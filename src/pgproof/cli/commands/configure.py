"""`pgproof configure`: the core interview, recorded in PATH/pgproof.toml.

`docs/TECHNICAL_DESIGN.md` section 2: `pgproof configure PATH [--non-interactive]`.
Non-interactive mode never prompts; it fails with the missing decision.
`docs/INTERFACE_DESIGN.md`'s "no conversational chat metaphor": each question
is a discrete labelled prompt (prompt, why it matters, choices), not a
free-flowing exchange, and a blank line always means "unknown" — never a
guessed default.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click

from pgproof.adapters.repository.config_toml import read_config, write_config
from pgproof.adapters.repository.inventory import app_source_paths, discover
from pgproof.adapters.repository.sqlalchemy_static import parse_models
from pgproof.application.configure import (
    build_state,
    missing_decision,
    record_answer,
    record_table_scale,
)
from pgproof.cli.exit_codes import CliError, ExitCode
from pgproof.cli.rendering.capabilities import TerminalCapabilities, detect_capabilities
from pgproof.cli.rendering.marks import Mark
from pgproof.cli.rendering.primitives import stage_line
from pgproof.domain.identifiers import table_id
from pgproof.domain.ir.context import AnswerState, ContextIR, TableScale
from pgproof.domain.ir.schema import SchemaIR
from pgproof.domain.questions import CORE_TABLE_SCALE, MaterialQuestion

_CONFIG_FILENAME = "pgproof.toml"


def _load_schema(root: Path) -> SchemaIR:
    inventory = discover(root)
    paths = app_source_paths(inventory, root)
    return parse_models(paths, root=root).schema


def _parse_table_scale_input(raw: str) -> tuple[TableScale, ...]:
    """`"orders:1000:5000, users:200"` to one `TableScale` per named table.

    A missing count is left `None` rather than guessed at; a bare table name
    is assumed to live in `public`, matching BE-08/BE-09's own default schema.
    """
    scales = []
    for chunk in raw.split(","):
        parts = [part.strip() for part in chunk.split(":")]
        if not parts or not parts[0]:
            continue
        current = parts[1] if len(parts) > 1 and parts[1] else None
        future = parts[2] if len(parts) > 2 and parts[2] else None
        scales.append(
            TableScale(
                table=table_id("public", parts[0]),
                current_rows=current,
                rows_in_twelve_months=future,
            )
        )
    return tuple(scales)


def _echo_question(question: MaterialQuestion, *, caps: TerminalCapabilities, width: int) -> None:
    click.echo(stage_line(Mark.ATTENTION, question.prompt, caps=caps, width=width))
    click.echo(f"    why it matters: {question.why_it_matters}")
    if question.choices:
        click.echo(f"    choices: {', '.join(question.choices)}")
    click.echo("    (leave blank for 'unknown')")


def _prompt_table_scale(
    context: ContextIR, question: MaterialQuestion, *, caps: TerminalCapabilities, width: int
) -> ContextIR:
    _echo_question(question, caps=caps, width=width)
    click.echo("    format: 'table:current_rows:rows_in_12_months', comma-separated")
    raw = click.prompt("  >", default="", show_default=False)
    if not raw.strip():
        return record_table_scale(context, (), state=AnswerState.UNKNOWN)
    return record_table_scale(context, _parse_table_scale_input(raw), state=AnswerState.ANSWERED)


def _prompt_core_answer(
    context: ContextIR, question: MaterialQuestion, *, caps: TerminalCapabilities, width: int
) -> ContextIR:
    _echo_question(question, caps=caps, width=width)
    raw = click.prompt("  >", default="", show_default=False)
    if not raw.strip():
        return record_answer(context, question, state=AnswerState.UNKNOWN)
    return record_answer(context, question, state=AnswerState.ANSWERED, value=raw.strip())


@click.command("configure")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
)
@click.option(
    "--non-interactive", is_flag=True, help="Never prompt; fail with the first missing decision."
)
@click.pass_context
def configure(ctx: click.Context, path: Path, non_interactive: bool) -> None:
    """Answer the core interview and record it in PATH/pgproof.toml."""
    root = path.resolve()
    schema = _load_schema(root)
    config_path = root / _CONFIG_FILENAME
    config = read_config(config_path)
    obj = ctx.obj or {}
    caps = detect_capabilities(sys.stdout, force_ascii=bool(obj.get("force_ascii", False)))
    width = shutil.get_terminal_size((80, 24)).columns if caps.interactive else 80

    context = config.context
    while True:
        question = missing_decision(build_state(schema, context))
        if question is None:
            break
        if non_interactive:
            raise CliError(
                f"missing decision: {question.id} ({question.prompt})",
                exit_code=ExitCode.INVALID_ARGUMENTS,
            )
        if question.id == CORE_TABLE_SCALE:
            context = _prompt_table_scale(context, question, caps=caps, width=width)
        else:
            context = _prompt_core_answer(context, question, caps=caps, width=width)

    write_config(config_path, config.model_copy(update={"context": context}))
    click.echo(
        stage_line(
            Mark.OK, f"{_CONFIG_FILENAME} updated", detail=str(config_path), caps=caps, width=width
        )
    )

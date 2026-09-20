"""`pgproof inspect`: the bounded repository inventory, `docs/TECHNICAL_DESIGN.md` section 5.

Schema/code reconstruction (BE-08, BE-09, BE-10) is not implemented yet, so
this command's terminal output is deliberately thinner than the full
`inspect` mockup in `docs/INTERFACE_DESIGN.md`: it reports what the inventory
found, not a design or its questions.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import click

from pgproof.adapters.repository.inventory import discover
from pgproof.cli.rendering.capabilities import TerminalCapabilities, detect_capabilities
from pgproof.cli.rendering.marks import Mark
from pgproof.cli.rendering.primitives import next_command, stage_line, trailer_line
from pgproof.ports.repository import RepositoryInventory

_MAX_SKIPPED_SHOWN = 5


def _revision_count(inventory: RepositoryInventory, alembic_dir: str) -> int:
    prefix = f"{alembic_dir}/versions/"
    return sum(1 for ref in inventory.included if ref.path.startswith(prefix))


def _inventory_to_json(inventory: RepositoryInventory) -> dict[str, Any]:
    return {
        "root": inventory.root,
        "gitignore_respected": inventory.gitignore_respected,
        "truncated": inventory.truncated,
        "total_bytes": inventory.total_bytes,
        "included": [ref.canonical_dict() for ref in inventory.included],
        "skipped": [dataclasses.asdict(entry) for entry in inventory.skipped],
        "signals": dataclasses.asdict(inventory.signals),
    }


def render_inventory(
    inventory: RepositoryInventory, *, caps: TerminalCapabilities, width: int, verbose: bool
) -> str:
    signals = inventory.signals
    lines = []
    if signals.uses_sqlalchemy or signals.uses_sqlmodel:
        orm = "SQLModel" if signals.uses_sqlmodel else "SQLAlchemy"
        lines.append(stage_line(Mark.OK, f"{orm} imports detected", caps=caps, width=width))
    else:
        lines.append(
            stage_line(
                Mark.UNAVAILABLE, "No SQLAlchemy/SQLModel imports found", caps=caps, width=width
            )
        )

    if signals.uses_alembic:
        total_revisions = sum(_revision_count(inventory, d) for d in signals.alembic_directories)
        detail = f"{total_revisions} revision file(s), not yet parsed"
        lines.append(
            stage_line(
                Mark.OK, "Alembic migrations detected", detail=detail, caps=caps, width=width
            )
        )
    else:
        lines.append(
            stage_line(Mark.UNAVAILABLE, "No Alembic migrations found", caps=caps, width=width)
        )

    if signals.docker_files:
        lines.append(
            stage_line(
                Mark.OK,
                "Docker files detected",
                detail=", ".join(signals.docker_files),
                caps=caps,
                width=width,
            )
        )
    else:
        lines.append(stage_line(Mark.UNAVAILABLE, "No Docker files found", caps=caps, width=width))

    lines.append(
        stage_line(
            Mark.OK if signals.has_tests else Mark.UNAVAILABLE,
            "Test layout detected" if signals.has_tests else "No test layout found",
            caps=caps,
            width=width,
        )
    )
    lines.append(
        stage_line(
            Mark.UNAVAILABLE,
            "Schema/code reconstruction not yet run",
            detail="lands in BE-08/BE-09/BE-10",
            caps=caps,
            width=width,
        )
    )
    lines.append("")
    lines.append(
        trailer_line(
            "Included", f"{len(inventory.included)} file(s), {inventory.total_bytes:,} bytes hashed"
        )
    )
    lines.append(trailer_line("Skipped", f"{len(inventory.skipped)} file(s)"))
    if inventory.skipped:
        shown = inventory.skipped if verbose else inventory.skipped[:_MAX_SKIPPED_SHOWN]
        for entry in shown:
            lines.append(f"    {entry.path}: {entry.reason}")
        hidden = len(inventory.skipped) - len(shown)
        if hidden > 0:
            lines.append(f"    ... and {hidden} more (--verbose to show all)")
    if inventory.truncated:
        lines.append("")
        lines.append(
            stage_line(
                Mark.ATTENTION,
                "Total size limit reached; some files were not read",
                caps=caps,
                width=width,
            )
        )
    if not inventory.gitignore_respected:
        lines.append("")
        lines.append(
            stage_line(
                Mark.ATTENTION,
                "Not a usable git repository: .gitignore was not consulted",
                detail="only pgproof's own exclusions applied",
                caps=caps,
                width=width,
            )
        )
    lines.append("")
    lines.append(
        next_command("pgproof configure ." if signals.uses_sqlalchemy else "pgproof doctor .")
    )
    return "\n".join(lines)


@click.command("inspect")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["terminal", "json"]),
    default="terminal",
    help="terminal (default) or json.",
)
@click.option(
    "--force",
    "_force",
    is_flag=True,
    help="Reserved: inventory has no cache yet (BE-04's cache-key abstraction is not wired to a "
    "stage runner), so every run already rescans. No additional effect today.",
)
@click.pass_context
def inspect_(ctx: click.Context, path: Path, output_format: str, _force: bool) -> None:
    """Discover PATH's files and report ORM/migration/test/Docker signals."""
    inventory = discover(path)
    if output_format == "json":
        click.echo(json.dumps(_inventory_to_json(inventory), sort_keys=True, indent=2))
        return
    obj = ctx.obj or {}
    caps = detect_capabilities(sys.stdout, force_ascii=bool(obj.get("force_ascii", False)))
    width = shutil.get_terminal_size((80, 24)).columns if caps.interactive else 80
    verbose = bool(obj.get("verbose", False))
    click.echo(render_inventory(inventory, caps=caps, width=width, verbose=verbose))

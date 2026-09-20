"""`pgproof inspect`: bounded repository inventory plus static Alembic parsing.

`docs/TECHNICAL_DESIGN.md` sections 5 and 6. SQLAlchemy model reconstruction
and schema/code reconciliation (BE-09, BE-10) are not implemented yet, so this
command's terminal output is deliberately thinner than the full `inspect`
mockup in `docs/INTERFACE_DESIGN.md`: it reports what static analysis found,
not a design, its questions, or its recommendations.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import click

from pgproof.adapters.repository.alembic_static import AlembicStaticResult, parse_migrations
from pgproof.adapters.repository.inventory import discover
from pgproof.cli.rendering.capabilities import TerminalCapabilities, detect_capabilities
from pgproof.cli.rendering.marks import Mark
from pgproof.cli.rendering.primitives import next_command, stage_line, trailer_line
from pgproof.ports.repository import RepositoryInventory

_MAX_SKIPPED_SHOWN = 5


def _parse_alembic_directories(
    inventory: RepositoryInventory, root: Path
) -> dict[str, AlembicStaticResult]:
    """One parse per declared Alembic environment; a repository may host more than one."""
    results: dict[str, AlembicStaticResult] = {}
    for alembic_dir in inventory.signals.alembic_directories:
        versions_dir = root / alembic_dir / "versions"
        version_paths = sorted(versions_dir.glob("*.py")) if versions_dir.is_dir() else []
        results[alembic_dir] = parse_migrations(version_paths, root=root)
    return results


def _alembic_result_to_json(result: AlembicStaticResult) -> dict[str, Any]:
    return {
        "revisions": [
            {
                "revision": info.revision,
                "down_revisions": list(info.down_revisions),
                "branch_labels": list(info.branch_labels),
                "depends_on": list(info.depends_on),
                "message": info.message,
                "source": info.source.canonical_dict(),
            }
            for info in result.revisions
        ],
        "graph": dataclasses.asdict(result.graph),
        "schema": result.schema.canonical_dict(),
    }


def _inventory_to_json(inventory: RepositoryInventory, root: Path) -> dict[str, Any]:
    alembic = _parse_alembic_directories(inventory, root)
    return {
        "root": inventory.root,
        "gitignore_respected": inventory.gitignore_respected,
        "truncated": inventory.truncated,
        "total_bytes": inventory.total_bytes,
        "included": [ref.canonical_dict() for ref in inventory.included],
        "skipped": [dataclasses.asdict(entry) for entry in inventory.skipped],
        "signals": dataclasses.asdict(inventory.signals),
        "alembic": {
            directory: _alembic_result_to_json(result) for directory, result in alembic.items()
        },
    }


def _alembic_stage_line(
    directory: str, result: AlembicStaticResult, *, caps: TerminalCapabilities, width: int
) -> str:
    graph = result.graph
    count = len(result.revisions)
    if len(graph.heads) == 1 and not graph.cycle and not graph.missing_predecessors:
        detail = f"{count} revision(s), head {graph.heads[0]}"
        return stage_line(
            Mark.OK,
            f"Alembic migrations detected ({directory})",
            detail=detail,
            caps=caps,
            width=width,
        )
    if graph.cycle:
        issue = f"a revision cycle ({' -> '.join(graph.cycle)})"
    elif graph.missing_predecessors:
        issue = f"a missing predecessor ({', '.join(graph.missing_predecessors)})"
    else:
        issue = f"{len(graph.heads)} heads ({', '.join(graph.heads)})"
    return stage_line(
        Mark.ATTENTION,
        f"Alembic migrations detected ({directory})",
        detail=f"{count} revision(s), {issue}",
        caps=caps,
        width=width,
    )


def _schema_replay_line(
    alembic: dict[str, AlembicStaticResult], *, caps: TerminalCapabilities, width: int
) -> str:
    if not alembic:
        return stage_line(
            Mark.UNAVAILABLE,
            "Static migration replay not run: no Alembic migrations",
            caps=caps,
            width=width,
        )
    replayed = [result for result in alembic.values() if result.schema.migration_head is not None]
    if not replayed:
        return stage_line(
            Mark.UNAVAILABLE,
            "Static migration replay skipped: the revision graph is ambiguous",
            caps=caps,
            width=width,
        )
    table_count = sum(len(result.schema.tables) for result in replayed)
    unsupported_count = sum(len(result.schema.unsupported) for result in alembic.values())
    detail = f"{table_count} table(s) from Alembic alone"
    if unsupported_count:
        detail += f", {unsupported_count} construct(s) not statically interpreted"
    return stage_line(Mark.OK, "Static migration replay", detail=detail, caps=caps, width=width)


def render_inventory(
    inventory: RepositoryInventory,
    alembic: dict[str, AlembicStaticResult],
    *,
    caps: TerminalCapabilities,
    width: int,
    verbose: bool,
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
        for directory, result in alembic.items():
            lines.append(_alembic_stage_line(directory, result, caps=caps, width=width))
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
    lines.append(_schema_replay_line(alembic, caps=caps, width=width))
    lines.append(
        stage_line(
            Mark.UNAVAILABLE,
            "SQLAlchemy model reconstruction and physical reconciliation not yet run",
            detail="lands in BE-09/BE-10",
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
    root = path.resolve()
    inventory = discover(root)
    if output_format == "json":
        click.echo(json.dumps(_inventory_to_json(inventory, root), sort_keys=True, indent=2))
        return
    alembic = _parse_alembic_directories(inventory, root)
    obj = ctx.obj or {}
    caps = detect_capabilities(sys.stdout, force_ascii=bool(obj.get("force_ascii", False)))
    width = shutil.get_terminal_size((80, 24)).columns if caps.interactive else 80
    verbose = bool(obj.get("verbose", False))
    click.echo(render_inventory(inventory, alembic, caps=caps, width=width, verbose=verbose))

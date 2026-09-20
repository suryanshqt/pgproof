"""`pgproof clean`: pgproof-owned local resources. `docs/TECHNICAL_DESIGN.md:45,692`.

"`pgproof clean --containers` lists exact resources and asks before removal."
Stored run directories under `.pgproof/runs/` are the same kind of disposable,
pgproof-owned local state, so `--runs` follows the identical list-then-confirm
shape.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click

from pgproof.adapters.runner.docker import find_orphaned_containers, remove_containers
from pgproof.cli.rendering.capabilities import detect_capabilities
from pgproof.cli.rendering.marks import Mark
from pgproof.cli.rendering.primitives import stage_line
from pgproof.store.paths import ProjectLayout


def _stale_run_dirs(layout: ProjectLayout) -> tuple[Path, ...]:
    if not layout.runs_dir.is_dir():
        return ()
    return tuple(sorted(entry for entry in layout.runs_dir.iterdir() if entry.is_dir()))


def _confirm(prompt: str, *, yes: bool) -> bool:
    if yes:
        return True
    try:
        return click.confirm(prompt)
    except click.exceptions.Abort:
        return False


@click.command("clean")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
)
@click.option("--containers", is_flag=True, help="Remove orphaned pgproof-owned containers.")
@click.option("--runs", "clean_runs", is_flag=True, help="Remove stored .pgproof/runs directories.")
@click.option("--yes", is_flag=True, help="Remove without an interactive confirmation.")
@click.pass_context
def clean(ctx: click.Context, path: Path, containers: bool, clean_runs: bool, yes: bool) -> None:
    """List and, on confirmation, remove pgproof-owned local resources for PATH."""
    if not containers and not clean_runs:
        click.echo("Nothing selected. Pass --containers and/or --runs.")
        return
    force_ascii = bool((ctx.obj or {}).get("force_ascii", False))
    caps = detect_capabilities(sys.stdout, force_ascii=force_ascii)
    width = shutil.get_terminal_size((80, 24)).columns if caps.interactive else 80

    if containers:
        orphans = find_orphaned_containers()
        if not orphans:
            click.echo(stage_line(Mark.OK, "No orphaned containers", caps=caps, width=width))
        else:
            for orphan in orphans:
                click.echo(
                    stage_line(
                        Mark.ATTENTION, orphan.name, detail=orphan.id[:12], caps=caps, width=width
                    )
                )
            if _confirm(f"Remove {len(orphans)} container(s)?", yes=yes):
                remove_containers([orphan.id for orphan in orphans])
                click.echo(
                    stage_line(
                        Mark.OK, f"Removed {len(orphans)} container(s)", caps=caps, width=width
                    )
                )

    if clean_runs:
        layout = ProjectLayout(path.resolve())
        run_dirs = _stale_run_dirs(layout)
        if not run_dirs:
            click.echo(stage_line(Mark.OK, "No stored runs", caps=caps, width=width))
        else:
            for run_dir in run_dirs:
                click.echo(stage_line(Mark.ATTENTION, run_dir.name, caps=caps, width=width))
            noun = "run" if len(run_dirs) == 1 else "runs"
            if _confirm(f"Remove {len(run_dirs)} stored {noun}?", yes=yes):
                for run_dir in run_dirs:
                    shutil.rmtree(run_dir)
                click.echo(
                    stage_line(
                        Mark.OK, f"Removed {len(run_dirs)} stored {noun}", caps=caps, width=width
                    )
                )

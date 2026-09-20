"""`pgproof doctor`: which modes can run in this environment and repository.

`ideation/03-product-experience.md`: "reports supported Python/PostgreSQL
tooling... Docker availability, and which modes can run. Missing Docker does
not block parse-only inspection." Repository framework/migration detection is
`pgproof.adapters` territory (BE-07); this command only reports signals cheap
enough to need no adapter: whether the path looks like a git repository,
whether Docker is reachable, and (BE-16) whether any pgproof-owned container
was left behind by a crashed or killed run, `docs/TECHNICAL_DESIGN.md:692`.
"""

from __future__ import annotations

import dataclasses
import json
import platform
import shutil
import sys
from pathlib import Path

import click

from pgproof import __version__
from pgproof.adapters.runner.docker import DockerCapability, find_orphaned_containers, probe_docker
from pgproof.cli.rendering.capabilities import TerminalCapabilities, detect_capabilities
from pgproof.cli.rendering.marks import Mark
from pgproof.cli.rendering.primitives import stage_line

__all__ = [
    "DockerCapability",
    "probe_docker",
]  # re-exported: existing import site, doctor's own tests


@dataclasses.dataclass(frozen=True)
class DoctorReport:
    pgproof_version: str
    python_version: str
    path: str
    git_repository: bool
    docker: DockerCapability
    parse_only_available: bool
    isolated_execution_available: bool
    isolated_execution_note: str | None
    orphaned_containers: int


def build_report(
    path: Path,
    *,
    docker: DockerCapability | None = None,
    orphaned_containers: int | None = None,
) -> DoctorReport:
    resolved_docker = docker if docker is not None else probe_docker()
    isolated_available = resolved_docker.daemon_reachable
    if orphaned_containers is None:
        orphaned_containers = len(find_orphaned_containers()) if isolated_available else 0
    return DoctorReport(
        pgproof_version=__version__,
        python_version=platform.python_version(),
        path=str(path),
        git_repository=(path / ".git").exists(),
        docker=resolved_docker,
        parse_only_available=True,
        isolated_execution_available=isolated_available,
        isolated_execution_note=None if isolated_available else "Docker daemon not reachable",
        orphaned_containers=orphaned_containers,
    )


def _docker_mark_and_text(docker: DockerCapability) -> tuple[Mark, str]:
    if docker.daemon_reachable:
        return Mark.OK, "Docker daemon reachable"
    if docker.cli_found:
        return Mark.ATTENTION, "Docker CLI found, daemon not reachable"
    return Mark.UNAVAILABLE, "Docker not detected"


def render_report(report: DoctorReport, *, caps: TerminalCapabilities, width: int) -> str:
    docker_mark, docker_text = _docker_mark_and_text(report.docker)
    lines = [
        stage_line(
            Mark.OK,
            f"pgproof {report.pgproof_version}",
            detail=f"Python {report.python_version}",
            caps=caps,
            width=width,
        ),
        stage_line(
            Mark.OK if report.git_repository else Mark.UNAVAILABLE,
            "Git repository detected" if report.git_repository else "Not a git repository",
            detail=report.path,
            caps=caps,
            width=width,
        ),
        stage_line(docker_mark, docker_text, caps=caps, width=width),
    ]
    if report.orphaned_containers:
        lines.append(
            stage_line(
                Mark.ATTENTION,
                f"{report.orphaned_containers} orphaned container(s)",
                detail="pgproof clean --containers",
                caps=caps,
                width=width,
            )
        )
    lines += [
        "",
        stage_line(Mark.OK, "Parse-only inspection", detail="available", caps=caps, width=width),
        stage_line(
            Mark.OK if report.isolated_execution_available else Mark.UNAVAILABLE,
            "Isolated execution (capture, verify)",
            detail=report.isolated_execution_note or "available",
            caps=caps,
            width=width,
        ),
    ]
    return "\n".join(lines)


@click.command("doctor")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
)
@click.option("--json", "as_json", is_flag=True, help="Write the capability report as JSON.")
@click.pass_context
def doctor(ctx: click.Context, path: Path, as_json: bool) -> None:
    """Report which pgproof modes can run, for PATH and this host."""
    report = build_report(path.resolve())
    if as_json:
        click.echo(json.dumps(dataclasses.asdict(report), sort_keys=True, indent=2))
        return
    force_ascii = bool((ctx.obj or {}).get("force_ascii", False))
    caps = detect_capabilities(sys.stdout, force_ascii=force_ascii)
    width = shutil.get_terminal_size((80, 24)).columns if caps.interactive else 80
    click.echo(render_report(report, caps=caps, width=width))

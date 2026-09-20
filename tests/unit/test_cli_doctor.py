"""`pgproof doctor`: report shape, JSON mode, exit codes, and the snapshot matrix."""

import json
import re
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from pgproof.cli.app import main
from pgproof.cli.commands.doctor import (
    DockerCapability,
    build_report,
    probe_docker,
    render_report,
)
from pgproof.cli.rendering.capabilities import TerminalCapabilities

_REACHABLE = DockerCapability(cli_found=True, daemon_reachable=True)
_CLI_ONLY = DockerCapability(cli_found=True, daemon_reachable=False)
_ABSENT = DockerCapability(cli_found=False, daemon_reachable=False)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _visible(text: str) -> str:
    return _ANSI.sub("", text)


# --------------------------------------------------------------------------- #
# Docker probing
# --------------------------------------------------------------------------- #
def test_probe_reports_absent_when_the_cli_is_not_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert probe_docker() == _ABSENT


def test_probe_reports_cli_only_when_the_daemon_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_a, **_k: subprocess.CompletedProcess(args=[], returncode=1),
    )
    assert probe_docker() == _CLI_ONLY


def test_probe_reports_cli_only_when_the_daemon_call_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd="docker info", timeout=3)

    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr("subprocess.run", _raise)
    assert probe_docker() == _CLI_ONLY


def test_probe_reports_reachable_on_a_zero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_a, **_k: subprocess.CompletedProcess(args=[], returncode=0),
    )
    assert probe_docker() == _REACHABLE


# --------------------------------------------------------------------------- #
# Report contents
# --------------------------------------------------------------------------- #
def test_a_git_repository_is_detected(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    report = build_report(tmp_path, docker=_ABSENT)
    assert report.git_repository is True


def test_a_plain_directory_is_not_a_git_repository(tmp_path: Path) -> None:
    report = build_report(tmp_path, docker=_ABSENT)
    assert report.git_repository is False


def test_isolated_execution_is_available_only_when_the_daemon_is_reachable(
    tmp_path: Path,
) -> None:
    assert (
        build_report(
            tmp_path, docker=_REACHABLE, orphaned_containers=0
        ).isolated_execution_available
        is True
    )
    assert build_report(tmp_path, docker=_CLI_ONLY).isolated_execution_available is False
    assert build_report(tmp_path, docker=_ABSENT).isolated_execution_note is not None


def test_parse_only_is_always_available_regardless_of_docker(tmp_path: Path) -> None:
    """`ideation/03-product-experience.md`: missing Docker never blocks parse-only inspection."""
    assert build_report(tmp_path, docker=_ABSENT).parse_only_available is True


def test_orphaned_containers_defaults_to_zero_when_docker_is_unavailable(tmp_path: Path) -> None:
    """A daemon that cannot be reached is never probed for orphans."""
    assert build_report(tmp_path, docker=_ABSENT).orphaned_containers == 0


def test_orphaned_containers_is_probed_only_when_the_daemon_is_reachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pgproof.adapters.runner.docker import OrphanedContainer

    monkeypatch.setattr(
        "pgproof.cli.commands.doctor.find_orphaned_containers",
        lambda: (OrphanedContainer(id="abc123", name="pgproof-runner-abc123"),),
    )
    assert build_report(tmp_path, docker=_REACHABLE).orphaned_containers == 1
    assert build_report(tmp_path, docker=_CLI_ONLY).orphaned_containers == 0


def test_an_explicit_orphaned_containers_count_overrides_the_probe(tmp_path: Path) -> None:
    assert build_report(tmp_path, docker=_REACHABLE, orphaned_containers=3).orphaned_containers == 3


# --------------------------------------------------------------------------- #
# CLI invocation
# --------------------------------------------------------------------------- #
def test_doctor_exits_zero_even_when_docker_is_entirely_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    result = CliRunner().invoke(main, ["doctor", str(tmp_path)])
    assert result.exit_code == 0


def test_doctor_rejects_a_nonexistent_path_with_exit_code_two() -> None:
    result = CliRunner().invoke(main, ["doctor", "/no/such/path"])
    assert result.exit_code == 2


def test_doctor_json_mode_writes_only_the_report_to_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    result = CliRunner().invoke(main, ["doctor", str(tmp_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["parse_only_available"] is True
    assert payload["docker"] == {"cli_found": False, "daemon_reachable": False}


def test_doctor_ascii_flag_produces_no_unicode_glyphs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    result = CliRunner().invoke(main, ["--ascii", "doctor", str(tmp_path)])
    assert result.exit_code == 0
    assert all(ord(char) < 128 for char in result.output)


def test_doctor_non_tty_output_contains_no_ansi_escape_codes(tmp_path: Path) -> None:
    """`click.testing.CliRunner` is never a TTY, matching non-TTY CI logs."""
    result = CliRunner().invoke(main, ["doctor", str(tmp_path)])
    assert "\x1b" not in result.output


# --------------------------------------------------------------------------- #
# Snapshot matrix: 80/120 columns; Unicode/ASCII; color/no-color; success/partial
# --------------------------------------------------------------------------- #
def test_snapshot_80_columns_unicode_color_all_capabilities_available() -> None:
    report = build_report(Path("/repo"), docker=_REACHABLE, orphaned_containers=0)
    caps = TerminalCapabilities(interactive=True, color=True, unicode=True)
    text = render_report(report, caps=caps, width=80)
    assert text.splitlines()[0].startswith("\x1b[32m✓\x1b[0m pgproof")
    assert "Docker daemon reachable" in text
    assert "Isolated execution (capture, verify)" in text
    assert max(len(_visible(line)) for line in text.splitlines()) <= 80


def test_snapshot_120_columns_unicode_no_color_partial_docker() -> None:
    report = build_report(Path("/repo"), docker=_CLI_ONLY)
    caps = TerminalCapabilities(interactive=True, color=False, unicode=True)
    text = render_report(report, caps=caps, width=120)
    assert "! Docker CLI found, daemon not reachable" in text
    assert "○ Isolated execution (capture, verify)" in text
    assert max(len(_visible(line)) for line in text.splitlines()) <= 120


def test_snapshot_80_columns_ascii_no_color_non_tty_docker_absent() -> None:
    report = build_report(Path("/repo"), docker=_ABSENT)
    caps = TerminalCapabilities(interactive=False, color=False, unicode=False)
    text = render_report(report, caps=caps, width=80)
    assert all(ord(char) < 128 for char in text)
    assert "[-] Docker not detected" in text
    assert "[-] Isolated execution (capture, verify)" in text


def test_snapshot_repository_not_git_shows_the_unavailable_mark() -> None:
    report = build_report(Path("/tmp/not-a-repo"), docker=_ABSENT)
    caps = TerminalCapabilities(interactive=False, color=False, unicode=True)
    text = render_report(report, caps=caps, width=80)
    assert "○ Not a git repository" in text


def test_orphaned_containers_are_reported_with_the_cleanup_command() -> None:
    report = build_report(Path("/repo"), docker=_REACHABLE, orphaned_containers=2)
    caps = TerminalCapabilities(interactive=False, color=False, unicode=True)
    text = render_report(report, caps=caps, width=80)
    assert "2 orphaned container(s)" in text
    assert "pgproof clean --containers" in text


def test_no_orphaned_containers_line_when_there_are_none() -> None:
    report = build_report(Path("/repo"), docker=_REACHABLE, orphaned_containers=0)
    caps = TerminalCapabilities(interactive=False, color=False, unicode=True)
    text = render_report(report, caps=caps, width=80)
    assert "orphaned container" not in text

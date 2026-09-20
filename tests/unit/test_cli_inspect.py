"""`pgproof inspect`: terminal and JSON output, over the bounded inventory."""

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from pgproof.cli.app import main
from pgproof.ports.repository import FrameworkSignals, RepositoryInventory

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _write(root: Path, relative: str, content: str = "x") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_inspect_rejects_a_nonexistent_path() -> None:
    result = CliRunner().invoke(main, ["inspect", "/no/such/path"])
    assert result.exit_code == 2


def test_inspect_on_an_empty_directory_shows_every_signal_as_unavailable(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["--ascii", "inspect", str(tmp_path)])
    assert result.exit_code == 0
    assert "No SQLAlchemy/SQLModel imports found" in result.output
    assert "No Alembic migrations found" in result.output
    assert "No Docker files found" in result.output
    assert "No test layout found" in result.output
    assert "Schema/code reconstruction not yet run" in result.output
    assert "Next" in result.output


def test_inspect_detects_sqlalchemy_and_alembic(tmp_path: Path) -> None:
    _write(tmp_path, "models.py", "import sqlalchemy\n")
    _write(tmp_path, "migrations/env.py")
    _write(tmp_path, "migrations/versions/0001_init.py")
    result = CliRunner().invoke(main, ["--ascii", "inspect", str(tmp_path)])
    assert result.exit_code == 0
    assert "SQLAlchemy imports detected" in result.output
    assert "Alembic migrations detected" in result.output
    assert "1 revision file(s)" in result.output
    assert "pgproof configure ." in result.output


def test_inspect_recommends_doctor_when_no_orm_is_found(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["--ascii", "inspect", str(tmp_path)])
    assert "pgproof doctor ." in result.output


def test_inspect_reports_a_capped_skip_list_by_default(tmp_path: Path) -> None:
    for index in range(8):
        _write(tmp_path, f".env.{index}", "secret")
    result = CliRunner().invoke(main, ["--ascii", "inspect", str(tmp_path)])
    assert "more (--verbose to show all)" in result.output
    shown = sum(1 for index in range(8) if f".env.{index}:" in result.output)
    assert shown == 5


def test_inspect_verbose_shows_every_skipped_entry(tmp_path: Path) -> None:
    for index in range(8):
        _write(tmp_path, f".env.{index}", "secret")
    result = CliRunner().invoke(main, ["--verbose", "--ascii", "inspect", str(tmp_path)])
    assert "more (--verbose to show all)" not in result.output
    for index in range(8):
        assert f".env.{index}" in result.output


def test_inspect_shows_docker_files_when_present(tmp_path: Path) -> None:
    _write(tmp_path, "Dockerfile", "FROM python:3.13\n")
    result = CliRunner().invoke(main, ["--ascii", "inspect", str(tmp_path)])
    assert "Docker files detected" in result.output
    assert "Dockerfile" in result.output


def _empty_inventory(root: Path, **overrides: object) -> RepositoryInventory:
    defaults: dict[str, object] = {
        "root": str(root),
        "included": (),
        "skipped": (),
        "signals": FrameworkSignals(
            package_name=None,
            uses_alembic=False,
            alembic_directories=(),
            uses_sqlalchemy=False,
            uses_sqlmodel=False,
            has_tests=False,
            docker_files=(),
            likely_app_roots=(),
        ),
        "total_bytes": 0,
        "truncated": False,
        "gitignore_respected": True,
    }
    defaults.update(overrides)
    return RepositoryInventory(**defaults)  # type: ignore[arg-type]


def test_inspect_flags_a_truncated_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pgproof.cli.commands.inspect.discover",
        lambda _path: _empty_inventory(tmp_path, truncated=True),
    )
    result = CliRunner().invoke(main, ["--ascii", "inspect", str(tmp_path)])
    assert "Total size limit reached" in result.output


def test_inspect_says_nothing_about_gitignore_when_it_was_respected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "pgproof.cli.commands.inspect.discover",
        lambda _path: _empty_inventory(tmp_path, gitignore_respected=True),
    )
    result = CliRunner().invoke(main, ["--ascii", "inspect", str(tmp_path)])
    assert "gitignore was not consulted" not in result.output


def test_inspect_flags_a_non_git_directory(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["--ascii", "inspect", str(tmp_path)])
    assert "gitignore was not consulted" in result.output


def test_inspect_force_flag_is_accepted(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["inspect", str(tmp_path), "--force"])
    assert result.exit_code == 0


def test_inspect_help_documents_its_options() -> None:
    result = CliRunner().invoke(main, ["inspect", "--help"])
    assert "--format" in result.output
    assert "--force" in result.output


# --------------------------------------------------------------------------- #
# JSON mode
# --------------------------------------------------------------------------- #
def test_inspect_json_mode_writes_only_the_report_to_stdout(tmp_path: Path) -> None:
    _write(tmp_path, "models.py", "import sqlalchemy\n")
    result = CliRunner().invoke(main, ["inspect", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["signals"]["uses_sqlalchemy"] is True
    assert payload["gitignore_respected"] is False
    assert any(entry["path"] == "models.py" for entry in payload["included"])


def test_inspect_json_mode_never_emits_ansi_codes(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["inspect", str(tmp_path), "--format", "json"])
    assert not _ANSI.search(result.output)

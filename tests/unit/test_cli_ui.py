"""`pgproof ui`: URL printed, `--no-open` honored, PATH validated."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from pgproof.cli.app import main


@pytest.fixture(autouse=True)
def _never_actually_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    """`serve()` blocks forever; every test replaces it with a no-op."""
    monkeypatch.setattr("pgproof.cli.commands.ui.serve", lambda _app, sock: sock.close())


def test_ui_prints_the_opened_url_with_a_token(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["ui", str(tmp_path), "--no-open"])
    assert result.exit_code == 0
    assert "http://127.0.0.1:" in result.output
    assert "token=" in result.output


def test_ui_opens_a_browser_unless_no_open_is_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("pgproof.cli.commands.ui.webbrowser.open", opened.append)
    CliRunner().invoke(main, ["ui", str(tmp_path)])
    assert len(opened) == 1
    assert opened[0].startswith("http://127.0.0.1:")


def test_ui_no_open_never_touches_the_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("pgproof.cli.commands.ui.webbrowser.open", opened.append)
    CliRunner().invoke(main, ["ui", str(tmp_path), "--no-open"])
    assert opened == []


def test_ui_rejects_a_nonexistent_path() -> None:
    result = CliRunner().invoke(main, ["ui", "/no/such/path"])
    assert result.exit_code == 2


def test_ui_creates_the_pgproof_layout(tmp_path: Path) -> None:
    CliRunner().invoke(main, ["ui", str(tmp_path), "--no-open"])
    assert (tmp_path / ".pgproof").is_dir()


def test_keep_open_is_accepted_and_currently_a_no_op(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["ui", str(tmp_path), "--no-open", "--keep-open"])
    assert result.exit_code == 0


def test_ui_help_documents_its_flags() -> None:
    result = CliRunner().invoke(main, ["ui", "--help"])
    assert "--no-open" in result.output
    assert "--keep-open" in result.output

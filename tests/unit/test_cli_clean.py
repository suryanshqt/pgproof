"""`pgproof clean`: listing, confirmation, and removal of owned local state."""

from pathlib import Path

import pytest
from click.testing import CliRunner

import pgproof.cli.commands.clean as clean_module
from pgproof.adapters.runner.docker import OrphanedContainer
from pgproof.cli.app import main


def test_with_no_flags_nothing_happens(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["clean", str(tmp_path)])
    assert result.exit_code == 0
    assert "Nothing selected" in result.output


# --------------------------------------------------------------------------- #
# --containers
# --------------------------------------------------------------------------- #
def test_no_orphans_reports_nothing_to_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(clean_module, "find_orphaned_containers", lambda: ())
    result = CliRunner().invoke(main, ["clean", str(tmp_path), "--containers"])
    assert result.exit_code == 0
    assert "No orphaned containers" in result.output


def test_orphans_are_listed_and_removed_on_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        clean_module,
        "find_orphaned_containers",
        lambda: (OrphanedContainer(id="abcdef123456", name="pgproof-runner-abcdef"),),
    )
    removed: list[list[str]] = []
    monkeypatch.setattr(clean_module, "remove_containers", lambda ids: removed.append(list(ids)))
    result = CliRunner().invoke(main, ["clean", str(tmp_path), "--containers"], input="y\n")
    assert result.exit_code == 0
    assert "pgproof-runner-abcdef" in result.output
    assert "Removed 1 container(s)" in result.output
    assert removed == [["abcdef123456"]]


def test_declining_the_confirmation_removes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        clean_module,
        "find_orphaned_containers",
        lambda: (OrphanedContainer(id="abc", name="pgproof-runner-abc"),),
    )
    removed: list[list[str]] = []
    monkeypatch.setattr(clean_module, "remove_containers", lambda ids: removed.append(list(ids)))
    result = CliRunner().invoke(main, ["clean", str(tmp_path), "--containers"], input="n\n")
    assert result.exit_code == 0
    assert "Removed" not in result.output
    assert removed == []


def test_no_input_at_all_is_treated_as_declined_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        clean_module,
        "find_orphaned_containers",
        lambda: (OrphanedContainer(id="abc", name="pgproof-runner-abc"),),
    )

    def _fail(_ids: list[str]) -> None:
        raise AssertionError("remove_containers must not be called without confirmation")

    monkeypatch.setattr(clean_module, "remove_containers", _fail)
    result = CliRunner().invoke(main, ["clean", str(tmp_path), "--containers"], input="")
    assert result.exit_code == 0


def test_yes_flag_skips_the_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        clean_module,
        "find_orphaned_containers",
        lambda: (OrphanedContainer(id="abc", name="pgproof-runner-abc"),),
    )
    removed: list[list[str]] = []
    monkeypatch.setattr(clean_module, "remove_containers", lambda ids: removed.append(list(ids)))
    result = CliRunner().invoke(main, ["clean", str(tmp_path), "--containers", "--yes"])
    assert result.exit_code == 0
    assert removed == [["abc"]]


# --------------------------------------------------------------------------- #
# --runs
# --------------------------------------------------------------------------- #
def test_no_stored_runs_reports_nothing_to_remove(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["clean", str(tmp_path), "--runs"])
    assert result.exit_code == 0
    assert "No stored runs" in result.output


def test_stored_runs_are_listed_and_removed_on_yes(tmp_path: Path) -> None:
    runs_dir = tmp_path / ".pgproof" / "runs"
    (runs_dir / "01J000RUN0000000000000001").mkdir(parents=True)
    (runs_dir / "01J000RUN0000000000000002").mkdir(parents=True)
    result = CliRunner().invoke(main, ["clean", str(tmp_path), "--runs", "--yes"])
    assert result.exit_code == 0
    assert "Removed 2 stored runs" in result.output
    assert not any(runs_dir.iterdir())


def test_declining_run_removal_leaves_the_directory_in_place(tmp_path: Path) -> None:
    runs_dir = tmp_path / ".pgproof" / "runs"
    (runs_dir / "01J000RUN0000000000000001").mkdir(parents=True)
    result = CliRunner().invoke(main, ["clean", str(tmp_path), "--runs"], input="n\n")
    assert result.exit_code == 0
    assert (runs_dir / "01J000RUN0000000000000001").is_dir()


def test_a_single_stored_run_uses_the_singular_noun(tmp_path: Path) -> None:
    runs_dir = tmp_path / ".pgproof" / "runs"
    (runs_dir / "01J000RUN0000000000000001").mkdir(parents=True)
    result = CliRunner().invoke(main, ["clean", str(tmp_path), "--runs", "--yes"])
    assert "Removed 1 stored run\n" in result.output

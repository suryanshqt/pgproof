"""Bounded repository inventory: discovery, exclusions, symlink/size safety, signals."""

import os
import subprocess
from pathlib import Path

import pytest

from pgproof.adapters.repository.inventory import discover


def _write(root: Path, relative: str, content: str = "x") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)


def _has_git() -> bool:
    import shutil

    return shutil.which("git") is not None


requires_git = pytest.mark.skipif(not _has_git(), reason="git is not installed")


# --------------------------------------------------------------------------- #
# Fallback (non-git) discovery and exclusions
# --------------------------------------------------------------------------- #
def test_a_plain_file_is_included_and_hashed(tmp_path: Path) -> None:
    _write(tmp_path, "app.py", "print('hi')\n")
    inventory = discover(tmp_path)
    assert not inventory.gitignore_respected
    paths = {ref.path for ref in inventory.included}
    assert "app.py" in paths
    ref = next(r for r in inventory.included if r.path == "app.py")
    assert ref.content_hash.startswith("sha256:")


def test_excluded_directories_are_never_descended_into(tmp_path: Path) -> None:
    _write(tmp_path, ".venv/lib/site.py", "junk")
    _write(tmp_path, "app.py")
    inventory = discover(tmp_path)
    paths = {ref.path for ref in inventory.included}
    assert "app.py" in paths
    assert not any(".venv" in ref.path for ref in inventory.included)


def test_env_files_are_excluded(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "SECRET=1")
    _write(tmp_path, ".env.local", "SECRET=2")
    inventory = discover(tmp_path)
    assert inventory.included == ()
    reasons = {entry.path: entry.reason for entry in inventory.skipped}
    assert "excluded" in reasons[".env"]
    assert "excluded" in reasons[".env.local"]


def test_a_file_over_the_size_cap_is_skipped_with_its_size_in_the_reason(tmp_path: Path) -> None:
    _write(tmp_path, "big.txt", "a" * 11)
    inventory = discover(tmp_path, max_file_bytes=10)
    assert inventory.included == ()
    (entry,) = inventory.skipped
    assert entry.path == "big.txt"
    assert "11" in entry.reason


def test_the_total_byte_cap_truncates_and_reports_it(tmp_path: Path) -> None:
    _write(tmp_path, "one.txt", "a" * 6)
    _write(tmp_path, "two.txt", "a" * 6)
    inventory = discover(tmp_path, max_total_bytes=10)
    assert inventory.truncated is True
    assert len(inventory.included) == 1
    assert any("total size limit" in entry.reason for entry in inventory.skipped)


def test_a_symlink_pointing_outside_root_is_skipped(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("do not read me", encoding="utf-8")
    root = tmp_path / "project"
    root.mkdir()
    (root / "link.txt").symlink_to(outside)
    try:
        inventory = discover(root)
        assert inventory.included == ()
        (entry,) = inventory.skipped
        assert entry.path == "link.txt"
        assert "escapes the selected root" in entry.reason
    finally:
        outside.unlink()


def test_a_symlink_pointing_inside_root_is_included(tmp_path: Path) -> None:
    _write(tmp_path, "real.py", "print(1)\n")
    (tmp_path / "link.py").symlink_to(tmp_path / "real.py")
    inventory = discover(tmp_path)
    paths = {ref.path for ref in inventory.included}
    assert "real.py" in paths
    assert "link.py" in paths


# --------------------------------------------------------------------------- #
# Framework/migration/test/Docker signals
# --------------------------------------------------------------------------- #
def test_sqlalchemy_import_is_detected(tmp_path: Path) -> None:
    _write(tmp_path, "models.py", "import sqlalchemy\n")
    assert discover(tmp_path).signals.uses_sqlalchemy is True


def test_sqlmodel_import_is_detected_separately(tmp_path: Path) -> None:
    _write(tmp_path, "models.py", "from sqlmodel import SQLModel\n")
    signals = discover(tmp_path).signals
    assert signals.uses_sqlmodel is True
    assert signals.uses_sqlalchemy is False


def test_a_file_with_no_relevant_imports_detects_neither(tmp_path: Path) -> None:
    _write(tmp_path, "util.py", "import os\n")
    signals = discover(tmp_path).signals
    assert signals.uses_sqlalchemy is False
    assert signals.uses_sqlmodel is False


def test_a_syntactically_invalid_python_file_does_not_crash_discovery(tmp_path: Path) -> None:
    _write(tmp_path, "broken.py", "def (:\n")
    inventory = discover(tmp_path)
    assert any(ref.path == "broken.py" for ref in inventory.included)


def test_alembic_ini_alone_is_detected(tmp_path: Path) -> None:
    _write(tmp_path, "alembic.ini", "[alembic]\n")
    assert discover(tmp_path).signals.uses_alembic is True


def test_an_alembic_directory_with_versions_is_detected_and_counted(tmp_path: Path) -> None:
    _write(tmp_path, "migrations/env.py", "# env\n")
    _write(tmp_path, "migrations/versions/0001_init.py", "# rev\n")
    _write(tmp_path, "migrations/versions/0002_next.py", "# rev\n")
    inventory = discover(tmp_path)
    assert inventory.signals.uses_alembic is True
    assert inventory.signals.alembic_directories == ("migrations",)


def test_an_env_py_with_no_versions_directory_is_not_alembic(tmp_path: Path) -> None:
    _write(tmp_path, "somewhere/env.py", "# not alembic\n")
    assert discover(tmp_path).signals.uses_alembic is False


def test_docker_files_are_collected(tmp_path: Path) -> None:
    _write(tmp_path, "Dockerfile", "FROM python:3.13\n")
    _write(tmp_path, "docker-compose.yml", "services: {}\n")
    assert discover(tmp_path).signals.docker_files == ("Dockerfile", "docker-compose.yml")


def test_test_layout_is_detected_by_directory_or_filename(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_app.py", "def test_x(): pass\n")
    assert discover(tmp_path).signals.has_tests is True


def test_package_name_comes_from_pyproject(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nname = "demo-app"\n')
    assert discover(tmp_path).signals.package_name == "demo-app"


def test_a_malformed_pyproject_does_not_crash_discovery(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", "not valid toml [[[")
    assert discover(tmp_path).signals.package_name is None


def test_likely_app_roots_finds_top_level_and_src_packages(tmp_path: Path) -> None:
    _write(tmp_path, "demo/__init__.py")
    _write(tmp_path, "src/other/__init__.py")
    signals = discover(tmp_path).signals
    assert signals.likely_app_roots == ("demo", "other")


# --------------------------------------------------------------------------- #
# Git-based discovery
# --------------------------------------------------------------------------- #
@requires_git
def test_git_discovery_respects_gitignore(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, ".gitignore", "ignored.txt\n")
    _write(tmp_path, "ignored.txt", "should not appear")
    _write(tmp_path, "included.txt", "should appear")
    inventory = discover(tmp_path)
    assert inventory.gitignore_respected is True
    paths = {ref.path for ref in inventory.included}
    assert "included.txt" in paths
    assert "ignored.txt" not in paths


@requires_git
def test_git_discovery_still_applies_pgproofs_own_exclusions(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _write(tmp_path, ".env", "SECRET=1")
    _write(tmp_path, "app.py", "print(1)\n")
    inventory = discover(tmp_path)
    assert inventory.gitignore_respected is True
    paths = {ref.path for ref in inventory.included}
    assert "app.py" in paths
    assert ".env" not in paths


def test_a_directory_that_is_not_a_git_repository_falls_back_cleanly(tmp_path: Path) -> None:
    assert not (tmp_path / ".git").exists()
    inventory = discover(tmp_path)
    assert inventory.gitignore_respected is False


@requires_git
def test_a_git_directory_with_a_broken_git_binary_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "app.py")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    inventory = discover(tmp_path)
    assert inventory.gitignore_respected is False
    assert any(ref.path == "app.py" for ref in inventory.included)


def test_discovery_is_deterministic_in_file_order(tmp_path: Path) -> None:
    _write(tmp_path, "b.py")
    _write(tmp_path, "a.py")
    inventory = discover(tmp_path)
    assert [ref.path for ref in inventory.included] == sorted(
        ref.path for ref in inventory.included
    )


def test_os_walk_does_not_follow_symlinked_directories(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-dir"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("nope", encoding="utf-8")
    root = tmp_path / "project2"
    root.mkdir()
    (root / "link-dir").symlink_to(outside, target_is_directory=True)
    try:
        inventory = discover(root)
        assert not any("secret" in ref.path for ref in inventory.included)
    finally:
        (root / "link-dir").unlink()


# --------------------------------------------------------------------------- #
# Defensive branches
# --------------------------------------------------------------------------- #
def test_a_nested_excluded_directory_is_still_excluded(tmp_path: Path) -> None:
    _write(tmp_path, "sub/.venv/site.py", "junk")
    _write(tmp_path, "sub/app.py")
    inventory = discover(tmp_path)
    paths = {ref.path for ref in inventory.included}
    assert "sub/app.py" in paths
    assert not any(".venv" in ref.path for ref in inventory.included)


def test_a_compiled_python_file_is_excluded_by_suffix(tmp_path: Path) -> None:
    _write(tmp_path, "module.pyc", "junk")
    inventory = discover(tmp_path)
    assert inventory.included == ()
    (entry,) = inventory.skipped
    assert entry.reason == "excluded: .pyc file"


def test_a_git_command_failure_falls_back_to_the_filesystem_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git_init(tmp_path)
    _write(tmp_path, "app.py")

    def _raise(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd="git", timeout=10)

    monkeypatch.setattr("subprocess.run", _raise)
    inventory = discover(tmp_path)
    assert inventory.gitignore_respected is False
    assert any(ref.path == "app.py" for ref in inventory.included)


def test_a_symlink_that_cannot_be_resolved_is_treated_as_escaping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "real.py", "print(1)\n")
    (tmp_path / "link.py").symlink_to(tmp_path / "real.py")

    real_resolve = Path.resolve

    def _flaky_resolve(self: Path, strict: bool = False) -> Path:
        if self.name == "link.py":
            raise OSError("simulated resolution failure")
        return real_resolve(self, strict)

    monkeypatch.setattr(Path, "resolve", _flaky_resolve, raising=True)
    inventory = discover(tmp_path)
    assert not any(ref.path == "link.py" for ref in inventory.included)
    assert any(entry.path == "link.py" and "escapes" in entry.reason for entry in inventory.skipped)


def test_a_directory_candidate_from_git_is_not_mistaken_for_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`git ls-files` only lists blobs, but the walk defends against a bare directory anyway."""
    _write(tmp_path, "pkg/module.py")
    real_candidates = [tmp_path / "pkg", tmp_path / "pkg" / "module.py"]
    monkeypatch.setattr(
        "pgproof.adapters.repository.inventory._git_candidates", lambda _root: real_candidates
    )
    inventory = discover(tmp_path)
    paths = {ref.path for ref in inventory.included}
    assert paths == {"pkg/module.py"}


def test_a_nested_venv_git_tracked_by_mistake_is_still_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`git ls-files` only skips what the *target* project's own `.gitignore` names;
    pgproof's own exclusions apply on top, however deep the excluded directory sits."""
    _write(tmp_path, "vendor/.venv/site.py")
    _write(tmp_path, "vendor/app.py")
    candidates = [tmp_path / "vendor" / ".venv" / "site.py", tmp_path / "vendor" / "app.py"]
    monkeypatch.setattr(
        "pgproof.adapters.repository.inventory._git_candidates", lambda _root: candidates
    )
    inventory = discover(tmp_path)
    paths = {ref.path for ref in inventory.included}
    assert paths == {"vendor/app.py"}
    assert any(entry.reason == "excluded: .venv/" for entry in inventory.skipped)


def test_a_file_that_disappears_before_stat_is_reported_not_crashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "gone.py")
    real_stat = Path.stat

    def _flaky_stat(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        # `follow_symlinks=False` is pathlib's own internal `is_symlink()` probe;
        # only the real, explicit `stat()` call in `discover()` should fail here.
        if self.name == "gone.py" and follow_symlinks:
            raise OSError("simulated vanish")
        return real_stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", _flaky_stat, raising=True)
    inventory = discover(tmp_path)
    assert inventory.included == ()
    (entry,) = inventory.skipped
    assert entry.reason == "could not stat file"


def test_a_file_that_disappears_before_read_is_reported_not_crashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "gone.py")
    real_read_bytes = Path.read_bytes

    def _flaky_read(self: Path) -> bytes:
        if self.name == "gone.py":
            raise OSError("simulated vanish")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _flaky_read, raising=True)
    inventory = discover(tmp_path)
    assert inventory.included == ()
    (entry,) = inventory.skipped
    assert entry.reason == "could not read file"

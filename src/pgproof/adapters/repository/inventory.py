"""Bounded repository inventory. `docs/TECHNICAL_DESIGN.md` section 5.

Discovery prefers `git ls-files`: it already implements `.gitignore`,
`.git/info/exclude`, and global-excludes semantics correctly, so nothing here
reimplements gitignore glob syntax. A repository with no usable `git` falls
back to a plain walk that only applies pgproof's own fixed exclusions —
`gitignore_respected` on the result says which happened.

Every candidate, from either source, still passes pgproof's own filters:
excluded directories/files, a symlink that resolves outside `root`, a file
over the size cap, and the running total over the total-bytes cap. Nothing
outside `root` is ever opened, per the roadmap's "no path outside the
selected root is read through symlinks."
"""

from __future__ import annotations

import ast
import hashlib
import os
import shutil
import stat
import subprocess
import tomllib
from pathlib import Path
from typing import Final

from pgproof.domain.sources import SourceRef
from pgproof.ports.repository import FrameworkSignals, RepositoryInventory, SkippedEntry

MAX_FILE_BYTES: Final = 2_000_000
MAX_TOTAL_BYTES: Final = 200_000_000

EXCLUDED_DIR_NAMES: Final = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".pgproof",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".eggs",
        "dist",
        "build",
        ".idea",
        ".vscode",
    }
)
EXCLUDED_SUFFIXES: Final = frozenset({".pyc", ".pyo", ".so"})
DOCKER_FILENAMES: Final = frozenset(
    {"Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
)


def app_source_paths(inventory: RepositoryInventory, root: Path) -> list[Path]:
    """`.py` files under a likely app root; `likely_app_roots` names bare packages, so both
    a top-level `<name>/` and a `src/<name>/` layout are matched.

    Shared by `pgproof inspect`'s SQLAlchemy parsing and `pgproof configure`'s
    dynamic question skipping, so both see the same candidate file set.
    """
    app_roots = set(inventory.signals.likely_app_roots)
    paths = []
    for ref in inventory.included:
        parts = Path(ref.path).parts
        if not ref.path.endswith(".py") or not parts:
            continue
        if parts[0] in app_roots or (
            len(parts) > 1 and parts[0] == "src" and parts[1] in app_roots
        ):
            paths.append(root / ref.path)
    return sorted(paths)


def discover(
    root: Path,
    *,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> RepositoryInventory:
    root = root.resolve()
    candidates = _git_candidates(root)
    gitignore_respected = candidates is not None
    if candidates is None:
        candidates = _walk_candidates(root)

    included: list[SourceRef] = []
    skipped: list[SkippedEntry] = []
    imported_roots: set[str] = set()
    total_bytes = 0
    truncated = False

    for path in sorted(candidates):
        relative = path.relative_to(root)
        relative_posix = relative.as_posix()

        reason = _exclusion_reason(relative)
        if reason is not None:
            skipped.append(SkippedEntry(path=relative_posix, reason=reason))
            continue

        if path.is_symlink() and not _resolves_within(path, root):
            skipped.append(
                SkippedEntry(path=relative_posix, reason="symlink escapes the selected root")
            )
            continue

        try:
            file_stat = path.stat()
        except OSError:
            skipped.append(SkippedEntry(path=relative_posix, reason="could not stat file"))
            continue
        if not stat.S_ISREG(file_stat.st_mode):
            continue

        size = file_stat.st_size
        if size > max_file_bytes:
            skipped.append(
                SkippedEntry(
                    path=relative_posix,
                    reason=f"file too large ({size} bytes, limit {max_file_bytes})",
                )
            )
            continue
        if total_bytes + size > max_total_bytes:
            truncated = True
            skipped.append(SkippedEntry(path=relative_posix, reason="total size limit reached"))
            continue

        try:
            data = path.read_bytes()
        except OSError:
            skipped.append(SkippedEntry(path=relative_posix, reason="could not read file"))
            continue

        total_bytes += size
        digest = f"sha256:{hashlib.sha256(data).hexdigest()}"
        included.append(SourceRef(path=relative_posix, content_hash=digest))
        if relative.suffix == ".py":
            imported_roots |= _imported_module_roots(data)

    signals = _detect_frameworks(root, included, imported_roots)
    return RepositoryInventory(
        root=str(root),
        included=tuple(included),
        skipped=tuple(skipped),
        signals=signals,
        total_bytes=total_bytes,
        truncated=truncated,
        gitignore_respected=gitignore_respected,
    )


# --------------------------------------------------------------------------- #
# Candidate discovery
# --------------------------------------------------------------------------- #
def _git_candidates(root: Path) -> list[Path] | None:
    """Files `git` would track or show as untracked-but-not-ignored. `None` if unusable."""
    if shutil.which("git") is None or not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            capture_output=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    names = result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    return [root / name for name in names if name]


def _walk_candidates(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in EXCLUDED_DIR_NAMES]
        found.extend(Path(dirpath) / filename for filename in filenames)
    return found


def _exclusion_reason(relative: Path) -> str | None:
    for part in relative.parts[:-1]:
        if part in EXCLUDED_DIR_NAMES or part.endswith(".egg-info"):
            return f"excluded: {part}/"
    name = relative.name
    if name.startswith(".env"):
        return f"excluded: {name}"
    if relative.suffix in EXCLUDED_SUFFIXES:
        return f"excluded: {relative.suffix} file"
    return None


def _resolves_within(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


# --------------------------------------------------------------------------- #
# Framework/migration/test/Docker detection
# --------------------------------------------------------------------------- #
def _imported_module_roots(source: bytes) -> set[str]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return set()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _package_name(root: Path) -> str | None:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
        return None
    name = document.get("project", {}).get("name")
    return name if isinstance(name, str) else None


def _detect_frameworks(
    root: Path, included: list[SourceRef], imported_roots: set[str]
) -> FrameworkSignals:
    paths = [ref.path for ref in included]
    # `env.py`'s sibling `versions/` is checked on disk, not just from the
    # included set, since `versions/` itself may hold no files pgproof reads.
    alembic_directories = tuple(
        sorted(
            {
                str(Path(path).parent)
                for path in paths
                if Path(path).name == "env.py" and (root / Path(path).parent / "versions").is_dir()
            }
        )
    )
    uses_alembic = bool(alembic_directories) or any(
        Path(path).name == "alembic.ini" for path in paths
    )
    has_tests = any(
        Path(path).name.startswith("test_")
        or Path(path).name.endswith("_test.py")
        or "tests" in Path(path).parts
        for path in paths
    )
    docker_files = tuple(sorted({path for path in paths if Path(path).name in DOCKER_FILENAMES}))
    top_level_packages = {
        Path(path).parts[0]
        for path in paths
        if len(Path(path).parts) == 2 and Path(path).name == "__init__.py"
    }
    src_packages = {
        Path(path).parts[1]
        for path in paths
        if len(Path(path).parts) == 3
        and Path(path).parts[0] == "src"
        and Path(path).name == "__init__.py"
    }
    return FrameworkSignals(
        package_name=_package_name(root),
        uses_alembic=uses_alembic,
        alembic_directories=alembic_directories,
        uses_sqlalchemy="sqlalchemy" in imported_roots,
        uses_sqlmodel="sqlmodel" in imported_roots,
        has_tests=has_tests,
        docker_files=docker_files,
        likely_app_roots=tuple(sorted(top_level_packages | src_packages)),
    )

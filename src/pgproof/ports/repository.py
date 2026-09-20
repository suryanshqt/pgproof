"""The repository inventory port. `docs/TECHNICAL_DESIGN.md` section 5.

One filesystem-based adapter exists (`pgproof.adapters.repository.inventory`).
`docs/ARCHITECTURE.md` section 12: v1 exposes no third-party plugin API; this
Protocol exists so a later adapter (a different VCS, a remote checkout) can
be substituted without changing every caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pgproof.domain.sources import SourceRef


@dataclass(frozen=True)
class SkippedEntry:
    """One path pgproof did not include, and why."""

    path: str
    reason: str


@dataclass(frozen=True)
class FrameworkSignals:
    """What `docs/TECHNICAL_DESIGN.md` section 5 calls identifying "likely app roots" etc.

    Provisional signals only: BE-08 and BE-09 do the actual Alembic/SQLAlchemy
    parsing. This is what tells them where to look.
    """

    package_name: str | None
    uses_alembic: bool
    alembic_directories: tuple[str, ...]
    uses_sqlalchemy: bool
    uses_sqlmodel: bool
    has_tests: bool
    docker_files: tuple[str, ...]
    likely_app_roots: tuple[str, ...]


@dataclass(frozen=True)
class RepositoryInventory:
    root: str
    included: tuple[SourceRef, ...]
    skipped: tuple[SkippedEntry, ...]
    signals: FrameworkSignals
    total_bytes: int
    truncated: bool
    gitignore_respected: bool


class RepositoryInventoryPort(Protocol):
    def __call__(self, root: Path) -> RepositoryInventory: ...

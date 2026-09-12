"""Source references.

`docs/ARCHITECTURE.md` section 6 defines a source identity as repository-relative
path, line and content hash. The content hash is what lets a stale line reference
be detected later, per `docs/TECHNICAL_DESIGN.md` section 5.
"""

from __future__ import annotations

from pgproof.domain.identifiers import MigrationId
from pgproof.domain.primitives import (
    Contract,
    LineNumber,
    NonEmptyText,
    RepositoryPath,
    Sha256,
)


class SourceRef(Contract):
    """A location in the analysed repository."""

    path: RepositoryPath
    line: LineNumber | None = None
    end_line: LineNumber | None = None
    content_hash: Sha256
    symbol: NonEmptyText | None = None

    @property
    def identity(self) -> str:
        """Content-hash-backed identity. Absolute paths cannot appear by construction."""
        line = "" if self.line is None else f"#{self.line}"
        return f"{self.path}{line}@{self.content_hash}"


class MigrationRef(Contract):
    """An Alembic revision, identified by its revision id rather than by file path."""

    revision: MigrationId
    down_revision: MigrationId | None = None
    source: SourceRef | None = None

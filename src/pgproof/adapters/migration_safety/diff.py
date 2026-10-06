"""Branch diff: which Alembic revisions are new on the current branch
relative to a base. Pure — operates on two already-parsed
`RevisionGraphReport`s (`adapters.repository.alembic_static`) plus the
current branch's own `RevisionInfo` list, which already carries each
revision's source location.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pgproof.adapters.repository.alembic_static import RevisionGraphReport, RevisionInfo
from pgproof.domain.sources import SourceRef


@dataclass(frozen=True)
class AddedRevision:
    revision: str
    source: SourceRef


def added_revisions(
    base: RevisionGraphReport,
    current: RevisionGraphReport,
    current_revisions: Sequence[RevisionInfo],
) -> tuple[AddedRevision, ...]:
    """Every revision id present on the current branch but not the base —
    the ones a migration-safety assessment should actually look at, since a
    revision already on both branches was already reviewed wherever the base
    itself was accepted.
    """
    base_ids = frozenset(base.revisions)
    current_ids = frozenset(current.revisions)
    added_ids = current_ids - base_ids
    by_id = {info.revision: info for info in current_revisions}
    return tuple(
        AddedRevision(revision=revision_id, source=by_id[revision_id].source)
        for revision_id in sorted(added_ids)
        if revision_id in by_id
    )

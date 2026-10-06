"""`adapters.migration_safety.diff.added_revisions` against synthetic
`RevisionGraphReport`/`RevisionInfo` fixtures.
"""

from __future__ import annotations

from pgproof.adapters.migration_safety.diff import added_revisions
from pgproof.adapters.repository.alembic_static import RevisionGraphReport, RevisionInfo
from pgproof.domain.sources import SourceRef

_DIGEST = "sha256:" + "a" * 64


def _revision(revision_id: str) -> RevisionInfo:
    return RevisionInfo(
        revision=revision_id,
        down_revisions=(),
        branch_labels=(),
        depends_on=(),
        message=None,
        source=SourceRef(path=f"migrations/versions/{revision_id}.py", content_hash=_DIGEST),
    )


def _graph(*revisions: str) -> RevisionGraphReport:
    return RevisionGraphReport(
        revisions=revisions, roots=(), heads=(), merge_revisions=(), missing_predecessors=()
    )


def test_a_revision_only_on_the_current_branch_is_added() -> None:
    base = _graph("0001")
    current = _graph("0001", "0002")
    result = added_revisions(base, current, [_revision("0001"), _revision("0002")])
    assert [added.revision for added in result] == ["0002"]


def test_a_revision_shared_by_both_branches_is_not_added() -> None:
    base = _graph("0001", "0002")
    current = _graph("0001", "0002")
    result = added_revisions(base, current, [_revision("0001"), _revision("0002")])
    assert result == ()


def test_several_added_revisions_are_sorted_by_id() -> None:
    base = _graph("0001")
    current = _graph("0001", "0003", "0002")
    result = added_revisions(
        base, current, [_revision("0001"), _revision("0002"), _revision("0003")]
    )
    assert [added.revision for added in result] == ["0002", "0003"]


def test_the_added_revisions_source_is_carried_through() -> None:
    base = _graph()
    current = _graph("0001")
    result = added_revisions(base, current, [_revision("0001")])
    assert result[0].source.path == "migrations/versions/0001.py"


def test_an_added_id_with_no_matching_revision_info_is_silently_skipped() -> None:
    """An honest gap, not a guess: if the current branch's own parse somehow
    never produced a `RevisionInfo` for an id the graph claims exists, there
    is no source to report a risk against, so it is omitted rather than
    fabricated.
    """
    base = _graph()
    current = _graph("0001", "0002")
    result = added_revisions(base, current, [_revision("0001")])
    assert [added.revision for added in result] == ["0001"]

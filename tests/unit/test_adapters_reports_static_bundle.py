"""`adapters.reports.static_bundle`: the self-contained Markdown report."""

from __future__ import annotations

from pgproof.adapters.reports.static_bundle import render_static_bundle
from pgproof.domain.decisions import Decision, DecisionKind, DecisionLog
from pgproof.domain.evidence import EvidenceGraph, EvidenceKind, EvidenceRef
from pgproof.domain.recommendations import (
    ChangeKind,
    ProposedChange,
    Recommendation,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationSet,
)
from pgproof.domain.sources import SourceRef

_HASH = "sha256:" + "a" * 64


def _recommendation() -> Recommendation:
    return Recommendation(
        id="IDX-001",
        rule="workload.unindexed_foreign_key",
        rule_version=1,
        title="Index orders.user_id",
        priority=RecommendationPriority.WORTH_EVALUATING,
        category=RecommendationCategory.QUERY,
        statement="orders.user_id is a foreign key with no covering index.",
        affected_objects=("public.orders.user_id",),
        evidence_refs=("ev-1",),
        proposed_change=ProposedChange(kind=ChangeKind.ADD_INDEX, summary="Add a btree index."),
    )


def _evidence() -> EvidenceGraph:
    return EvidenceGraph(
        refs=(
            EvidenceRef(
                id="ev-1",
                kind=EvidenceKind.OBSERVED,
                summary="observed in the migration history",
                source=SourceRef(path="app/models.py", line=42, content_hash=_HASH),
            ),
        )
    )


def test_the_bundle_lists_every_recommendation() -> None:
    bundle = render_static_bundle(
        RecommendationSet(recommendations=(_recommendation(),)), _evidence(), DecisionLog()
    )
    assert "IDX-001" in bundle
    assert "Index orders.user_id" in bundle
    assert "app/models.py:42" in bundle


def test_an_empty_recommendation_set_says_so_rather_than_nothing() -> None:
    bundle = render_static_bundle(RecommendationSet(), EvidenceGraph(), DecisionLog())
    assert "No recommendations." in bundle


def test_the_bundle_includes_recorded_decisions() -> None:
    decision = Decision(
        recommendation="IDX-001",
        kind=DecisionKind.DEFERRED,
        reason="revisit after the next load test",
        decided_at="2026-01-01T00:00:00Z",
        input_manifest_hash=_HASH,
    )
    bundle = render_static_bundle(
        RecommendationSet(recommendations=(_recommendation(),)),
        _evidence(),
        DecisionLog(decisions=(decision,)),
    )
    assert "deferred" in bundle
    assert "revisit after the next load test" in bundle


def test_no_decisions_recorded_is_stated_rather_than_omitted() -> None:
    bundle = render_static_bundle(
        RecommendationSet(recommendations=(_recommendation(),)), _evidence(), DecisionLog()
    )
    assert "No decisions recorded yet." in bundle

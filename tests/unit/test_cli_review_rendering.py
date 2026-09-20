"""Pure rendering/selection helpers in `cli.commands.review`, tested directly."""

from pgproof.application.review import ReviewResult
from pgproof.cli.commands.review import (
    _evidence_sources,
    _priority_label,
    _select_physical_schema,
    render_markdown_report,
    render_review,
)
from pgproof.cli.rendering.capabilities import TerminalCapabilities
from pgproof.domain.evidence import EvidenceGraph, EvidenceKind, EvidenceRef
from pgproof.domain.ir.schema import SchemaIR, SchemaProvenance
from pgproof.domain.migration_plan import MigrationPlan
from pgproof.domain.recommendations import (
    ChangeKind,
    ProposedChange,
    Recommendation,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationSet,
)
from pgproof.domain.scenarios import Scenario, ScenarioKind
from pgproof.domain.sources import SourceRef

_PLAIN = TerminalCapabilities(color=False, unicode=True, interactive=False)


def _recommendation(
    rec_id: str, priority: RecommendationPriority, evidence_refs: tuple[str, ...] = ()
) -> Recommendation:
    return Recommendation(
        id=rec_id,
        rule="a.rule",
        rule_version=1,
        title=f"Title for {rec_id}",
        priority=priority,
        category=RecommendationCategory.SCHEMA,
        statement="Statement.",
        affected_objects=("public.x",),
        evidence_refs=evidence_refs,
        proposed_change=ProposedChange(kind=ChangeKind.ADD_INDEX, summary="x"),
    )


def _result(*recommendations: Recommendation) -> ReviewResult:
    recs = RecommendationSet(recommendations=recommendations)
    scenario = Scenario(
        kind=ScenarioKind.LAUNCH_MINIMAL,
        title="Launch-minimal",
        summary="x",
        recommendations=tuple(r.id for r in recommendations),
    )
    return ReviewResult(recommendations=recs, scenario=scenario, migration_plan=MigrationPlan())


# --------------------------------------------------------------------------- #
# _select_physical_schema
# --------------------------------------------------------------------------- #
def test_no_alembic_schemas_falls_back_to_empty() -> None:
    schema = _select_physical_schema(())
    assert schema.tables == ()
    assert schema.provenance is SchemaProvenance.STATIC_MIGRATION


def test_an_ambiguous_schema_is_skipped_in_favor_of_a_resolved_one() -> None:
    ambiguous = SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION, migration_head=None)
    resolved = SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION, migration_head="abc123")
    assert _select_physical_schema((ambiguous, resolved)) is resolved


def test_all_ambiguous_falls_back_to_empty() -> None:
    ambiguous = SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION, migration_head=None)
    schema = _select_physical_schema((ambiguous,))
    assert schema.migration_head is None
    assert schema.tables == ()


# --------------------------------------------------------------------------- #
# _priority_label
# --------------------------------------------------------------------------- #
def test_priority_label_covers_every_priority() -> None:
    assert _priority_label(RecommendationPriority.REQUIRED_FOR_CORRECTNESS) == "required"
    assert _priority_label(RecommendationPriority.REQUIRED_BY_CONFIRMED_REQUIREMENTS) == "required"
    assert _priority_label(RecommendationPriority.VERIFIED_IMPROVEMENT) == "verified"
    assert _priority_label(RecommendationPriority.WORTH_EVALUATING) == "worth eval."
    assert _priority_label(RecommendationPriority.OPTIONAL_HARDENING) == "optional"


# --------------------------------------------------------------------------- #
# _evidence_sources
# --------------------------------------------------------------------------- #
def test_evidence_sources_formats_path_and_line() -> None:
    evidence = EvidenceGraph(
        refs=(
            EvidenceRef(
                id="ev-1",
                kind=EvidenceKind.OBSERVED,
                summary="x",
                source=SourceRef(path="app/models.py", line=42, content_hash="sha256:" + "a" * 64),
            ),
        )
    )
    rec = _recommendation("AA-001", RecommendationPriority.WORTH_EVALUATING, ("ev-1",))
    assert _evidence_sources(rec, evidence) == ["app/models.py:42"]


def test_evidence_sources_skips_a_ref_with_no_source() -> None:
    evidence = EvidenceGraph(
        refs=(EvidenceRef(id="ev-1", kind=EvidenceKind.OBSERVED, summary="x"),)
    )
    rec = _recommendation("AA-001", RecommendationPriority.WORTH_EVALUATING, ("ev-1",))
    assert _evidence_sources(rec, evidence) == []


def test_evidence_sources_skips_an_unknown_ref_id() -> None:
    rec = _recommendation("AA-001", RecommendationPriority.WORTH_EVALUATING, ("ghost",))
    assert _evidence_sources(rec, EvidenceGraph()) == []


def test_evidence_sources_omits_the_line_when_absent() -> None:
    evidence = EvidenceGraph(
        refs=(
            EvidenceRef(
                id="ev-1",
                kind=EvidenceKind.OBSERVED,
                summary="x",
                source=SourceRef(path="app/models.py", content_hash="sha256:" + "a" * 64),
            ),
        )
    )
    rec = _recommendation("AA-001", RecommendationPriority.WORTH_EVALUATING, ("ev-1",))
    assert _evidence_sources(rec, evidence) == ["app/models.py"]


# --------------------------------------------------------------------------- #
# render_review
# --------------------------------------------------------------------------- #
def test_render_review_truncates_beyond_three_and_says_how_many_are_hidden() -> None:
    recs = [
        _recommendation(f"AA-{i:03d}", RecommendationPriority.REQUIRED_FOR_CORRECTNESS)
        for i in range(1, 6)
    ]
    text = render_review(_result(*recs), EvidenceGraph(), caps=_PLAIN, width=80)
    assert "... and 2 more (--verbose to show all)" in text


def test_render_review_with_no_recommendations_shows_no_headline_result() -> None:
    text = render_review(_result(), EvidenceGraph(), caps=_PLAIN, width=80)
    assert "No headline result" in text


# --------------------------------------------------------------------------- #
# render_markdown_report
# --------------------------------------------------------------------------- #
def test_markdown_report_includes_priority_and_category() -> None:
    rec = _recommendation("AA-001", RecommendationPriority.REQUIRED_FOR_CORRECTNESS)
    markdown = render_markdown_report(_result(rec), EvidenceGraph())
    assert "`required_for_correctness`" in markdown
    assert "`schema`" in markdown

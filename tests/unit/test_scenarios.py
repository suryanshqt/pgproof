"""Scenario builders: unresolved blockers, and the recommendation diff mechanism."""

from pgproof.domain.ir.context import AnswerState, ContextIR
from pgproof.domain.questions import (
    CORE_READ_AFTER_WRITE,
    CORE_RPO_RTO,
    CORE_TABLE_SCALE,
    apply_core_answer,
    apply_table_scale_answer,
)
from pgproof.domain.recommendations import (
    ChangeKind,
    ProposedChange,
    Recommendation,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationSet,
)
from pgproof.domain.scenarios import (
    DeltaKind,
    ScenarioKind,
    build_scenario,
    build_scenario_diff,
    diff_recommendations,
    unresolved_blockers_for,
)


def _recommendation(
    rec_id: str, category: RecommendationCategory = RecommendationCategory.SCHEMA
) -> Recommendation:
    return Recommendation(
        id=rec_id,
        rule="a.rule",
        rule_version=1,
        title="x",
        priority=RecommendationPriority.WORTH_EVALUATING,
        category=category,
        statement="x",
        affected_objects=("public.x",),
        proposed_change=ProposedChange(kind=ChangeKind.ADD_INDEX, summary="x"),
    )


# --------------------------------------------------------------------------- #
# Unresolved blockers per scenario
# --------------------------------------------------------------------------- #
def test_launch_minimal_never_has_unresolved_blockers() -> None:
    assert unresolved_blockers_for(ScenarioKind.LAUNCH_MINIMAL, ContextIR()) == ()


def test_growth_ready_is_blocked_on_table_scale_until_answered() -> None:
    assert unresolved_blockers_for(ScenarioKind.GROWTH_READY, ContextIR()) == (CORE_TABLE_SCALE,)
    context = apply_table_scale_answer(ContextIR(), (), state=AnswerState.ANSWERED)
    assert unresolved_blockers_for(ScenarioKind.GROWTH_READY, context) == ()


def test_availability_ready_is_blocked_on_rpo_rto_and_read_after_write() -> None:
    blockers = unresolved_blockers_for(ScenarioKind.AVAILABILITY_READY, ContextIR())
    assert set(blockers) == {CORE_RPO_RTO, CORE_READ_AFTER_WRITE}


def test_an_unknown_answer_still_counts_as_unresolved() -> None:
    context = apply_core_answer(ContextIR(), CORE_RPO_RTO, state=AnswerState.UNKNOWN)
    blockers = unresolved_blockers_for(ScenarioKind.AVAILABILITY_READY, context)
    assert CORE_RPO_RTO in blockers


# --------------------------------------------------------------------------- #
# build_scenario
# --------------------------------------------------------------------------- #
def test_build_scenario_carries_recommendation_ids_and_blockers() -> None:
    recs = RecommendationSet(recommendations=(_recommendation("AA-001"), _recommendation("BB-002")))
    scenario = build_scenario(ScenarioKind.GROWTH_READY, recs, ContextIR())
    assert scenario.kind is ScenarioKind.GROWTH_READY
    assert scenario.recommendations == ("AA-001", "BB-002")
    assert scenario.unresolved_blockers == (CORE_TABLE_SCALE,)
    assert scenario.requirements_satisfied == ()


# --------------------------------------------------------------------------- #
# diff_recommendations / build_scenario_diff
# --------------------------------------------------------------------------- #
def test_identical_recommendation_sets_produce_no_deltas() -> None:
    recs = RecommendationSet(recommendations=(_recommendation("AA-001"),))
    deltas = diff_recommendations(recs, recs, base_context=ContextIR(), target_context=ContextIR())
    assert deltas == ()


def test_an_added_recommendation_is_reported() -> None:
    base = RecommendationSet()
    target = RecommendationSet(recommendations=(_recommendation("AA-001"),))
    deltas = diff_recommendations(
        base, target, base_context=ContextIR(), target_context=ContextIR()
    )
    assert len(deltas) == 1
    assert deltas[0].kind is DeltaKind.ADDED
    assert deltas[0].recommendation == "AA-001"


def test_a_removed_recommendation_is_reported() -> None:
    base = RecommendationSet(recommendations=(_recommendation("AA-001"),))
    target = RecommendationSet()
    deltas = diff_recommendations(
        base, target, base_context=ContextIR(), target_context=ContextIR()
    )
    assert len(deltas) == 1
    assert deltas[0].kind is DeltaKind.REMOVED


def test_a_recommendation_that_differs_by_id_is_reported_as_changed() -> None:
    base = RecommendationSet(
        recommendations=(_recommendation("AA-001", RecommendationCategory.TENANCY),)
    )
    target = RecommendationSet(
        recommendations=(_recommendation("AA-001", RecommendationCategory.SCHEMA),)
    )
    deltas = diff_recommendations(
        base, target, base_context=ContextIR(), target_context=ContextIR()
    )
    assert len(deltas) == 1
    assert deltas[0].kind is DeltaKind.CHANGED


def test_caused_by_is_set_when_exactly_one_answer_changed() -> None:
    base_context = ContextIR()
    target_context = apply_core_answer(base_context, CORE_TABLE_SCALE, state=AnswerState.UNKNOWN)
    base = RecommendationSet()
    target = RecommendationSet(recommendations=(_recommendation("AA-001"),))
    deltas = diff_recommendations(
        base, target, base_context=base_context, target_context=target_context
    )
    assert deltas[0].caused_by == CORE_TABLE_SCALE


def test_caused_by_is_none_when_more_than_one_answer_changed() -> None:
    base_context = ContextIR()
    target_context = apply_core_answer(base_context, CORE_TABLE_SCALE, state=AnswerState.UNKNOWN)
    target_context = apply_core_answer(target_context, CORE_RPO_RTO, state=AnswerState.UNKNOWN)
    base = RecommendationSet()
    target = RecommendationSet(recommendations=(_recommendation("AA-001"),))
    deltas = diff_recommendations(
        base, target, base_context=base_context, target_context=target_context
    )
    assert deltas[0].caused_by is None


def test_caused_by_is_none_when_no_answer_changed_at_all() -> None:
    base = RecommendationSet()
    target = RecommendationSet(recommendations=(_recommendation("AA-001"),))
    deltas = diff_recommendations(
        base, target, base_context=ContextIR(), target_context=ContextIR()
    )
    assert deltas[0].caused_by is None


def test_build_scenario_diff_wraps_the_deltas_with_both_scenario_kinds() -> None:
    base = RecommendationSet()
    target = RecommendationSet(recommendations=(_recommendation("AA-001"),))
    diff = build_scenario_diff(
        ScenarioKind.LAUNCH_MINIMAL,
        ScenarioKind.GROWTH_READY,
        base,
        target,
        base_context=ContextIR(),
        target_context=ContextIR(),
    )
    assert diff.base is ScenarioKind.LAUNCH_MINIMAL
    assert diff.target is ScenarioKind.GROWTH_READY
    assert len(diff.deltas) == 1

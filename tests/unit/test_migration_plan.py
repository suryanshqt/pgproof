"""Migration plan: staged templates, topological ordering, and cycle detection."""

import pytest

from pgproof.domain.migration_plan import (
    MigrationPlan,
    MigrationPlanCycleError,
    PlanStep,
    build_migration_plan,
    expand_change,
    topological_order,
)
from pgproof.domain.recommendations import (
    ChangeKind,
    ProposedChange,
    Recommendation,
    RecommendationCategory,
    RecommendationPriority,
)
from pgproof.domain.scenarios import ScenarioKind


def _recommendation(rec_id: str, change: ProposedChange | None) -> Recommendation:
    return Recommendation(
        id=rec_id,
        rule="a.rule",
        rule_version=1,
        title="x",
        priority=RecommendationPriority.WORTH_EVALUATING,
        category=RecommendationCategory.SCHEMA,
        statement="x",
        affected_objects=("public.x",),
        proposed_change=change,
        blocking_question="some_question" if change is None else None,
    )


def _step(step_id: str, dependency_ids: tuple[str, ...] = ()) -> PlanStep:
    return PlanStep(
        id=step_id,
        recommendation="AA-001",
        scenario=ScenarioKind.LAUNCH_MINIMAL,
        dependency_ids=dependency_ids,
        schema_action="x",
        deployment_boundary="x",
        rollback_note="x",
        verification_requirement="x",
    )


# --------------------------------------------------------------------------- #
# expand_change: staged templates
# --------------------------------------------------------------------------- #
def test_add_constraint_expands_to_two_dependent_steps() -> None:
    change = ProposedChange(kind=ChangeKind.ADD_CONSTRAINT, summary="Add fk_x_y.")
    steps = expand_change(_recommendation("AA-001", change), ScenarioKind.LAUNCH_MINIMAL)
    assert len(steps) == 2
    assert steps[1].dependency_ids == (steps[0].id,)
    assert "NOT VALID" in steps[0].schema_action
    assert "VALIDATE" in steps[1].schema_action


def test_add_index_expands_to_one_concurrent_step() -> None:
    change = ProposedChange(kind=ChangeKind.ADD_INDEX, summary="Create ix_x_y.")
    steps = expand_change(_recommendation("AA-001", change), ScenarioKind.LAUNCH_MINIMAL)
    assert len(steps) == 1
    assert "CONCURRENTLY" in steps[0].schema_action
    assert steps[0].dependency_ids == ()


def test_an_unstaged_change_kind_gets_one_generic_step() -> None:
    change = ProposedChange(kind=ChangeKind.ALTER_QUERY, summary="Rewrite the query.")
    steps = expand_change(_recommendation("AA-001", change), ScenarioKind.LAUNCH_MINIMAL)
    assert len(steps) == 1
    assert steps[0].schema_action == "Rewrite the query."
    assert "No rollback sketch" in steps[0].rollback_note


def test_a_change_with_its_own_rollback_note_keeps_it() -> None:
    change = ProposedChange(
        kind=ChangeKind.ALTER_COLUMN, summary="x", rollback_note="Revert the column type."
    )
    steps = expand_change(_recommendation("AA-001", change), ScenarioKind.LAUNCH_MINIMAL)
    assert steps[0].rollback_note == "Revert the column type."


def test_a_recommendation_with_no_proposed_change_expands_to_no_steps() -> None:
    steps = expand_change(_recommendation("AA-001", None), ScenarioKind.LAUNCH_MINIMAL)
    assert steps == ()


def test_every_step_records_its_originating_recommendation_and_scenario() -> None:
    change = ProposedChange(kind=ChangeKind.ADD_INDEX, summary="x")
    steps = expand_change(_recommendation("AA-001", change), ScenarioKind.AVAILABILITY_READY)
    assert steps[0].recommendation == "AA-001"
    assert steps[0].scenario is ScenarioKind.AVAILABILITY_READY


# --------------------------------------------------------------------------- #
# build_migration_plan
# --------------------------------------------------------------------------- #
def test_build_migration_plan_expands_every_recommendation() -> None:
    recs = (
        _recommendation("AA-001", ProposedChange(kind=ChangeKind.ADD_INDEX, summary="x")),
        _recommendation("BB-002", ProposedChange(kind=ChangeKind.ADD_CONSTRAINT, summary="y")),
    )
    plan = build_migration_plan(recs, ScenarioKind.LAUNCH_MINIMAL)
    assert len(plan.steps) == 3


def test_a_blocked_recommendation_contributes_no_steps() -> None:
    plan = build_migration_plan((_recommendation("AA-001", None),), ScenarioKind.LAUNCH_MINIMAL)
    assert plan.steps == ()


# --------------------------------------------------------------------------- #
# MigrationPlan referential integrity
# --------------------------------------------------------------------------- #
def test_duplicate_step_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        MigrationPlan(steps=(_step("s1"), _step("s1")))


def test_a_dangling_dependency_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown step ids"):
        MigrationPlan(steps=(_step("s1", ("ghost",)),))


# --------------------------------------------------------------------------- #
# topological_order
# --------------------------------------------------------------------------- #
def test_independent_steps_sort_by_id() -> None:
    plan = MigrationPlan(steps=(_step("b"), _step("a")))
    assert topological_order(plan) == ("a", "b")


def test_dependent_steps_come_after_their_dependency() -> None:
    plan = MigrationPlan(steps=(_step("second", ("first",)), _step("first")))
    assert topological_order(plan) == ("first", "second")


def test_a_two_step_cycle_is_detected() -> None:
    # A cycle cannot be built through MigrationPlan's own validator (each step
    # would dangle until both exist), so the cycle is exercised directly against
    # topological_order's algorithm via two mutually dependent steps.
    plan = MigrationPlan.model_construct(
        steps=(_step("a", ("b",)), _step("b", ("a",))),
    )
    with pytest.raises(MigrationPlanCycleError, match="cycle"):
        topological_order(plan)


def test_an_empty_plan_has_an_empty_order() -> None:
    assert topological_order(MigrationPlan()) == ()

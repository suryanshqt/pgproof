"""Migration plan: staged plan steps expanded from a recommendation's proposed change.

`docs/TECHNICAL_DESIGN.md` section 17: every accepted/proposed change becomes
one or more plan steps carrying dependency ids, a schema action, required
application action, backfill/validation, a deployment boundary, rollback/
reversibility, and a verification requirement. The planner topologically sorts
steps and detects cycles; two named patterns — FK-not-valid/validate and
concurrent index creation — are staged here, since they are the only two
`ChangeKind`s any Ring A rule (`pgproof.rules`) currently produces. The other
three named patterns (nullable-add/backfill/not-null, dual-write/read-switch/
remove, unique-index/constraint) have no producing rule yet to validate a
template against, so they are not speculatively staged.
"""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from pgproof.domain.identifiers import RecommendationId, frame_components
from pgproof.domain.primitives import Contract, NonEmptyText
from pgproof.domain.recommendations import ChangeKind, Recommendation
from pgproof.domain.scenarios import ScenarioKind


class PlanStep(Contract):
    """One ordered unit of a migration plan."""

    id: NonEmptyText
    recommendation: RecommendationId
    scenario: ScenarioKind
    dependency_ids: tuple[NonEmptyText, ...] = ()
    schema_action: NonEmptyText
    application_action: NonEmptyText | None = None
    backfill_or_validation: NonEmptyText | None = None
    deployment_boundary: NonEmptyText
    rollback_note: NonEmptyText
    verification_requirement: NonEmptyText


class MigrationPlan(Contract):
    """A topologically-orderable set of plan steps."""

    steps: tuple[PlanStep, ...] = ()

    @model_validator(mode="after")
    def _validate_references(self) -> Self:
        ids = {step.id for step in self.steps}
        if len(ids) != len(self.steps):
            raise ValueError("plan step ids must be unique")
        dangling = sorted(
            {dep for step in self.steps for dep in step.dependency_ids if dep not in ids}
        )
        if dangling:
            raise ValueError(f"plan steps depend on unknown step ids: {dangling}")
        return self


class MigrationPlanCycleError(ValueError):
    """Raised when plan steps' dependencies form a cycle."""


def topological_order(plan: MigrationPlan) -> tuple[str, ...]:
    """Step ids in dependency order via Kahn's algorithm.

    Ties always break by id, so the order depends only on the plan's content,
    never on `plan.steps`' own construction order.
    """
    indegree = {step.id: 0 for step in plan.steps}
    dependents: dict[str, list[str]] = {step.id: [] for step in plan.steps}
    for step in plan.steps:
        for dep in step.dependency_ids:
            indegree[step.id] += 1
            dependents[dep].append(step.id)
    ready = sorted(step_id for step_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for dependent in dependents[current]:
            indegree[dependent] -= 1
        ready = sorted(
            [
                step_id
                for step_id, degree in indegree.items()
                if degree == 0 and step_id not in order
            ]
        )
    if len(order) != len(plan.steps):
        remaining = sorted(set(indegree) - set(order))
        raise MigrationPlanCycleError(f"migration plan has a dependency cycle among: {remaining}")
    return tuple(order)


def _step_id(recommendation_id: str, index: int) -> str:
    return frame_components(recommendation_id, index)


def expand_change(recommendation: Recommendation, scenario: ScenarioKind) -> tuple[PlanStep, ...]:
    """One recommendation's `proposed_change`, staged into ordered plan steps."""
    change = recommendation.proposed_change
    if change is None:
        return ()
    if change.kind is ChangeKind.ADD_CONSTRAINT:
        not_valid_id = _step_id(recommendation.id, 0)
        validate_id = _step_id(recommendation.id, 1)
        return (
            PlanStep(
                id=not_valid_id,
                recommendation=recommendation.id,
                scenario=scenario,
                schema_action=f"{change.summary} Add it NOT VALID so existing rows "
                "are not checked immediately.",
                deployment_boundary="Safe without a maintenance window: NOT VALID "
                "acquires only a brief metadata lock.",
                rollback_note="Drop the NOT VALID constraint; no data was altered.",
                verification_requirement="Confirm the constraint exists and is marked NOT VALID.",
            ),
            PlanStep(
                id=validate_id,
                recommendation=recommendation.id,
                scenario=scenario,
                dependency_ids=(not_valid_id,),
                schema_action="Run VALIDATE CONSTRAINT to check existing rows without "
                "blocking concurrent writes.",
                backfill_or_validation="Existing rows are validated in place; "
                "a violating row must be corrected first.",
                deployment_boundary="Run once existing data is known to satisfy the constraint.",
                rollback_note="A failed validation leaves the constraint NOT VALID; "
                "nothing to undo.",
                verification_requirement="Confirm the constraint is no longer marked NOT VALID.",
            ),
        )
    if change.kind is ChangeKind.ADD_INDEX:
        step_id = _step_id(recommendation.id, 0)
        return (
            PlanStep(
                id=step_id,
                recommendation=recommendation.id,
                scenario=scenario,
                schema_action=f"{change.summary} Create it CONCURRENTLY to avoid locking writes.",
                deployment_boundary="Safe against a live table: CONCURRENTLY builds "
                "without an exclusive lock.",
                rollback_note="Drop the index; no data was altered.",
                verification_requirement="Confirm the index exists and is not marked INVALID.",
            ),
        )
    step_id = _step_id(recommendation.id, 0)
    return (
        PlanStep(
            id=step_id,
            recommendation=recommendation.id,
            scenario=scenario,
            schema_action=change.summary,
            deployment_boundary="Not yet staged; review before deploying.",
            rollback_note=change.rollback_note
            or "No rollback sketch is available for this change.",
            verification_requirement="Confirm the change was applied as sketched.",
        ),
    )


def build_migration_plan(
    recommendations: tuple[Recommendation, ...], scenario: ScenarioKind
) -> MigrationPlan:
    steps = tuple(
        step
        for recommendation in recommendations
        for step in expand_change(recommendation, scenario)
    )
    return MigrationPlan(steps=steps)

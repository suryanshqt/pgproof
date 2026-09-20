"""Scenarios and scenario differences.

`docs/TECHNICAL_DESIGN.md` section 15 makes scenarios deterministic projections
and requires a diff to name the context answer causing each delta, which is what
`ScenarioDelta.caused_by` carries. `docs/PRODUCT_SPEC.md` section 16 forbids
attaching invented capacity or cost, so no such field exists.
"""

from __future__ import annotations

from pgproof.domain.identifiers import QuestionId, RecommendationId
from pgproof.domain.ir.context import AnswerState, ContextIR
from pgproof.domain.primitives import Contract, NonEmptyText, SnakeCaseEnum
from pgproof.domain.questions import CORE_READ_AFTER_WRITE, CORE_RPO_RTO, CORE_TABLE_SCALE
from pgproof.domain.recommendations import RecommendationSet


class ScenarioKind(SnakeCaseEnum):
    LAUNCH_MINIMAL = "launch_minimal"
    GROWTH_READY = "growth_ready"
    AVAILABILITY_READY = "availability_ready"


class OperationalComplexity(SnakeCaseEnum):
    """Relative only. No throughput, cost or availability number is implied."""

    UNCHANGED = "unchanged"
    SLIGHTLY_HIGHER = "slightly_higher"
    HIGHER = "higher"
    SUBSTANTIALLY_HIGHER = "substantially_higher"


class DeltaKind(SnakeCaseEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class RoutingEligibility(SnakeCaseEnum):
    """Per-operation routing from `docs/TECHNICAL_DESIGN.md` section 25."""

    PRIMARY_REQUIRED = "primary_required"
    REPLICA_ELIGIBLE = "replica_eligible"
    EITHER = "either"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


class Scenario(Contract):
    """One deterministic projection of the target design."""

    kind: ScenarioKind
    title: NonEmptyText
    summary: NonEmptyText
    recommendations: tuple[RecommendationId, ...] = ()
    requirements_satisfied: tuple[NonEmptyText, ...] = ()
    unresolved_blockers: tuple[QuestionId, ...] = ()
    operational_complexity: OperationalComplexity = OperationalComplexity.UNCHANGED


class ScenarioDelta(Contract):
    """One difference between two scenarios, and the answer that caused it."""

    kind: DeltaKind
    recommendation: RecommendationId
    caused_by: QuestionId | None = None
    explanation: NonEmptyText


class ScenarioDiff(Contract):
    """A true diff between two scenarios, not a feature comparison."""

    base: ScenarioKind
    target: ScenarioKind
    deltas: tuple[ScenarioDelta, ...] = ()


class ScenarioSet(Contract):
    """Every projection plus the pairwise diffs the UI renders."""

    scenarios: tuple[Scenario, ...] = ()
    diffs: tuple[ScenarioDiff, ...] = ()


_REQUIRED_QUESTIONS: dict[ScenarioKind, tuple[QuestionId, ...]] = {
    ScenarioKind.LAUNCH_MINIMAL: (),
    ScenarioKind.GROWTH_READY: (CORE_TABLE_SCALE,),
    ScenarioKind.AVAILABILITY_READY: (CORE_RPO_RTO, CORE_READ_AFTER_WRITE),
}

_TITLES: dict[ScenarioKind, str] = {
    ScenarioKind.LAUNCH_MINIMAL: "Launch-minimal",
    ScenarioKind.GROWTH_READY: "Growth-ready",
    ScenarioKind.AVAILABILITY_READY: "Availability-ready",
}

_SUMMARIES: dict[ScenarioKind, str] = {
    ScenarioKind.LAUNCH_MINIMAL: "The simplest design satisfying confirmed launch scale.",
    ScenarioKind.GROWTH_READY: (
        "The design needed for the confirmed 12-month scale and its critical paths."
    ),
    ScenarioKind.AVAILABILITY_READY: (
        "Adds the confirmed recovery targets and consistency requirements."
    ),
}


def unresolved_blockers_for(kind: ScenarioKind, context: ContextIR) -> tuple[QuestionId, ...]:
    """Which of this scenario's required questions are not yet answered.

    `docs/TECHNICAL_DESIGN.md` section 15: growth-ready needs the 12-month scale;
    availability-ready additionally needs RPO/RTO and read-after-write flows.
    Launch-minimal needs neither, since it only ever targets confirmed present
    scale, which every core interview already asks unconditionally.
    """
    answered = {
        answer.question for answer in context.answers if answer.state is AnswerState.ANSWERED
    }
    return tuple(question for question in _REQUIRED_QUESTIONS[kind] if question not in answered)


def build_scenario(
    kind: ScenarioKind, recommendations: RecommendationSet, context: ContextIR
) -> Scenario:
    """A scenario from one rule run's output. `requirements_satisfied` stays empty:
    naming a requirement as satisfied is a claim this module has no evidence for
    yet, per `docs/PRODUCT_SPEC.md` section 16's ban on invented capacity/cost.
    """
    return Scenario(
        kind=kind,
        title=_TITLES[kind],
        summary=_SUMMARIES[kind],
        recommendations=tuple(item.id for item in recommendations.recommendations),
        unresolved_blockers=unresolved_blockers_for(kind, context),
    )


def _sole_changed_answer(base_context: ContextIR, target_context: ContextIR) -> QuestionId | None:
    """The one answer that differs between two contexts, if there is exactly one.

    More than one changed answer makes attributing a delta to a single cause a
    guess, so `None` is returned instead — `ScenarioDelta.caused_by` is optional
    for exactly this reason.
    """
    base_answers = {
        answer.question: (answer.state, answer.value) for answer in base_context.answers
    }
    target_answers = {
        answer.question: (answer.state, answer.value) for answer in target_context.answers
    }
    changed = {
        question
        for question in base_answers.keys() | target_answers.keys()
        if base_answers.get(question) != target_answers.get(question)
    }
    return next(iter(changed)) if len(changed) == 1 else None


def diff_recommendations(
    base: RecommendationSet,
    target: RecommendationSet,
    *,
    base_context: ContextIR,
    target_context: ContextIR,
) -> tuple[ScenarioDelta, ...]:
    """Added/removed/changed recommendations between two rule runs, deterministic
    and sorted by recommendation id within each `DeltaKind`.
    """
    caused_by = _sole_changed_answer(base_context, target_context)
    base_by_id = {item.id: item for item in base.recommendations}
    target_by_id = {item.id: item for item in target.recommendations}
    deltas = [
        ScenarioDelta(
            kind=DeltaKind.ADDED,
            recommendation=recommendation_id,
            caused_by=caused_by,
            explanation=f"{recommendation_id} is newly reported.",
        )
        for recommendation_id in sorted(set(target_by_id) - set(base_by_id))
    ]
    deltas += [
        ScenarioDelta(
            kind=DeltaKind.REMOVED,
            recommendation=recommendation_id,
            caused_by=caused_by,
            explanation=f"{recommendation_id} is no longer reported.",
        )
        for recommendation_id in sorted(set(base_by_id) - set(target_by_id))
    ]
    deltas += [
        ScenarioDelta(
            kind=DeltaKind.CHANGED,
            recommendation=recommendation_id,
            caused_by=caused_by,
            explanation=f"{recommendation_id} is reported differently.",
        )
        for recommendation_id in sorted(set(base_by_id) & set(target_by_id))
        if base_by_id[recommendation_id] != target_by_id[recommendation_id]
    ]
    return tuple(deltas)


def build_scenario_diff(
    base_kind: ScenarioKind,
    target_kind: ScenarioKind,
    base: RecommendationSet,
    target: RecommendationSet,
    *,
    base_context: ContextIR,
    target_context: ContextIR,
) -> ScenarioDiff:
    return ScenarioDiff(
        base=base_kind,
        target=target_kind,
        deltas=diff_recommendations(
            base, target, base_context=base_context, target_context=target_context
        ),
    )

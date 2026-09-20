"""Scenarios and scenario differences.

`docs/TECHNICAL_DESIGN.md` section 15 makes scenarios deterministic projections
and requires a diff to name the context answer causing each delta, which is what
`ScenarioDelta.caused_by` carries. `docs/PRODUCT_SPEC.md` section 16 forbids
attaching invented capacity or cost, so no such field exists.
"""

from __future__ import annotations

from pgproof.domain.identifiers import QuestionId, RecommendationId
from pgproof.domain.primitives import Contract, NonEmptyText, SnakeCaseEnum


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

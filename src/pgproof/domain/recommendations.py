"""Recommendations.

`docs/PRODUCT_SPEC.md` section 7 requires every recommendation to expose its
evidence, assumptions, trade-offs, invalidating context and verification state,
and forbids presenting synthetic latency as expected production latency. Both are
structural here: there is no field in which a production prediction could be
written, and a measured saving carries the fixture scale it was measured at.
"""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from pgproof.domain.identifiers import (
    ProofId,
    QuestionId,
    RecommendationId,
    RuleId,
    canonical_recommendation_identity,
)
from pgproof.domain.primitives import (
    Contract,
    Microseconds,
    NonEmptyText,
    SnakeCaseEnum,
)
from pgproof.domain.questions import MaterialQuestion


class RecommendationPriority(SnakeCaseEnum):
    """The five groups in `docs/PRODUCT_SPEC.md` section 12. No numeric score exists."""

    REQUIRED_FOR_CORRECTNESS = "required_for_correctness"
    REQUIRED_BY_CONFIRMED_REQUIREMENTS = "required_by_confirmed_requirements"
    VERIFIED_IMPROVEMENT = "verified_improvement"
    WORTH_EVALUATING = "worth_evaluating"
    OPTIONAL_HARDENING = "optional_hardening"


class RecommendationCategory(SnakeCaseEnum):
    SCHEMA = "schema"
    QUERY = "query"
    TENANCY = "tenancy"
    PROCEDURE = "procedure"
    TOPOLOGY = "topology"
    MIGRATION = "migration"


class VerificationState(SnakeCaseEnum):
    NOT_ELIGIBLE = "not_eligible"
    ELIGIBLE = "eligible"
    BLOCKED = "blocked"
    QUEUED = "queued"
    VERIFIED_IN_FIXTURE = "verified_in_fixture"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED = "unsupported"


class ChangeKind(SnakeCaseEnum):
    ADD_INDEX = "add_index"
    ADD_CONSTRAINT = "add_constraint"
    ALTER_COLUMN = "alter_column"
    ALTER_QUERY = "alter_query"
    ALTER_LOADING_STRATEGY = "alter_loading_strategy"
    ADD_PROCEDURE = "add_procedure"
    CHANGE_TOPOLOGY = "change_topology"
    NO_CHANGE = "no_change"


class Assumption(Contract):
    """A named assumption, with what would falsify it."""

    statement: NonEmptyText
    falsified_by: NonEmptyText | None = None


class TradeOff(Contract):
    """A cost accepted in exchange for the benefit."""

    statement: NonEmptyText
    affects: NonEmptyText | None = None


class InvalidatingContext(Contract):
    """The answer change that would retire this recommendation."""

    question: QuestionId
    condition: NonEmptyText


class Alternative(Contract):
    """A option not recommended, and what evidence would select it."""

    summary: NonEmptyText
    selected_by: NonEmptyText | None = None
    reversibility: NonEmptyText | None = None


class ProposedChange(Contract):
    """A sketch, never an applied edit.

    `docs/PRODUCT_SPEC.md` section 17 forbids automatic repository mutation, so
    this carries text for the developer to apply rather than a patch to run.
    """

    kind: ChangeKind
    summary: NonEmptyText
    sql_sketch: NonEmptyText | None = None
    migration_sketch: NonEmptyText | None = None
    application_sketch: NonEmptyText | None = None
    rollback_note: NonEmptyText | None = None


class FixtureMeasurement(Contract):
    """A measured effect, inseparable from the fixture it was measured in.

    There is deliberately no field for expected production behaviour. `docs/
    PRODUCT_SPEC.md` section 7 forbids presenting synthetic latency as a
    production forecast, and `fixture_scale` is required so the boundary cannot be
    dropped when the number is quoted.
    """

    fixture_scale: NonEmptyText
    control_median_us: Microseconds
    treatment_median_us: Microseconds
    absolute_saving_us: int
    proof: ProofId | None = None


class Recommendation(Contract):
    """One decision, with the whole evidence trail attached."""

    id: RecommendationId
    rule: RuleId
    rule_version: int
    title: NonEmptyText
    priority: RecommendationPriority
    category: RecommendationCategory
    statement: NonEmptyText
    affected_objects: tuple[str, ...]
    evidence_refs: tuple[NonEmptyText, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    trade_offs: tuple[TradeOff, ...] = ()
    invalidating_context: tuple[InvalidatingContext, ...] = ()
    alternatives: tuple[Alternative, ...] = ()
    verification_state: VerificationState = VerificationState.NOT_ELIGIBLE
    measurement: FixtureMeasurement | None = None
    proposed_change: ProposedChange | None = None
    blocking_question: QuestionId | None = None

    @property
    def canonical_identity(self) -> str:
        """Rule plus affected objects. Rewording the statement does not move it."""
        return canonical_recommendation_identity(self.rule, self.affected_objects)

    @model_validator(mode="after")
    def _validate_contract(self) -> Self:
        if not self.affected_objects:
            raise ValueError("a recommendation must name at least one affected object")
        if self.proposed_change is None and self.blocking_question is None:
            raise ValueError("a recommendation must carry a proposed change or a blocking question")
        verified = self.verification_state is VerificationState.VERIFIED_IN_FIXTURE
        if verified and self.measurement is None:
            raise ValueError("verified_in_fixture requires a fixture measurement to cite")
        if self.measurement is not None and not verified:
            raise ValueError("a fixture measurement may only accompany verified_in_fixture")
        if self.priority is RecommendationPriority.VERIFIED_IMPROVEMENT and not verified:
            raise ValueError("verified_improvement requires verification_state verified_in_fixture")
        return self


class RecommendationSet(Contract):
    """Rule output: the decisions and the questions blocking them."""

    recommendations: tuple[Recommendation, ...] = ()
    questions: tuple[MaterialQuestion, ...] = ()
    unsupported_reasons: tuple[NonEmptyText, ...] = ()

"""Proof summaries.

This is the summary a report and the UI read. The portable bundle on disk is
BE-30's contract; nothing here writes or reads a file.

`docs/TECHNICAL_DESIGN.md` section 20 forbids a p95 from seven samples, and
`docs/PRODUCT_SPEC.md` section 7 forbids presenting a fixture measurement as
production behaviour. Both are structural: there is no percentile field, and
every measured arm is bound to a declared fixture scale.
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from pgproof.domain.identifiers import ProofId, QueryId, RecommendationId
from pgproof.domain.primitives import (
    Contract,
    DecimalString,
    Microseconds,
    NonEmptyText,
    Sha256,
    SnakeCaseEnum,
)


class ProofVerdict(SnakeCaseEnum):
    VERIFIED_IN_FIXTURE = "verified_in_fixture"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED = "unsupported"


class ExperimentArm(SnakeCaseEnum):
    CONTROL_A1 = "control_a1"
    TREATMENT_B = "treatment_b"
    DRIFT_CONTROL_A2 = "drift_control_a2"


class TreatmentKind(SnakeCaseEnum):
    SINGLE_COLUMN_BTREE = "single_column_btree"
    COMPOSITE_BTREE = "composite_btree"
    EAGER_LOADING = "eager_loading"
    SET_BASED_QUERY = "set_based_query"
    STORED_PROCEDURE = "stored_procedure"


class ArmMeasurement(Contract):
    """One arm's statistics. Raw samples live in the proof bundle, not here."""

    arm: ExperimentArm
    samples: int = Field(ge=1)
    warmups_discarded: int = Field(ge=0)
    median_us: Microseconds
    q1_us: Microseconds
    q3_us: Microseconds
    iqr_fraction: DecimalString
    plan_shape: NonEmptyText | None = None


class ProofSummary(Contract):
    """A measured treatment, inseparable from its fixture."""

    id: ProofId
    recommendation: RecommendationId
    query: QueryId | None = None
    treatment: TreatmentKind
    verdict: ProofVerdict
    # The declared fixture the numbers belong to. Required, so a measured saving
    # can never be quoted without its boundary.
    fixture_scale: NonEmptyText
    dataset_seed: NonEmptyText
    postgres_version: NonEmptyText
    input_manifest_hash: Sha256
    arms: tuple[ArmMeasurement, ...] = ()
    absolute_saving_us: int | None = None
    drift_fraction: DecimalString | None = None
    stability_note: NonEmptyText | None = None
    rejection_reason: NonEmptyText | None = None

    @model_validator(mode="after")
    def _validate_contract(self) -> Self:
        if self.verdict is ProofVerdict.VERIFIED_IN_FIXTURE:
            arms = {arm.arm for arm in self.arms}
            required = {
                ExperimentArm.CONTROL_A1,
                ExperimentArm.TREATMENT_B,
                ExperimentArm.DRIFT_CONTROL_A2,
            }
            missing = sorted(arm.value for arm in required - arms)
            if missing:
                raise ValueError(
                    f"verified_in_fixture requires control, treatment and drift arms; "
                    f"missing {missing}"
                )
            if self.absolute_saving_us is None:
                raise ValueError("verified_in_fixture requires an absolute saving")
        if self.verdict is ProofVerdict.REJECTED and self.rejection_reason is None:
            raise ValueError("a rejected candidate must state why")
        if self.verdict is ProofVerdict.INCONCLUSIVE and self.stability_note is None:
            raise ValueError("an inconclusive result must state its instability")
        if not self.id.startswith(f"{self.recommendation}@"):
            raise ValueError("proof id must be its recommendation plus the input-manifest hash")
        return self


class ProofSummarySet(Contract):
    """Every candidate, including the rejected ones.

    `docs/PRODUCT_SPEC.md` section 5 treats rejected experiments as evidence of
    rigour, so they are retained rather than filtered out.
    """

    proofs: tuple[ProofSummary, ...] = ()

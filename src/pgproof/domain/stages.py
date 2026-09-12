"""Stage summaries.

The state machine is `docs/ARCHITECTURE.md` section 14. `partial` exists so a
useful-but-bounded result is never presented as `complete`, and a stage that
`failed` must not be treated as valid by any downstream consumer.

This module describes a stage; it does not run one, and it writes nothing.
Run manifests, NDJSON events and the artifact store belong to BE-04.
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from pgproof.domain.primitives import (
    Contract,
    Microseconds,
    NonEmptyText,
    Rfc3339Utc,
    Sha256,
    SnakeCaseEnum,
)


class StageName(SnakeCaseEnum):
    """The visible, cacheable stages listed in `ideation/03-product-experience.md`."""

    REPOSITORY_INVENTORY = "repository_inventory"
    SCHEMA_RECONSTRUCTION = "schema_reconstruction"
    CONTEXT_RESOLUTION = "context_resolution"
    MIGRATION_SANDBOX = "migration_sandbox"
    QUERY_CAPTURE = "query_capture"
    DATASET_BUILD = "dataset_build"
    CANDIDATE_SCREENING = "candidate_screening"
    PHYSICAL_VERIFICATION = "physical_verification"
    REPORT_GENERATION = "report_generation"


class StageStatus(SnakeCaseEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageSummary(Contract):
    """The outcome of one stage.

    Durations are integer microseconds per `docs/TECHNICAL_DESIGN.md` section 4
    and are formatted at presentation, not here.
    """

    stage: StageName
    status: StageStatus
    started_at: Rfc3339Utc | None = None
    ended_at: Rfc3339Utc | None = None
    duration_us: Microseconds | None = None
    cache_key: Sha256 | None = None
    input_hashes: dict[str, Sha256] = Field(default_factory=dict)
    warnings: tuple[NonEmptyText, ...] = ()
    failure_reason: NonEmptyText | None = None
    boundary_note: NonEmptyText | None = None

    @model_validator(mode="after")
    def _validate_contract(self) -> Self:
        if self.status is StageStatus.FAILED and self.failure_reason is None:
            raise ValueError("a failed stage must state its failure reason")
        if self.status is StageStatus.PARTIAL and self.boundary_note is None:
            raise ValueError("a partial stage must state its boundary explicitly")
        return self


class StageSet(Contract):
    """Every stage of one run, in declared order."""

    stages: tuple[StageSummary, ...] = ()

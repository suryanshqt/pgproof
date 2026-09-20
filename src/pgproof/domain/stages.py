"""Stage summaries and the legal transitions between their statuses.

The state machine is `docs/ARCHITECTURE.md` section 14. `partial` exists so a
useful-but-bounded result is never presented as `complete`, and a stage that
`failed` must not be treated as valid by any downstream consumer.

This module describes a stage and validates a transition between two statuses;
it does not run one and it writes nothing. The run orchestrator, NDJSON events
and the artifact store are `pgproof.store`.
"""

from __future__ import annotations

from typing import Final, Self

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


# `docs/ARCHITECTURE.md` section 14: pending -> running -> {complete, partial,
# failed, cancelled}. Every terminal state is final; a stage that already
# finished cannot be reopened by a later event in the same run.
ALLOWED_STAGE_TRANSITIONS: Final[dict[StageStatus, frozenset[StageStatus]]] = {
    StageStatus.PENDING: frozenset({StageStatus.RUNNING, StageStatus.CANCELLED}),
    StageStatus.RUNNING: frozenset(
        {StageStatus.COMPLETE, StageStatus.PARTIAL, StageStatus.FAILED, StageStatus.CANCELLED}
    ),
    StageStatus.COMPLETE: frozenset(),
    StageStatus.PARTIAL: frozenset(),
    StageStatus.FAILED: frozenset(),
    StageStatus.CANCELLED: frozenset(),
}


def validate_stage_transition(current: StageStatus, target: StageStatus) -> None:
    """Raise if moving a stage from `current` to `target` is not a legal edge."""
    if target not in ALLOWED_STAGE_TRANSITIONS[current]:
        raise ValueError(f"invalid stage transition: {current.value} -> {target.value}")

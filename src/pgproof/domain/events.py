"""Run event stream records, one per NDJSON line in `runs/<run-id>/events.ndjson`.

Distinct from `StageSummary` (`stages.py`): a `StageSummary` is the terminal
outcome of a stage; a `StageEvent` is one point in the live transition stream,
including the `stage_started` event that has no terminal outcome yet. This is
what `docs/ARCHITECTURE.md` section 9 streams to the browser as server-sent
events once BE-06 wires the API.

Not part of the generated JSON Schema / TypeScript contract set: it is a
backend-internal record today, so it carries no `ArtifactType` and is not
registered in `pgproof.domain.registry`.
"""

from __future__ import annotations

from pgproof.domain.primitives import Contract, NonEmptyText, Rfc3339Utc, RunId, SnakeCaseEnum
from pgproof.domain.stages import StageName


class StageEventKind(SnakeCaseEnum):
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    STAGE_PARTIAL = "stage_partial"
    STAGE_FAILED = "stage_failed"
    STAGE_CANCELLED = "stage_cancelled"


class StageEvent(Contract):
    run_id: RunId
    stage: StageName
    kind: StageEventKind
    at: Rfc3339Utc
    detail: NonEmptyText | None = None

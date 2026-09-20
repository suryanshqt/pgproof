"""The run/stage state machine, the NDJSON event stream, and the run manifest.

`docs/ARCHITECTURE.md` section 31: a running stage's manifest must be absent or
explicitly marked cancelled on disk, never left `running`. `result.json` and
`manifest.json` are therefore written only once, by `finish()`; each stage
transition before that is visible only as an event line in `events.ndjson`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from pgproof.domain.envelope import ArtifactType, Envelope
from pgproof.domain.events import StageEvent, StageEventKind
from pgproof.domain.manifest import ManifestEntry, RunManifest
from pgproof.domain.primitives import NonEmptyText, Rfc3339Utc, Sha256
from pgproof.domain.registry import envelope_model_for
from pgproof.domain.stages import (
    StageName,
    StageSet,
    StageStatus,
    StageSummary,
    validate_stage_transition,
)
from pgproof.ports.clock import Clock, SystemClock
from pgproof.store.artifacts import write_artifact
from pgproof.store.atomic import append_line_durable
from pgproof.store.manifest import write_run_manifest
from pgproof.store.paths import ProjectLayout

_EVENT_KIND_FOR_STATUS: Final[dict[StageStatus, StageEventKind]] = {
    StageStatus.RUNNING: StageEventKind.STAGE_STARTED,
    StageStatus.COMPLETE: StageEventKind.STAGE_COMPLETED,
    StageStatus.PARTIAL: StageEventKind.STAGE_PARTIAL,
    StageStatus.FAILED: StageEventKind.STAGE_FAILED,
    StageStatus.CANCELLED: StageEventKind.STAGE_CANCELLED,
}


def format_rfc3339(moment: dt.datetime) -> Rfc3339Utc:
    return moment.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


class RunSession:
    """Drives one run: stage transitions, its event stream, and its manifest.

    Not thread-safe and not re-entrant across processes; one run is one CLI
    invocation, per `docs/ARCHITECTURE.md` section 3.
    """

    def __init__(
        self,
        layout: ProjectLayout,
        run_id: str,
        tool_version: str,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._layout = layout
        self._run_id = run_id
        self._tool_version = tool_version
        self._clock = clock or SystemClock()
        self._stages: dict[StageName, StageSummary] = {}
        self._manifest_entries: list[ManifestEntry] = []
        self._events_path = layout.run_events_path(run_id)

    @property
    def run_id(self) -> str:
        return self._run_id

    def start_stage(self, stage: StageName) -> None:
        self._transition(stage, StageStatus.RUNNING)

    def complete_stage(
        self,
        stage: StageName,
        *,
        cache_key: Sha256 | None = None,
        input_hashes: Mapping[str, Sha256] | None = None,
        warnings: tuple[NonEmptyText, ...] = (),
    ) -> None:
        self._transition(
            stage,
            StageStatus.COMPLETE,
            cache_key=cache_key,
            input_hashes=input_hashes,
            warnings=warnings,
        )

    def partial_stage(
        self,
        stage: StageName,
        *,
        boundary_note: NonEmptyText,
        cache_key: Sha256 | None = None,
        input_hashes: Mapping[str, Sha256] | None = None,
        warnings: tuple[NonEmptyText, ...] = (),
    ) -> None:
        self._transition(
            stage,
            StageStatus.PARTIAL,
            boundary_note=boundary_note,
            cache_key=cache_key,
            input_hashes=input_hashes,
            warnings=warnings,
        )

    def fail_stage(
        self,
        stage: StageName,
        *,
        failure_reason: NonEmptyText,
        cache_key: Sha256 | None = None,
        input_hashes: Mapping[str, Sha256] | None = None,
    ) -> None:
        self._transition(
            stage,
            StageStatus.FAILED,
            failure_reason=failure_reason,
            cache_key=cache_key,
            input_hashes=input_hashes,
        )

    def cancel_stage(self, stage: StageName) -> None:
        self._transition(stage, StageStatus.CANCELLED)

    def record_artifact(
        self, artifact_type: ArtifactType, path: Path, envelope: Envelope[Any]
    ) -> None:
        """Write one artifact atomically and record it in this run's manifest."""
        digest = write_artifact(path, envelope)
        relative_path = str(path.relative_to(self._layout.pgproof_dir))
        self._manifest_entries.append(
            ManifestEntry(
                artifact_type=artifact_type,
                path=relative_path,
                content_hash=digest,
                schema_version=envelope.schema_version,
            )
        )

    def finish(self) -> tuple[StageSummary, ...]:
        """Write `result.json` then `manifest.json`, in that order, and return the stage summaries.

        `manifest.json` is written last, per `docs/ARCHITECTURE.md` section 7: its
        presence is what marks this run's artifact set complete and verifiable.
        """
        stage_summaries = tuple(self._stages.values())
        stage_set = StageSet(stages=stage_summaries)
        now = format_rfc3339(self._clock.now())
        envelope_cls = envelope_model_for(ArtifactType.STAGES)
        envelope = envelope_cls(
            tool_version=self._tool_version,
            artifact_type=ArtifactType.STAGES,
            created_at=now,
            run_id=self._run_id,
            data=stage_set,
        )
        result_path = self._layout.run_result_path(self._run_id)
        self.record_artifact(ArtifactType.STAGES, result_path, envelope)
        manifest = RunManifest(
            run_id=self._run_id,
            tool_version=self._tool_version,
            created_at=now,
            entries=tuple(self._manifest_entries),
        )
        write_run_manifest(self._layout.run_manifest_path(self._run_id), manifest)
        return stage_summaries

    def _transition(
        self,
        stage: StageName,
        status: StageStatus,
        *,
        cache_key: Sha256 | None = None,
        input_hashes: Mapping[str, Sha256] | None = None,
        warnings: tuple[NonEmptyText, ...] = (),
        failure_reason: NonEmptyText | None = None,
        boundary_note: NonEmptyText | None = None,
    ) -> None:
        current = self._stages.get(stage)
        current_status = current.status if current is not None else StageStatus.PENDING
        validate_stage_transition(current_status, status)
        now = self._clock.now()
        started_at = current.started_at if current is not None else format_rfc3339(now)
        ended_at = None if status is StageStatus.RUNNING else format_rfc3339(now)
        duration_us = None
        if ended_at is not None and started_at is not None:
            duration_us = (now - _parse_rfc3339(started_at)) // dt.timedelta(microseconds=1)
        self._stages[stage] = StageSummary(
            stage=stage,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            duration_us=duration_us,
            cache_key=cache_key,
            input_hashes=dict(input_hashes or {}),
            warnings=warnings,
            failure_reason=failure_reason,
            boundary_note=boundary_note,
        )
        event = StageEvent(
            run_id=self._run_id,
            stage=stage,
            kind=_EVENT_KIND_FOR_STATUS[status],
            at=format_rfc3339(now),
            detail=failure_reason or boundary_note,
        )
        append_line_durable(self._events_path, event.canonical_json())


def _parse_rfc3339(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.UTC)

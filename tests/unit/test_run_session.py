"""End-to-end run/stage lifecycle: transitions, the NDJSON event stream, and finish()."""

import datetime as dt
import re
from pathlib import Path

import pytest

from pgproof.domain.envelope import ArtifactType
from pgproof.domain.events import StageEvent, StageEventKind
from pgproof.domain.primitives import RUN_ID_PATTERN
from pgproof.domain.registry import envelope_model_for
from pgproof.domain.stages import StageName, StageStatus
from pgproof.ports.clock import SystemClock
from pgproof.store.artifacts import read_artifact
from pgproof.store.manifest import read_run_manifest, verify_manifest
from pgproof.store.paths import ProjectLayout
from pgproof.store.run import RunSession
from pgproof.store.run_id import new_run_id

RUN = "01JQ0X3M4N5P6R7S8T9V0W1X2Y"


class FakeClock:
    def __init__(self, start: dt.datetime) -> None:
        self._current = start

    def now(self) -> dt.datetime:
        moment = self._current
        self._current += dt.timedelta(seconds=1)
        return moment


def _session(tmp_path: Path) -> RunSession:
    layout = ProjectLayout(tmp_path)
    layout.ensure_base_layout()
    clock = FakeClock(dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    return RunSession(layout, RUN, "0.1.0", clock=clock)


def _events(tmp_path: Path) -> list[StageEvent]:
    layout = ProjectLayout(tmp_path)
    lines = layout.run_events_path(RUN).read_text(encoding="utf-8").splitlines()
    return [StageEvent.model_validate_json(line) for line in lines]


def test_a_completed_stage_records_duration_and_emits_two_events(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.start_stage(StageName.REPOSITORY_INVENTORY)
    session.complete_stage(StageName.REPOSITORY_INVENTORY)

    events = _events(tmp_path)
    assert [event.kind for event in events] == [
        StageEventKind.STAGE_STARTED,
        StageEventKind.STAGE_COMPLETED,
    ]

    (summary,) = session.finish()
    assert summary.status is StageStatus.COMPLETE
    assert summary.started_at is not None
    assert summary.ended_at is not None
    assert summary.duration_us == 1_000_000


def test_a_partial_stage_requires_and_records_its_boundary(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.start_stage(StageName.QUERY_CAPTURE)
    session.partial_stage(StageName.QUERY_CAPTURE, boundary_note="two of five tests failed")
    (summary,) = session.finish()
    assert summary.status is StageStatus.PARTIAL
    assert summary.boundary_note == "two of five tests failed"


def test_a_failed_stage_records_its_reason(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.start_stage(StageName.MIGRATION_SANDBOX)
    session.fail_stage(StageName.MIGRATION_SANDBOX, failure_reason="alembic upgrade raised")
    (summary,) = session.finish()
    assert summary.status is StageStatus.FAILED
    assert summary.failure_reason == "alembic upgrade raised"


def test_cancelling_a_stage_that_never_started_needs_no_prior_event(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.cancel_stage(StageName.DATASET_BUILD)
    (summary,) = session.finish()
    assert summary.status is StageStatus.CANCELLED
    assert summary.started_at is not None


def test_a_terminal_stage_cannot_be_reopened(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.start_stage(StageName.REPOSITORY_INVENTORY)
    session.complete_stage(StageName.REPOSITORY_INVENTORY)
    with pytest.raises(ValueError, match="invalid stage transition"):
        session.complete_stage(StageName.REPOSITORY_INVENTORY)


def test_completing_a_stage_that_never_started_is_rejected(tmp_path: Path) -> None:
    session = _session(tmp_path)
    with pytest.raises(ValueError, match="invalid stage transition"):
        session.complete_stage(StageName.REPOSITORY_INVENTORY)


def test_finish_writes_result_json_then_a_verifiable_manifest(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.start_stage(StageName.REPOSITORY_INVENTORY)
    session.complete_stage(StageName.REPOSITORY_INVENTORY)
    session.finish()

    layout = ProjectLayout(tmp_path)
    result = read_artifact(layout.run_result_path(RUN), ArtifactType.STAGES)
    assert len(result.data.stages) == 1
    assert result.data.stages[0].stage is StageName.REPOSITORY_INVENTORY

    manifest = read_run_manifest(layout.run_manifest_path(RUN))
    assert len(manifest.entries) == 1
    assert manifest.entries[0].path == f"runs/{RUN}/result.json"
    assert verify_manifest(layout.pgproof_dir, manifest) == ()


def test_record_artifact_places_the_analysis_document_and_hashes_it(tmp_path: Path) -> None:
    session = _session(tmp_path)
    layout = ProjectLayout(tmp_path)
    envelope_cls = envelope_model_for(ArtifactType.SCHEMA)
    envelope = envelope_cls(
        tool_version="0.1.0",
        artifact_type=ArtifactType.SCHEMA,
        created_at="2026-01-01T00:00:00Z",
        run_id=RUN,
        data={"provenance": "physical_catalog"},
    )
    session.record_artifact(
        ArtifactType.SCHEMA, layout.analysis_path(ArtifactType.SCHEMA), envelope
    )
    session.finish()

    manifest = read_run_manifest(layout.run_manifest_path(RUN))
    paths = {entry.path for entry in manifest.entries}
    assert "analysis/schema.json" in paths
    assert verify_manifest(layout.pgproof_dir, manifest) == ()


def test_a_session_defaults_to_the_system_clock_and_exposes_its_run_id(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)
    layout.ensure_base_layout()
    session = RunSession(layout, RUN, "0.1.0")
    assert session.run_id == RUN
    session.cancel_stage(StageName.DATASET_BUILD)
    (summary,) = session.finish()
    assert summary.status is StageStatus.CANCELLED


def test_system_clock_reports_a_timezone_aware_utc_instant() -> None:
    moment = SystemClock().now()
    assert moment.tzinfo is dt.UTC


# --------------------------------------------------------------------------- #
# Run id generation
# --------------------------------------------------------------------------- #
def test_new_run_id_matches_the_run_id_pattern() -> None:
    pattern = re.compile(RUN_ID_PATTERN)
    for _ in range(50):
        assert pattern.match(new_run_id())


def test_new_run_ids_are_practically_unique() -> None:
    ids = {new_run_id() for _ in range(200)}
    assert len(ids) == 200

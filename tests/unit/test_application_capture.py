"""`run_capture` orchestration against fake `Runner`/`DatabaseLifecycle`/`CatalogReader`.

No Docker here — this tests the sequencing/decision logic in isolation, the
same split as every other BE-16/17/18 adapter: `tests/integration/test_capture.py`
is the real end-to-end round trip.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from pgproof.application.capture import TestCaptureSpec as CaptureSpec
from pgproof.application.capture import run_capture
from pgproof.domain.execution import RunnerConfig, RunOutcome
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.schema import SchemaIR, SchemaProvenance, UnsupportedConstruct
from pgproof.ports.database import DisposableDatabase, GeneratedCredentials
from pgproof.ports.runner import RunSpec

_HOST_CREDENTIALS = GeneratedCredentials(
    host="127.0.0.1", port=1, user="pgproof", password="x", database="pgproof"
)
_INTERNAL_CREDENTIALS = GeneratedCredentials(
    host="pgproof-postgres-abc", port=5432, user="pgproof", password="x", database="pgproof"
)
_DATABASE = DisposableDatabase(
    credentials=_HOST_CREDENTIALS,
    container_id="container123",
    internal_credentials=_INTERNAL_CREDENTIALS,
)
_SUCCESS = RunOutcome(
    exit_code=0, timed_out=False, cancelled=False, stdout="", stderr="", duration_seconds=1.0
)
_FAILURE = RunOutcome(
    exit_code=1, timed_out=False, cancelled=False, stdout="", stderr="boom", duration_seconds=1.0
)


@dataclass
class _FakeRunner:
    outcome: RunOutcome
    calls: list[RunSpec] = field(default_factory=list)

    def run(self, spec: RunSpec) -> RunOutcome:
        self.calls.append(spec)
        return self.outcome


@dataclass
class _FakeSequenceRunner:
    """One outcome per successive `run()` call — migration, then test phase."""

    outcomes: list[RunOutcome]
    calls: list[RunSpec] = field(default_factory=list)

    def run(self, spec: RunSpec) -> RunOutcome:
        self.calls.append(spec)
        return self.outcomes[len(self.calls) - 1]


@dataclass
class _FakeLifecycle:
    database: DisposableDatabase
    started: list[dict[str, object]] = field(default_factory=list)
    stopped: list[DisposableDatabase] = field(default_factory=list)

    def start(
        self, *, image: str, timeout_seconds: float, network: str | None = None
    ) -> DisposableDatabase:
        self.started.append(
            {"image": image, "timeout_seconds": timeout_seconds, "network": network}
        )
        return self.database

    def stop(self, database: DisposableDatabase) -> None:
        self.stopped.append(database)


@dataclass
class _FakeCatalogReader:
    schema: SchemaIR
    calls: list[GeneratedCredentials] = field(default_factory=list)

    def introspect(self, credentials: GeneratedCredentials) -> SchemaIR:
        self.calls.append(credentials)
        return self.schema


def _kwargs(**overrides: object) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "root": Path("/repo"),
        "runner": _FakeRunner(outcome=_SUCCESS),
        "database_lifecycle": _FakeLifecycle(database=_DATABASE),
        "catalog_reader": _FakeCatalogReader(
            schema=SchemaIR(provenance=SchemaProvenance.PHYSICAL_CATALOG)
        ),
        "config": RunnerConfig(
            image="alpine:3.19", migration_command=("alembic", "upgrade", "head")
        ),
        "postgres_image": "postgres:17",
        "network_name": "pgproof-net-abc123",
        "allowlisted_environment": {},
        "static_schema": SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION),
        "orm_schema": SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION),
        "code": CodeIR(orm="sqlalchemy"),
    }
    defaults.update(overrides)
    return defaults


def test_a_successful_migration_introspects_and_reconciles() -> None:
    result = run_capture(**_kwargs())
    assert result.succeeded is True
    assert result.head_matched is True
    assert result.physical_schema is not None
    assert result.reconciliation is not None


def test_a_failed_migration_never_introspects_or_reconciles() -> None:
    catalog_reader = _FakeCatalogReader(
        schema=SchemaIR(provenance=SchemaProvenance.PHYSICAL_CATALOG)
    )
    result = run_capture(
        **_kwargs(runner=_FakeRunner(outcome=_FAILURE), catalog_reader=catalog_reader)
    )
    assert result.succeeded is False
    assert result.head_matched is None
    assert result.physical_schema is None
    assert result.reconciliation is None
    assert catalog_reader.calls == []


def test_the_database_is_always_stopped_even_on_failure() -> None:
    lifecycle = _FakeLifecycle(database=_DATABASE)
    run_capture(**_kwargs(runner=_FakeRunner(outcome=_FAILURE), database_lifecycle=lifecycle))
    assert lifecycle.stopped == [_DATABASE]


def test_the_database_is_stopped_even_when_the_runner_raises() -> None:
    class _RaisingRunner:
        def run(self, spec: RunSpec) -> RunOutcome:  # noqa: ARG002
            raise RuntimeError("boom")

    lifecycle = _FakeLifecycle(database=_DATABASE)
    with pytest.raises(RuntimeError, match="boom"):
        run_capture(**_kwargs(runner=_RaisingRunner(), database_lifecycle=lifecycle))
    assert lifecycle.stopped == [_DATABASE]


def test_a_head_mismatch_is_reported_without_failing_the_outcome() -> None:
    physical = SchemaIR(provenance=SchemaProvenance.PHYSICAL_CATALOG, migration_head="deadbeef00")
    static = SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION, migration_head="6a912ef4c1b8")
    result = run_capture(
        **_kwargs(catalog_reader=_FakeCatalogReader(schema=physical), static_schema=static)
    )
    assert result.succeeded is True
    assert result.head_matched is False


def test_no_static_head_to_compare_against_counts_as_matched() -> None:
    physical = SchemaIR(provenance=SchemaProvenance.PHYSICAL_CATALOG, migration_head="deadbeef00")
    static = SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION)  # no migration_head
    result = run_capture(
        **_kwargs(catalog_reader=_FakeCatalogReader(schema=physical), static_schema=static)
    )
    assert result.head_matched is True


def test_unverified_migration_operations_are_always_surfaced_from_the_static_schema() -> None:
    unsupported = (UnsupportedConstruct(kind="op_execute", reason="raw SQL not resolved"),)
    static = SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION, unsupported=unsupported)
    result = run_capture(**_kwargs(static_schema=static))
    assert result.unverified_migration_operations == unsupported

    failed = run_capture(**_kwargs(runner=_FakeRunner(outcome=_FAILURE), static_schema=static))
    assert failed.unverified_migration_operations == unsupported


def test_an_empty_migration_command_is_rejected_before_starting_anything() -> None:
    lifecycle = _FakeLifecycle(database=_DATABASE)
    with pytest.raises(ValueError, match="migration_command"):
        run_capture(
            **_kwargs(
                config=RunnerConfig(image="alpine:3.19"),  # no migration_command
                database_lifecycle=lifecycle,
            )
        )
    assert lifecycle.started == []


def test_the_environment_carries_the_allowlist_and_the_generated_db_url() -> None:
    runner = _FakeRunner(outcome=_SUCCESS)
    run_capture(**_kwargs(runner=runner, allowlisted_environment={"APP_ENV": "test"}))
    spec = runner.calls[0]
    assert spec.environment["APP_ENV"] == "test"
    assert spec.environment["DATABASE_URL"] == _INTERNAL_CREDENTIALS.dsn


def test_the_runner_and_database_join_the_same_network() -> None:
    runner = _FakeRunner(outcome=_SUCCESS)
    lifecycle = _FakeLifecycle(database=_DATABASE)
    run_capture(**_kwargs(runner=runner, database_lifecycle=lifecycle))
    assert lifecycle.started[0]["network"] == "pgproof-net-abc123"
    assert runner.calls[0].network == "pgproof-net-abc123"


def test_the_migration_command_from_config_is_what_actually_runs() -> None:
    runner = _FakeRunner(outcome=_SUCCESS)
    run_capture(**_kwargs(runner=runner))
    assert runner.calls[0].command == ("alembic", "upgrade", "head")


def test_the_catalog_is_introspected_using_the_host_facing_credentials() -> None:
    catalog_reader = _FakeCatalogReader(
        schema=SchemaIR(provenance=SchemaProvenance.PHYSICAL_CATALOG)
    )
    run_capture(**_kwargs(catalog_reader=catalog_reader))
    assert catalog_reader.calls == [_HOST_CREDENTIALS]


# --------------------------------------------------------------------------- #
# BE-20: the test phase, when a `TestCaptureSpec` is given
# --------------------------------------------------------------------------- #
def _test_capture_spec(**overrides: object) -> CaptureSpec:
    defaults: dict[str, Any] = {
        "command": ("pytest", "-q"),
        "plugin_source": "print('plugin')",
        "plugin_workspace_path": "_pgproof_capture_plugin.py",
        "plugin_module_env": "PYTEST_PLUGINS",
        "plugin_module_name": "_pgproof_capture_plugin",
        "pythonpath_env": "PYTHONPATH",
        "capture_file_env": "PGPROOF_CAPTURE_FILE",
        "capture_file_path": ".pgproof-capture/events.ndjson",
        "summary_file_path": ".pgproof-capture/summary.json",
    }
    defaults.update(overrides)
    return CaptureSpec(**defaults)


def _event_line(sequence: int) -> str:
    payload = {
        "sequence": sequence,
        "duration_us": 10,
        "statement": "SELECT 1",
        "dialect": "postgresql",
        "parameters": [],
        "executemany": False,
        "batch_size": None,
        "rowcount": 1,
        "transaction_id": None,
        "node_id": "tests/test_x.py::test_y",
        "phase": "call",
        "call_sites": [],
        "error_class": None,
        "process_id": 1,
        "thread_id": 1,
        "task_id": None,
    }
    return json.dumps(payload)


def test_with_no_test_capture_spec_the_runner_only_runs_once() -> None:
    runner = _FakeRunner(outcome=_SUCCESS)
    result = run_capture(**_kwargs(runner=runner))
    assert len(runner.calls) == 1
    assert result.test_capture is None


def test_a_successful_migration_and_test_run_parses_the_captured_events() -> None:
    capture_path = ".pgproof-capture/events.ndjson"
    test_outcome = RunOutcome(
        exit_code=0,
        timed_out=False,
        cancelled=False,
        stdout="",
        stderr="",
        duration_seconds=1.0,
        captured_files={
            capture_path: (_event_line(1) + "\n" + _event_line(2) + "\n").encode("utf-8")
        },
    )
    runner = _FakeSequenceRunner(outcomes=[_SUCCESS, test_outcome])
    result = run_capture(
        **_kwargs(runner=runner, test_capture=_test_capture_spec(capture_file_path=capture_path))
    )
    assert len(runner.calls) == 2
    assert result.test_capture is not None
    assert result.test_capture.succeeded is True
    assert [event.sequence for event in result.test_capture.events] == [1, 2]
    assert result.test_capture.malformed_event_lines == 0


def test_when_no_summary_file_was_captured_the_summary_defaults_to_zero() -> None:
    capture_path = ".pgproof-capture/events.ndjson"
    test_outcome = RunOutcome(
        exit_code=0,
        timed_out=False,
        cancelled=False,
        stdout="",
        stderr="",
        duration_seconds=1.0,
        captured_files={capture_path: (_event_line(1) + "\n").encode("utf-8")},
    )
    runner = _FakeSequenceRunner(outcomes=[_SUCCESS, test_outcome])
    result = run_capture(
        **_kwargs(runner=runner, test_capture=_test_capture_spec(capture_file_path=capture_path))
    )
    assert result.test_capture is not None
    assert result.test_capture.summary.selected_tests == 0
    assert result.test_capture.summary.transaction_outcomes == {}


def test_the_summary_file_is_parsed_into_the_test_capture_result() -> None:
    capture_path = ".pgproof-capture/events.ndjson"
    summary_path = ".pgproof-capture/summary.json"
    summary_payload = json.dumps(
        {
            "selected_tests": 3,
            "passed_tests": 2,
            "failed_tests": 1,
            "transaction_outcomes": {"1": True},
        }
    ).encode("utf-8")
    test_outcome = RunOutcome(
        exit_code=0,
        timed_out=False,
        cancelled=False,
        stdout="",
        stderr="",
        duration_seconds=1.0,
        captured_files={capture_path: b"", summary_path: summary_payload},
    )
    runner = _FakeSequenceRunner(outcomes=[_SUCCESS, test_outcome])
    result = run_capture(
        **_kwargs(
            runner=runner,
            test_capture=_test_capture_spec(
                capture_file_path=capture_path, summary_file_path=summary_path
            ),
        )
    )
    assert result.test_capture is not None
    summary = result.test_capture.summary
    assert summary.selected_tests == 3
    assert summary.passed_tests == 2
    assert summary.failed_tests == 1
    assert summary.transaction_outcomes == {"1": True}


def test_the_test_phase_carries_its_plugin_and_capture_env_vars() -> None:
    runner = _FakeSequenceRunner(outcomes=[_SUCCESS, _SUCCESS])
    run_capture(**_kwargs(runner=runner, test_capture=_test_capture_spec()))
    test_spec = runner.calls[1]
    assert test_spec.command == ("pytest", "-q")
    assert test_spec.inject_files == {"_pgproof_capture_plugin.py": "print('plugin')"}
    assert test_spec.capture_paths == (
        ".pgproof-capture/events.ndjson",
        ".pgproof-capture/summary.json",
    )
    assert test_spec.environment["PYTEST_PLUGINS"] == "_pgproof_capture_plugin"
    assert test_spec.environment["PYTHONPATH"] == "."
    assert test_spec.environment["PGPROOF_CAPTURE_FILE"] == ".pgproof-capture/events.ndjson"
    assert test_spec.environment["DATABASE_URL"] == _INTERNAL_CREDENTIALS.dsn
    assert test_spec.network == "pgproof-net-abc123"


def test_a_failed_migration_never_runs_the_test_phase() -> None:
    runner = _FakeSequenceRunner(outcomes=[_FAILURE])
    result = run_capture(**_kwargs(runner=runner, test_capture=_test_capture_spec()))
    assert len(runner.calls) == 1
    assert result.test_capture is None


def test_malformed_capture_lines_are_counted_not_raised() -> None:
    capture_path = ".pgproof-capture/events.ndjson"
    test_outcome = RunOutcome(
        exit_code=0,
        timed_out=False,
        cancelled=False,
        stdout="",
        stderr="",
        duration_seconds=1.0,
        captured_files={capture_path: (_event_line(1) + "\nnot json\n").encode("utf-8")},
    )
    runner = _FakeSequenceRunner(outcomes=[_SUCCESS, test_outcome])
    result = run_capture(
        **_kwargs(runner=runner, test_capture=_test_capture_spec(capture_file_path=capture_path))
    )
    assert result.test_capture is not None
    assert len(result.test_capture.events) == 1
    assert result.test_capture.malformed_event_lines == 1


def test_a_failed_test_run_still_reports_whatever_was_captured() -> None:
    capture_path = ".pgproof-capture/events.ndjson"
    failed_test_outcome = RunOutcome(
        exit_code=1,
        timed_out=False,
        cancelled=False,
        stdout="",
        stderr="",
        duration_seconds=1.0,
        captured_files={capture_path: (_event_line(1) + "\n").encode("utf-8")},
    )
    runner = _FakeSequenceRunner(outcomes=[_SUCCESS, failed_test_outcome])
    result = run_capture(
        **_kwargs(runner=runner, test_capture=_test_capture_spec(capture_file_path=capture_path))
    )
    assert result.test_capture is not None
    assert result.test_capture.succeeded is False
    assert len(result.test_capture.events) == 1


def test_the_database_is_stopped_after_a_successful_test_phase_too() -> None:
    lifecycle = _FakeLifecycle(database=_DATABASE)
    runner = _FakeSequenceRunner(outcomes=[_SUCCESS, _SUCCESS])
    run_capture(
        **_kwargs(runner=runner, database_lifecycle=lifecycle, test_capture=_test_capture_spec())
    )
    assert lifecycle.stopped == [_DATABASE]

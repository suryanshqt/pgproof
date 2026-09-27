"""`pgproof capture`: stage transitions, artifact writing, and approval/error
paths, against fakes for every Docker/Postgres-touching dependency — the same
isolation `tests/unit/test_application_capture.py` already uses for
`run_capture` itself, one layer up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from click.testing import CliRunner

from pgproof.adapters.pytest_capture import CAPTURE_FILE_PATH
from pgproof.adapters.repository.alembic_static import AlembicStaticResult, RevisionGraphReport
from pgproof.adapters.repository.sqlalchemy_static import SqlAlchemyStaticResult
from pgproof.adapters.runner.docker import DockerCapability, RunnerUnavailableError
from pgproof.cli.app import main
from pgproof.cli.commands import capture as capture_module
from pgproof.domain.config import ProjectConfig
from pgproof.domain.execution import RunnerConfig, RunOutcome
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.schema import SchemaIR, SchemaProvenance
from pgproof.ports.database import DisposableDatabase, GeneratedCredentials
from pgproof.ports.runner import RunSpec

_HOST_CREDENTIALS = GeneratedCredentials(
    host="127.0.0.1", port=1, user="pgproof", password="x", database="pgproof"
)
_INTERNAL_CREDENTIALS = GeneratedCredentials(
    host="pgproof-postgres-abc", port=5432, user="pgproof", password="x", database="pgproof"
)
_DATABASE = DisposableDatabase(
    credentials=_HOST_CREDENTIALS, container_id="c1", internal_credentials=_INTERNAL_CREDENTIALS
)
_SUCCESS = RunOutcome(
    exit_code=0, timed_out=False, cancelled=False, stdout="", stderr="", duration_seconds=1.0
)
_FAILURE = RunOutcome(
    exit_code=1, timed_out=False, cancelled=False, stdout="", stderr="boom", duration_seconds=1.0
)
_REACHABLE = DockerCapability(cli_found=True, daemon_reachable=True)
_UNREACHABLE = DockerCapability(cli_found=True, daemon_reachable=False)

_VALID_EVENT = (
    b'{"sequence":1,"duration_us":10,"statement":"SELECT 1","dialect":"postgresql",'
    b'"parameters":[],"executemany":false,"batch_size":null,"rowcount":1,'
    b'"transaction_id":null,"node_id":"tests/test_x.py::test_y","phase":"call",'
    b'"call_sites":[],"error_class":null,"process_id":1,"thread_id":1,"task_id":null}\n'
)
_TEST_FAILURE_WITH_EVENTS = RunOutcome(
    exit_code=1,
    timed_out=False,
    cancelled=False,
    stdout="",
    stderr="",
    duration_seconds=1.0,
    captured_files={CAPTURE_FILE_PATH: _VALID_EVENT},
)
_TEST_SUCCESS_MALFORMED = RunOutcome(
    exit_code=0,
    timed_out=False,
    cancelled=False,
    stdout="",
    stderr="",
    duration_seconds=1.0,
    captured_files={CAPTURE_FILE_PATH: _VALID_EVENT + b"not json\n"},
)


@dataclass
class _FakeRunner:
    outcomes: list[RunOutcome]
    calls: list[RunSpec] = field(default_factory=list)

    def run(self, spec: RunSpec) -> RunOutcome:
        self.calls.append(spec)
        return self.outcomes[len(self.calls) - 1]


class _RaisingRunner:
    def run(self, spec: RunSpec) -> RunOutcome:  # noqa: ARG002
        raise RunnerUnavailableError("Docker daemon is not reachable")


@dataclass
class _FakeLifecycle:
    def start(
        self, *, image: str, timeout_seconds: float, network: str | None = None
    ) -> DisposableDatabase:
        del image, timeout_seconds, network
        return _DATABASE

    def stop(self, database: DisposableDatabase) -> None:
        pass


@dataclass
class _FakeCatalogReader:
    schema: SchemaIR

    def introspect(self, credentials: GeneratedCredentials) -> SchemaIR:  # noqa: ARG002
        return self.schema


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    *,
    runner_outcomes: list[RunOutcome],
    capability: DockerCapability = _REACHABLE,
) -> None:
    monkeypatch.setattr(
        capture_module,
        "read_config",
        lambda _path: ProjectConfig(
            runner=RunnerConfig(image="alpine:3.19", migration_command=("alembic", "upgrade"))
        ),
    )
    monkeypatch.setattr(capture_module, "probe_docker", lambda: capability)
    monkeypatch.setattr(capture_module, "resolve_image", lambda _config, _root: "alpine:3.19")
    monkeypatch.setattr(capture_module, "create_network", lambda _name: None)
    monkeypatch.setattr(capture_module, "remove_network", lambda _name: None)
    monkeypatch.setattr(capture_module, "discover", lambda _root: object())
    monkeypatch.setattr(
        capture_module,
        "parse_sqlalchemy_models",
        lambda _inventory, _root: SqlAlchemyStaticResult(
            code=CodeIR(orm="sqlalchemy"),
            schema=SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION),
        ),
    )
    monkeypatch.setattr(capture_module, "parse_alembic_directories", lambda _inventory, _root: {})
    monkeypatch.setattr(
        capture_module,
        "DockerRunner",
        lambda: _FakeRunner(outcomes=runner_outcomes) if runner_outcomes else _RaisingRunner(),
    )
    monkeypatch.setattr(capture_module, "DockerPostgresLifecycle", _FakeLifecycle)
    monkeypatch.setattr(
        capture_module,
        "PsycopgCatalogReader",
        lambda: _FakeCatalogReader(schema=SchemaIR(provenance=SchemaProvenance.PHYSICAL_CATALOG)),
    )
    monkeypatch.setattr(capture_module, "load_plugin_source", lambda: "print('plugin')")


def test_a_missing_command_is_a_usage_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["capture", str(tmp_path), "--yes"])
    assert result.exit_code != 0
    assert "a command is required" in result.output


def test_a_missing_runner_config_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capture_module, "read_config", lambda _path: ProjectConfig())
    result = CliRunner().invoke(main, ["capture", str(tmp_path), "--yes", "--", "pytest"])
    assert result.exit_code != 0
    assert "pgproof configure" in result.output


def test_docker_unreachable_is_reported_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_common(monkeypatch, runner_outcomes=[], capability=_UNREACHABLE)
    result = CliRunner().invoke(main, ["capture", str(tmp_path), "--yes", "--", "pytest"])
    assert result.exit_code != 0
    assert "Docker is not reachable" in result.output


def test_declining_the_approval_prompt_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_common(monkeypatch, runner_outcomes=[_SUCCESS, _SUCCESS])
    result = CliRunner().invoke(main, ["capture", str(tmp_path), "--", "pytest"], input="n\n")
    assert result.exit_code != 0
    assert "not approved" in result.output


def test_yes_skips_the_prompt_and_runs_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_common(monkeypatch, runner_outcomes=[_SUCCESS, _SUCCESS])
    result = CliRunner().invoke(main, ["capture", str(tmp_path), "--yes", "--", "pytest", "-q"])
    assert result.exit_code == 0, result.output
    assert "Migration: ok" in result.output
    assert "Tests: ok" in result.output
    assert "Captured queries: 0" in result.output
    assert (tmp_path / ".pgproof" / "analysis" / "schema.json").is_file()
    workload_path = tmp_path / ".pgproof" / "analysis" / "workload.json"
    assert workload_path.is_file()
    workload_document = json.loads(workload_path.read_text(encoding="utf-8"))
    assert workload_document["artifact_type"] == "workload"
    assert workload_document["data"]["queries"] == []
    assert workload_document["data"]["coverage"] == "complete_for_selection"


def test_a_failed_migration_is_reported_and_skips_the_test_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_common(monkeypatch, runner_outcomes=[_FAILURE])
    result = CliRunner().invoke(main, ["capture", str(tmp_path), "--yes", "--", "pytest"])
    assert result.exit_code == 0, result.output
    assert "Migration: failed" in result.output
    assert "Tests:" not in result.output
    assert not (tmp_path / ".pgproof" / "analysis" / "schema.json").exists()


def test_a_runner_unavailable_error_fails_the_stage_and_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_common(monkeypatch, runner_outcomes=[])
    result = CliRunner().invoke(main, ["capture", str(tmp_path), "--yes", "--", "pytest"])
    assert result.exit_code != 0
    assert "Docker daemon is not reachable" in result.output


def test_an_eof_at_the_prompt_aborts_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_common(monkeypatch, runner_outcomes=[_SUCCESS, _SUCCESS])
    result = CliRunner().invoke(main, ["capture", str(tmp_path), "--", "pytest"], input="")
    assert result.exit_code != 0
    assert "not approved" in result.output


def test_a_failed_test_run_reports_whatever_was_captured_as_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_common(monkeypatch, runner_outcomes=[_SUCCESS, _TEST_FAILURE_WITH_EVENTS])
    result = CliRunner().invoke(main, ["capture", str(tmp_path), "--yes", "--", "pytest"])
    assert result.exit_code == 0, result.output
    assert "Tests: failed" in result.output
    assert "Captured queries: 1" in result.output
    workload_document = json.loads(
        (tmp_path / ".pgproof" / "analysis" / "workload.json").read_text(encoding="utf-8")
    )
    assert workload_document["data"]["coverage"] == "partial"
    assert len(workload_document["data"]["queries"]) == 1


def test_malformed_capture_lines_are_summarized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_common(monkeypatch, runner_outcomes=[_SUCCESS, _TEST_SUCCESS_MALFORMED])
    result = CliRunner().invoke(main, ["capture", str(tmp_path), "--yes", "--", "pytest"])
    assert result.exit_code == 0, result.output
    assert "Tests: ok" in result.output
    assert "Malformed capture lines: 1" in result.output
    workload_document = json.loads(
        (tmp_path / ".pgproof" / "analysis" / "workload.json").read_text(encoding="utf-8")
    )
    assert workload_document["data"]["coverage"] == "partial"


def test_the_static_schema_with_a_migration_head_is_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_head = SchemaIR(
        provenance=SchemaProvenance.STATIC_MIGRATION, migration_head="6a912ef4c1b8"
    )
    graph = RevisionGraphReport(
        revisions=(), roots=(), heads=(), merge_revisions=(), missing_predecessors=()
    )
    _patch_common(monkeypatch, runner_outcomes=[_SUCCESS, _SUCCESS])
    monkeypatch.setattr(
        capture_module,
        "parse_alembic_directories",
        lambda _inventory, _root: {
            "alembic": AlembicStaticResult(revisions=(), graph=graph, schema=with_head)
        },
    )
    result = CliRunner().invoke(main, ["capture", str(tmp_path), "--yes", "--", "pytest"])
    assert result.exit_code == 0, result.output
    assert "Migration: ok" in result.output

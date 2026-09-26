"""Migration execution, physical reconciliation, and pytest query capture.

`docs/ARCHITECTURE.md:307-329`'s `pgproof capture` sequence: steps up through
"introspect final catalog" always run; "run selected tests with capture
plugin" (BE-20) runs too, against the same disposable database, when the
caller passes a `TestCaptureSpec`. Orchestration only, over already-injected
ports (`Runner`, `DatabaseLifecycle`, `CatalogReader`): no adapter
construction, no `RunSession`, no filesystem writes beyond what the `Runner`
port itself performs inside its staged workspace, no `pgproof.toml` reading.
Those belong to `cli/commands/capture.py`, mirroring how
`cli/commands/review.py` owns all I/O around `application/review.py`'s pure
decision logic.

A failed migration returns with `physical_schema=None` and
`reconciliation=None` — the caller never has a `SchemaIR` to write as
`analysis/schema.json`, which is what `docs/PR_ROADMAP.md`'s "failed
migrations produce no physical-analysis manifest" means mechanically: this
function simply never produces the artifact, rather than a store-level rule
suppressing one that exists.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from pgproof.domain.capture_event import CapturedQueryEvent, parse_capture_ndjson
from pgproof.domain.execution import RunnerConfig, RunOutcome
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.schema import SchemaIR, UnsupportedConstruct
from pgproof.domain.reconciliation import ReconciliationReport, reconcile
from pgproof.ports.database import CatalogReader, DatabaseLifecycle
from pgproof.ports.runner import Runner, RunSpec


@dataclass(frozen=True)
class TestCaptureSpec:
    """Everything `run_capture` needs to run the test phase, opaque to it.

    The plugin's own module name, injected path, and environment-variable
    protocol are `adapters.pytest_capture`'s concern; `application` may not
    import `adapters` (`tests/unit/test_dependency_boundaries.py`), so the
    caller (`cli/commands/capture.py`, which may) resolves them and passes
    this bundle in, the same way `config.database_url_env` is already a
    caller-supplied name rather than a hardcoded one.
    """

    command: Sequence[str]
    plugin_source: str
    plugin_workspace_path: str
    plugin_module_env: str
    plugin_module_name: str
    pythonpath_env: str
    capture_file_env: str
    capture_file_path: str


@dataclass(frozen=True)
class TestCaptureResult:
    outcome: RunOutcome
    events: tuple[CapturedQueryEvent, ...]
    # NDJSON lines that failed to decode or validate — counted, never raised;
    # `docs/PR_ROADMAP.md`'s "failed tests preserve bounded capture" means one
    # bad line must not discard every event captured around it.
    malformed_event_lines: int

    @property
    def succeeded(self) -> bool:
        return self.outcome.succeeded


@dataclass(frozen=True)
class CaptureResult:
    outcome: RunOutcome
    head_matched: bool | None
    physical_schema: SchemaIR | None
    reconciliation: ReconciliationReport | None
    # The static migration's own `UnsupportedConstruct`s (e.g. an unresolved
    # `op.execute`) — BE-18's "DML preservation metadata": surfaced, not
    # newly verified, since nothing in this codebase diffs row contents yet.
    unverified_migration_operations: tuple[UnsupportedConstruct, ...]
    # BE-20: set only when migrations succeeded and a `TestCaptureSpec` was
    # given — the pytest capture phase never runs against a schema that
    # never reconciled.
    test_capture: TestCaptureResult | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome.succeeded


def run_capture(
    *,
    root: Path,
    runner: Runner,
    database_lifecycle: DatabaseLifecycle,
    catalog_reader: CatalogReader,
    config: RunnerConfig,
    postgres_image: str,
    network_name: str,
    allowlisted_environment: Mapping[str, str],
    static_schema: SchemaIR,
    orm_schema: SchemaIR,
    code: CodeIR,
    cancel_event: Event | None = None,
    test_capture: TestCaptureSpec | None = None,
) -> CaptureResult:
    """`docs/TECHNICAL_DESIGN.md` section 8, steps 2-9, plus (BE-20) the test
    phase when `test_capture` is given. Step 1 (statically resolving the
    expected head) is the caller's job — it's already
    `static_schema.migration_head`, from `adapters.repository.alembic_static`.

    `network_name` must already exist (`adapters.runner.docker.create_network`)
    and is *required*, not optional: without a shared network the runner
    container has no route to the disposable database at all, host-bound
    `127.0.0.1` credentials meaning nothing from inside another container.

    The test phase, when it runs, reuses this same disposable database and
    network — `docs/ARCHITECTURE.md:307-329`'s sequence runs migrations and
    tests against one instance, not two, so the captured queries observe
    exactly the catalog `reconciliation` above already validated.
    """
    if not config.migration_command:
        raise ValueError("config.migration_command must be set to run a capture")

    database = database_lifecycle.start(
        image=postgres_image, timeout_seconds=config.timeout_seconds, network=network_name
    )
    try:
        assert database.internal_credentials is not None  # network_name was given above
        environment = dict(allowlisted_environment)
        environment[config.database_url_env] = database.internal_credentials.dsn
        spec = RunSpec(
            source=root,
            config=config,
            command=config.migration_command,
            environment=environment,
            cancel_event=cancel_event,
            network=network_name,
        )
        outcome = runner.run(spec)
        if not outcome.succeeded:
            return CaptureResult(
                outcome=outcome,
                head_matched=None,
                physical_schema=None,
                reconciliation=None,
                unverified_migration_operations=static_schema.unsupported,
            )

        physical_schema = catalog_reader.introspect(database.credentials)
        head_matched = (
            static_schema.migration_head is None
            or physical_schema.migration_head == static_schema.migration_head
        )
        report = reconcile(physical_schema, orm_schema, code)
        test_result = None
        if test_capture is not None:
            test_result = _run_test_phase(
                root=root,
                runner=runner,
                config=config,
                environment=environment,
                network_name=network_name,
                cancel_event=cancel_event,
                spec=test_capture,
            )
        return CaptureResult(
            outcome=outcome,
            head_matched=head_matched,
            physical_schema=physical_schema,
            reconciliation=report,
            unverified_migration_operations=static_schema.unsupported,
            test_capture=test_result,
        )
    finally:
        database_lifecycle.stop(database)


def _run_test_phase(
    *,
    root: Path,
    runner: Runner,
    config: RunnerConfig,
    environment: Mapping[str, str],
    network_name: str,
    cancel_event: Event | None,
    spec: TestCaptureSpec,
) -> TestCaptureResult:
    test_environment = dict(environment)
    test_environment[spec.pythonpath_env] = "."
    test_environment[spec.plugin_module_env] = spec.plugin_module_name
    test_environment[spec.capture_file_env] = spec.capture_file_path
    run_spec = RunSpec(
        source=root,
        config=config,
        command=spec.command,
        environment=test_environment,
        cancel_event=cancel_event,
        network=network_name,
        inject_files={spec.plugin_workspace_path: spec.plugin_source},
        capture_paths=(spec.capture_file_path,),
    )
    outcome = runner.run(run_spec)
    raw = outcome.captured_files.get(spec.capture_file_path, b"")
    events, malformed = parse_capture_ndjson(raw)
    return TestCaptureResult(outcome=outcome, events=events, malformed_event_lines=malformed)

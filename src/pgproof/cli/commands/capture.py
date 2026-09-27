"""`pgproof capture`: run migrations, then selected tests, against a disposable
PostgreSQL instance inside an isolated runner. `docs/TECHNICAL_DESIGN.md`
section 2: `pgproof capture PATH -- COMMAND [ARGS...]`.

`docs/ARCHITECTURE.md:307-329`'s sequence, composed here from already-tested
pieces: `application.run_capture` (BE-18/20 orchestration),
`adapters.postgres` (disposable database + catalog), `adapters.runner.docker`
(isolated execution + network), `adapters.pytest_capture` (the injected
plugin).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import click

from pgproof import __version__
from pgproof.adapters.postgres.catalog import PsycopgCatalogReader
from pgproof.adapters.postgres.lifecycle import DockerPostgresLifecycle
from pgproof.adapters.pytest_capture import (
    CAPTURE_FILE_ENV,
    CAPTURE_FILE_PATH,
    CAPTURE_SUMMARY_PATH,
    PLUGIN_MODULE_NAME,
    PLUGIN_WORKSPACE_PATH,
    PLUGINS_ENV,
    PYTHONPATH_ENV,
    load_plugin_source,
)
from pgproof.adapters.repository.config_toml import read_config
from pgproof.adapters.repository.inventory import discover
from pgproof.adapters.runner.docker import (
    DockerRunner,
    RunnerUnavailableError,
    create_network,
    probe_docker,
    remove_network,
    resolve_image,
)
from pgproof.adapters.workload.amplification import annotate_amplifications
from pgproof.adapters.workload.reconstruct import reconstruct_workload
from pgproof.application.capture import (
    CaptureResult,
    TestCaptureResult,
    TestCaptureSpec,
    run_capture,
)
from pgproof.cli.commands.inspect import parse_alembic_directories, parse_sqlalchemy_models
from pgproof.domain.envelope import ArtifactType
from pgproof.domain.execution import build_execution_contract
from pgproof.domain.ir.schema import SchemaIR, SchemaProvenance
from pgproof.domain.ir.workload import WorkloadCoverage
from pgproof.domain.registry import envelope_model_for
from pgproof.domain.stages import StageName
from pgproof.ports.clock import SystemClock
from pgproof.store.atomic import write_bytes_atomic
from pgproof.store.paths import ProjectLayout
from pgproof.store.run import RunSession, format_rfc3339
from pgproof.store.run_id import new_run_id

_DEFAULT_POSTGRES_IMAGE = "postgres:17"


def _confirm(prompt: str, *, yes: bool) -> bool:
    if yes:
        return True
    try:
        return click.confirm(prompt)
    except click.exceptions.Abort:
        return False


def _select_physical_schema(alembic_schemas: tuple[SchemaIR, ...]) -> SchemaIR:
    for schema in alembic_schemas:
        if schema.migration_head is not None:
            return schema
    return SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION)


@click.command("capture", context_settings={"ignore_unknown_options": True})
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
)
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
@click.option("--yes", is_flag=True, help="Run without an interactive approval prompt.")
@click.option(
    "--postgres-image", default=_DEFAULT_POSTGRES_IMAGE, help="Disposable PostgreSQL image."
)
@click.pass_context
def capture(
    ctx: click.Context, path: Path, command: tuple[str, ...], yes: bool, postgres_image: str
) -> None:
    """Run COMMAND against PATH's migrations, in an isolated runner with a
    disposable PostgreSQL instance, capturing every query it issues.
    """
    del ctx
    root = path.resolve()
    if not command:
        raise click.UsageError("a command is required: pgproof capture PATH -- COMMAND [ARGS...]")

    config = read_config(root / "pgproof.toml")
    if config.runner is None or not config.runner.migration_command:
        raise click.UsageError(
            "pgproof.toml needs a [runner] table with migration_command set; run "
            "'pgproof configure' first"
        )
    runner_config = config.runner

    capability = probe_docker()
    if not capability.daemon_reachable:
        raise click.ClickException("Docker is not reachable; isolated execution is unavailable")

    resolved_image = resolve_image(runner_config, root)
    contract = build_execution_contract(runner_config, command, resolved_image=resolved_image)
    click.echo(f"Image:   {contract.image}")
    click.echo(f"Command: {' '.join(contract.command)}")
    click.echo(f"Network: {'enabled' if contract.network_enabled else 'disabled (isolated)'}")
    click.echo(f"CPU:     {contract.cpu}  Memory: {contract.memory}  PIDs: {contract.pids}")
    if not _confirm("Run this command in an isolated container?", yes=yes):
        raise click.ClickException("aborted: execution not approved")

    inventory = discover(root)
    orm_result = parse_sqlalchemy_models(inventory, root)
    alembic_results = parse_alembic_directories(inventory, root)
    static_schema = _select_physical_schema(tuple(r.schema for r in alembic_results.values()))

    layout = ProjectLayout(root)
    layout.ensure_base_layout()
    session = RunSession(layout, new_run_id(), __version__)
    network_name = f"pgproof-capture-{uuid.uuid4().hex[:12]}"
    create_network(network_name)
    try:
        session.start_stage(StageName.MIGRATION_SANDBOX)
        test_spec = TestCaptureSpec(
            command=command,
            plugin_source=load_plugin_source(),
            plugin_workspace_path=PLUGIN_WORKSPACE_PATH,
            plugin_module_env=PLUGINS_ENV,
            plugin_module_name=PLUGIN_MODULE_NAME,
            pythonpath_env=PYTHONPATH_ENV,
            capture_file_env=CAPTURE_FILE_ENV,
            capture_file_path=CAPTURE_FILE_PATH,
            summary_file_path=CAPTURE_SUMMARY_PATH,
        )
        try:
            result = run_capture(
                root=root,
                runner=DockerRunner(),
                database_lifecycle=DockerPostgresLifecycle(),
                catalog_reader=PsycopgCatalogReader(),
                config=runner_config,
                postgres_image=postgres_image,
                network_name=network_name,
                allowlisted_environment={},
                static_schema=static_schema,
                orm_schema=orm_result.schema,
                code=orm_result.code,
                test_capture=test_spec,
            )
        except RunnerUnavailableError as error:
            session.fail_stage(StageName.MIGRATION_SANDBOX, failure_reason=str(error))
            session.finish()
            raise click.ClickException(str(error)) from error

        _report_migration(session, layout, result)
        if result.test_capture is not None:
            _report_test_capture(session, layout, result)
        session.finish()
    finally:
        remove_network(network_name)

    _print_summary(result)


def _report_migration(session: RunSession, layout: ProjectLayout, result: CaptureResult) -> None:
    if not result.succeeded:
        session.fail_stage(
            StageName.MIGRATION_SANDBOX,
            failure_reason=f"migration command exited {result.outcome.exit_code}",
        )
        return
    session.complete_stage(StageName.MIGRATION_SANDBOX)
    if result.physical_schema is not None:
        envelope_cls = envelope_model_for(ArtifactType.SCHEMA)
        envelope = envelope_cls(
            tool_version=__version__,
            artifact_type=ArtifactType.SCHEMA,
            created_at=format_rfc3339(SystemClock().now()),
            run_id=session.run_id,
            data=result.physical_schema,
        )
        session.record_artifact(
            ArtifactType.SCHEMA, layout.analysis_path(ArtifactType.SCHEMA), envelope
        )


def _capture_coverage(test_capture: TestCaptureResult) -> tuple[WorkloadCoverage, str]:
    if not test_capture.succeeded:
        return (
            WorkloadCoverage.PARTIAL,
            f"test command exited {test_capture.outcome.exit_code}; "
            f"{len(test_capture.events)} query event(s) captured before it stopped",
        )
    if test_capture.malformed_event_lines:
        return (
            WorkloadCoverage.PARTIAL,
            f"{test_capture.malformed_event_lines} capture line(s) failed to parse",
        )
    return (
        WorkloadCoverage.COMPLETE_FOR_SELECTION,
        "capture completed for the selected test command",
    )


def _report_test_capture(session: RunSession, layout: ProjectLayout, result: CaptureResult) -> None:
    test_capture = result.test_capture
    assert test_capture is not None
    assert result.physical_schema is not None  # the test phase never runs without one
    session.start_stage(StageName.QUERY_CAPTURE)
    raw = "\n".join(event.canonical_json() for event in test_capture.events)
    write_bytes_atomic(
        layout.run_query_events_path(session.run_id),
        (raw + "\n").encode("utf-8") if raw else b"",
    )

    coverage, boundary_note = _capture_coverage(test_capture)
    workload = reconstruct_workload(
        test_capture.events,
        schema=result.physical_schema,
        transaction_outcomes=test_capture.summary.transaction_outcomes,
        coverage=coverage,
        boundary_note=boundary_note,
        selected_tests=test_capture.summary.selected_tests,
        passed_tests=test_capture.summary.passed_tests,
        failed_tests=test_capture.summary.failed_tests,
    )
    workload = annotate_amplifications(test_capture.events, workload, schema=result.physical_schema)
    envelope_cls = envelope_model_for(ArtifactType.WORKLOAD)
    envelope = envelope_cls(
        tool_version=__version__,
        artifact_type=ArtifactType.WORKLOAD,
        created_at=format_rfc3339(SystemClock().now()),
        run_id=session.run_id,
        data=workload,
    )
    session.record_artifact(
        ArtifactType.WORKLOAD, layout.analysis_path(ArtifactType.WORKLOAD), envelope
    )

    if coverage is WorkloadCoverage.PARTIAL:
        session.partial_stage(StageName.QUERY_CAPTURE, boundary_note=boundary_note)
        return
    session.complete_stage(StageName.QUERY_CAPTURE)


def _print_summary(result: CaptureResult) -> None:
    click.echo("")
    click.echo(f"Migration: {'ok' if result.succeeded else 'failed'}")
    if result.head_matched is not None:
        click.echo(f"Head match: {result.head_matched}")
    if result.test_capture is not None:
        test_capture = result.test_capture
        click.echo(f"Tests: {'ok' if test_capture.succeeded else 'failed'}")
        click.echo(f"Captured queries: {len(test_capture.events)}")
        if test_capture.malformed_event_lines:
            click.echo(f"Malformed capture lines: {test_capture.malformed_event_lines}")

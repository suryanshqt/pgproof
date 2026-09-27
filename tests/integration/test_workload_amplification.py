"""BE-22 accept criterion: "demo N+1 is observed, ordinary repetition is not
mislabeled." Real Docker, real disposable PostgreSQL, a real runner container
running the fixtures' own pytest suites under the capture plugin — the planted
`NPLUS1-001` in `fixtures/demo-broken/EXPECTED.yaml` against the same operation
in `fixtures/demo-clean`, whose `selectinload` fix is the control.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

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
from pgproof.adapters.repository.inventory import discover
from pgproof.adapters.runner.docker import (
    DockerRunner,
    create_network,
    probe_docker,
    remove_network,
)
from pgproof.adapters.workload.amplification import annotate_amplifications
from pgproof.adapters.workload.reconstruct import reconstruct_workload
from pgproof.application.capture import TestCaptureSpec as CaptureSpec
from pgproof.application.capture import run_capture
from pgproof.cli.commands.inspect import parse_alembic_directories, parse_sqlalchemy_models
from pgproof.domain.execution import RunnerConfig
from pgproof.domain.identifiers import operation_id
from pgproof.domain.ir.workload import AmplificationClass, OperationIR, WorkloadCoverage

requires_docker = pytest.mark.skipif(
    not probe_docker().daemon_reachable, reason="Docker daemon not reachable"
)
pytestmark = requires_docker

_POSTGRES_IMAGE = "postgres@sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675"
_FIXTURES = Path(__file__).parents[2] / "fixtures"
_NODE_ID = "tests/test_orders.py::test_order_totals_by_item_matches_stored_total"
# The same `postgresql://` -> `postgresql+psycopg://` rewrite
# `tests/integration/test_capture.py` documents for the migration phase: the
# fixtures hand `DATABASE_URL` straight to SQLAlchemy, which needs the
# dialect-qualified form to select psycopg3.
_REWRITE_SED = "s#^postgresql://#postgresql+psycopg://#"
_REWRITE_URL = f'DATABASE_URL=$(echo "$DATABASE_URL" | sed "{_REWRITE_SED}") '
_MIGRATION_COMMAND = ("sh", "-c", f"{_REWRITE_URL}/opt/venv/bin/alembic upgrade head")
_TEST_COMMAND = ("sh", "-c", f"{_REWRITE_URL}/opt/venv/bin/pytest {_NODE_ID}")


@pytest.fixture
def network() -> Iterator[str]:
    name = f"pgproof-net-{uuid.uuid4().hex[:12]}"
    create_network(name)
    try:
        yield name
    finally:
        remove_network(name)


def _capture_operation(root: Path, network: str) -> OperationIR:
    inventory = discover(root)
    alembic_results = parse_alembic_directories(inventory, root)
    static_schema = next(
        schema
        for schema in (result.schema for result in alembic_results.values())
        if schema.migration_head is not None
    )
    orm_result = parse_sqlalchemy_models(inventory, root)
    result = run_capture(
        root=root,
        runner=DockerRunner(),
        database_lifecycle=DockerPostgresLifecycle(),
        catalog_reader=PsycopgCatalogReader(),
        config=RunnerConfig(
            build="Dockerfile", migration_command=_MIGRATION_COMMAND, timeout_seconds=300
        ),
        postgres_image=_POSTGRES_IMAGE,
        network_name=network,
        allowlisted_environment={},
        static_schema=static_schema,
        orm_schema=orm_result.schema,
        code=orm_result.code,
        test_capture=CaptureSpec(
            command=_TEST_COMMAND,
            plugin_source=load_plugin_source(),
            plugin_workspace_path=PLUGIN_WORKSPACE_PATH,
            plugin_module_env=PLUGINS_ENV,
            plugin_module_name=PLUGIN_MODULE_NAME,
            pythonpath_env=PYTHONPATH_ENV,
            capture_file_env=CAPTURE_FILE_ENV,
            capture_file_path=CAPTURE_FILE_PATH,
            summary_file_path=CAPTURE_SUMMARY_PATH,
        ),
    )
    assert result.succeeded, result.outcome.stderr
    assert result.physical_schema is not None
    test_capture = result.test_capture
    assert test_capture is not None
    assert test_capture.succeeded, test_capture.outcome.stdout + test_capture.outcome.stderr

    workload = reconstruct_workload(
        test_capture.events,
        schema=result.physical_schema,
        transaction_outcomes=test_capture.summary.transaction_outcomes,
        coverage=WorkloadCoverage.COMPLETE_FOR_SELECTION,
        boundary_note="capture completed for the selected test command",
    )
    workload = annotate_amplifications(test_capture.events, workload, schema=result.physical_schema)
    wanted = operation_id("pytest", _NODE_ID, "call")
    return next(operation for operation in workload.operations if operation.id == wanted)


def test_demo_broken_lazy_loading_is_observed_as_an_n_plus_one(network: str) -> None:
    operation = _capture_operation(_FIXTURES / "demo-broken", network)
    assert len(operation.amplifications) == 1
    amplification = operation.amplifications[0]
    assert amplification.classification is AmplificationClass.OBSERVED_N_PLUS_ONE
    assert amplification.repetitions == 5
    assert amplification.relationship_name == "fk_order_items_order_id"
    assert amplification.call_site is not None
    assert amplification.call_site.path == "tests/test_orders.py"


def test_demo_cleans_eager_loading_reports_no_amplification(network: str) -> None:
    operation = _capture_operation(_FIXTURES / "demo-clean", network)
    assert operation.amplifications == ()

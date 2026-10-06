"""BE-29 accept criterion: "demo treatment preserves declared results and
reduces amplification while a deliberately wrong treatment is rejected."
Real Docker, real disposable PostgreSQL: `fixtures/demo-broken` (the planted
lazy-load N+1) as baseline, `fixtures/demo-clean` (the real `selectinload`
fix) as the correct treatment, and a patched copy of `demo-clean` that keeps
the same query-reducing fix but computes a deliberately wrong total as the
rejected treatment.
"""

from __future__ import annotations

import shutil
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
from pgproof.adapters.treatment.compare import compare_treatment
from pgproof.adapters.workload.amplification import annotate_amplifications
from pgproof.adapters.workload.reconstruct import reconstruct_workload
from pgproof.application.capture import TestCaptureSpec as CaptureSpec
from pgproof.application.capture import run_capture
from pgproof.cli.commands.inspect import parse_alembic_directories, parse_sqlalchemy_models
from pgproof.domain.execution import RunnerConfig
from pgproof.domain.identifiers import operation_id
from pgproof.domain.ir.workload import WorkloadCoverage, WorkloadIR

requires_docker = pytest.mark.skipif(
    not probe_docker().daemon_reachable, reason="Docker daemon not reachable"
)
pytestmark = requires_docker

_POSTGRES_IMAGE = "postgres@sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675"
_FIXTURES = Path(__file__).parents[2] / "fixtures"
_NODE_ID = "tests/test_orders.py::test_order_totals_by_item_matches_stored_total"
_REWRITE_SED = "s#^postgresql://#postgresql+psycopg://#"
_REWRITE_URL = f'DATABASE_URL=$(echo "$DATABASE_URL" | sed "{_REWRITE_SED}") '
_MIGRATION_COMMAND = ("sh", "-c", f"{_REWRITE_URL}/opt/venv/bin/alembic upgrade head")
_TEST_COMMAND = ("sh", "-c", f"{_REWRITE_URL}/opt/venv/bin/pytest {_NODE_ID}")
_OPERATION = operation_id("pytest", _NODE_ID, "call")


@pytest.fixture
def network() -> Iterator[str]:
    name = f"pgproof-net-{uuid.uuid4().hex[:12]}"
    create_network(name)
    try:
        yield name
    finally:
        remove_network(name)


def _capture_workload(root: Path, network: str) -> WorkloadIR:
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
    # Deliberately not asserted here: the wrong-treatment fixture is expected
    # to fail its own test, and that failure is exactly what this module must
    # observe rather than raise past.

    workload = reconstruct_workload(
        test_capture.events,
        schema=result.physical_schema,
        transaction_outcomes=test_capture.summary.transaction_outcomes,
        coverage=WorkloadCoverage.COMPLETE_FOR_SELECTION,
        boundary_note="capture completed for the selected test command",
        selected_tests=test_capture.summary.selected_tests,
        passed_tests=test_capture.summary.passed_tests,
        failed_tests=test_capture.summary.failed_tests,
    )
    return annotate_amplifications(test_capture.events, workload, schema=result.physical_schema)


@pytest.fixture
def wrong_treatment_root(tmp_path: Path) -> Path:
    """`demo-clean`'s own `selectinload` fix (still query-reducing), with
    `order_totals_by_item`'s total computation broken — drops
    `unit_price_cents` from the sum, so the fixture's own assertion
    (`test_order_totals_by_item_matches_stored_total`: "all(total == 5000 for
    _, total in totals)") fails for any order with more than one item.
    """
    destination = tmp_path / "wrong-treatment"
    shutil.copytree(_FIXTURES / "demo-clean", destination)
    repositories = destination / "app" / "repositories.py"
    original = repositories.read_text(encoding="utf-8")
    broken = original.replace(
        "sum(item.quantity * item.unit_price_cents for item in order.items)",
        "sum(item.quantity for item in order.items)",
    )
    assert broken != original, "the total-computation line to patch was not found"
    repositories.write_text(broken, encoding="utf-8")
    return destination


def test_demo_cleans_real_fix_reduces_amplification_and_is_verified(network: str) -> None:
    baseline = _capture_workload(_FIXTURES / "demo-broken", network)
    treatment = _capture_workload(_FIXTURES / "demo-clean", network)
    comparison = compare_treatment(baseline, treatment, operation_id=_OPERATION)
    assert comparison.amplification_reduced is True
    assert comparison.results_equivalent is True
    assert comparison.verified is True
    assert comparison.unsupported_reason is None
    assert comparison.treatment_query_count < comparison.baseline_query_count


def test_a_deliberately_wrong_treatment_is_rejected(
    network: str, wrong_treatment_root: Path
) -> None:
    baseline = _capture_workload(_FIXTURES / "demo-broken", network)
    treatment = _capture_workload(wrong_treatment_root, network)
    assert treatment.failed_tests > 0, "the patched fixture was expected to fail its own test"
    comparison = compare_treatment(baseline, treatment, operation_id=_OPERATION)
    # Still query-reducing (the same real selectinload fix), which is exactly
    # why this case matters: a wrong treatment is not rejected for looking
    # unoptimized, it is rejected for breaking correctness.
    assert comparison.amplification_reduced is True
    assert comparison.results_equivalent is False
    assert comparison.verified is False

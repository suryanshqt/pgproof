"""BE-18 accept criterion: "failed migrations produce no physical-analysis
manifest and successful complex fixtures reconcile correctly." Real Docker,
real disposable PostgreSQL, a real runner container running real Alembic
against `fixtures/demo-broken` — the same "complex, real" fixture this
session's fixture-based golden tests have used throughout, not a synthetic
stand-in.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from pgproof.adapters.postgres.catalog import PsycopgCatalogReader
from pgproof.adapters.postgres.lifecycle import DockerPostgresLifecycle
from pgproof.adapters.repository.inventory import discover
from pgproof.adapters.runner.docker import (
    DockerRunner,
    create_network,
    find_orphaned_containers,
    find_orphaned_networks,
    probe_docker,
    remove_network,
)
from pgproof.application.capture import CaptureResult, run_capture
from pgproof.cli.commands.inspect import parse_alembic_directories, parse_sqlalchemy_models
from pgproof.domain.execution import RunnerConfig
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.schema import SchemaIR, SchemaProvenance
from pgproof.domain.reconciliation import ObservationKind

requires_docker = pytest.mark.skipif(
    not probe_docker().daemon_reachable, reason="Docker daemon not reachable"
)
pytestmark = requires_docker

_POSTGRES_IMAGE = "postgres@sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675"
_DEMO_BROKEN = Path(__file__).parents[2] / "fixtures" / "demo-broken"
# The dependencies are already baked into the image at build time
# (`fixtures/demo-broken/Dockerfile`) — no network activity at runtime.
# `run_capture` injects a driver-agnostic `postgresql://` DSN (the scheme
# `psycopg.connect` itself requires, BE-17); demo-broken's own `env.py`
# passes `DATABASE_URL` straight to SQLAlchemy, which needs the
# dialect-qualified `postgresql+psycopg://` to select psycopg3 — the exact
# rewrite `.github/workflows/ci.yml`'s own `fixtures` job already does for
# this fixture, just done here instead of by GHA's `services:` key.
_MIGRATION_COMMAND = (
    "sh",
    "-c",
    'DATABASE_URL=$(echo "$DATABASE_URL" | sed "s#^postgresql://#postgresql+psycopg://#") '
    "/opt/venv/bin/alembic upgrade head",
)


@pytest.fixture
def network() -> Iterator[str]:
    name = f"pgproof-net-{uuid.uuid4().hex[:12]}"
    create_network(name)
    try:
        yield name
    finally:
        remove_network(name)


def _static_schema_and_code(root: Path) -> tuple[SchemaIR, SchemaIR, CodeIR]:
    inventory = discover(root)
    alembic_results = parse_alembic_directories(inventory, root)
    resolved = [r.schema for r in alembic_results.values() if r.schema.migration_head is not None]
    static_schema = resolved[0] if resolved else next(iter(alembic_results.values())).schema
    sqlalchemy_result = parse_sqlalchemy_models(inventory, root)
    return static_schema, sqlalchemy_result.schema, sqlalchemy_result.code


_EMPTY_SCHEMAS = (
    SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION),
    SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION),
    CodeIR(orm="sqlalchemy"),
)


def _run(
    *,
    network: str,
    config: RunnerConfig,
    schemas: tuple[SchemaIR, SchemaIR, CodeIR] = _EMPTY_SCHEMAS,
) -> CaptureResult:
    static_schema, orm_schema, code = schemas
    return run_capture(
        root=_DEMO_BROKEN,
        runner=DockerRunner(),
        database_lifecycle=DockerPostgresLifecycle(),
        catalog_reader=PsycopgCatalogReader(),
        config=config,
        postgres_image=_POSTGRES_IMAGE,
        network_name=network,
        allowlisted_environment={},
        static_schema=static_schema,
        orm_schema=orm_schema,
        code=code,
    )


def test_a_successful_complex_fixture_migration_reconciles_correctly(network: str) -> None:
    schemas = _static_schema_and_code(_DEMO_BROKEN)
    assert schemas[0].migration_head is not None  # demo-broken has one clean head

    result = _run(
        network=network,
        config=RunnerConfig(
            build="Dockerfile", migration_command=_MIGRATION_COMMAND, timeout_seconds=120
        ),
        schemas=schemas,
    )

    assert result.succeeded, result.outcome.stderr
    assert result.head_matched is True
    assert result.physical_schema is not None
    assert {t.name for t in result.physical_schema.tables} >= {"tenants", "users", "orders"}
    assert result.reconciliation is not None
    # demo-broken's own known defect (established across this session's other
    # fixture-based tests): the ORM declares orders -> tenants without a
    # physical foreign key backing it.
    kinds = {o.kind for o in result.reconciliation.observations}
    assert ObservationKind.ORM_ONLY_RELATIONSHIP in kinds


def test_a_failed_migration_produces_no_physical_schema(network: str) -> None:
    result = _run(
        network=network,
        config=RunnerConfig(image="alpine:3.19", migration_command=("sh", "-c", "exit 1")),
    )
    assert result.succeeded is False
    assert result.physical_schema is None
    assert result.reconciliation is None
    assert result.head_matched is None


def test_run_capture_itself_leaves_no_containers_behind(network: str) -> None:
    """The `network` fixture owns the network's own lifecycle (created before,
    removed after this test returns) — only the containers `run_capture`
    itself creates (the disposable database, the runner) are its job to
    prove clean, mid-test.
    """
    _run(
        network=network,
        config=RunnerConfig(image="alpine:3.19", migration_command=("sh", "-c", "exit 0")),
    )
    assert find_orphaned_containers() == ()


def test_orphan_network_detection_finds_and_removes_a_network_nothing_cleaned_up() -> None:
    """Mirrors `test_runner_adversarial.py`'s own orphan-container test: a
    network created directly, bypassing the normal create-then-remove path,
    to prove `find_orphaned_networks`/`remove_network` work together on a
    genuine leak, not just the happy path the `network` fixture exercises."""
    name = f"pgproof-net-{uuid.uuid4().hex[:12]}"
    create_network(name)
    try:
        assert name in find_orphaned_networks()
    finally:
        remove_network(name)
    assert name not in find_orphaned_networks()

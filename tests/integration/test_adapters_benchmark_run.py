"""BE-25 accept criterion: "intentionally noisy fixtures are inconclusive and
stable fixtures reproduce direction across repeated runs." Real Docker, real
PostgreSQL, BE-23's own seeder filling `fixtures/demo-broken`'s real
reconciled schema at a scale large enough for a missing index to matter —
the same `orders.user_id` gap `fixtures/demo-broken/EXPECTED.yaml` calls
`IDX-001`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import psycopg
import pytest

from pgproof.adapters.benchmark.run import CandidateDDL, run_experiment
from pgproof.adapters.postgres.catalog import PsycopgCatalogReader
from pgproof.adapters.postgres.lifecycle import DockerPostgresLifecycle
from pgproof.adapters.runner.docker import (
    DockerRunner,
    create_network,
    probe_docker,
    remove_network,
)
from pgproof.adapters.seeder.load import load_dataset
from pgproof.domain.execution import RunnerConfig
from pgproof.domain.identifiers import table_id
from pgproof.domain.ir.schema import SchemaIR
from pgproof.ports.database import GeneratedCredentials
from pgproof.ports.runner import RunSpec

requires_docker = pytest.mark.skipif(
    not probe_docker().daemon_reachable, reason="Docker daemon not reachable"
)
pytestmark = requires_docker

_POSTGRES_IMAGE = "postgres@sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675"
_DEMO_BROKEN = Path(__file__).parents[2] / "fixtures" / "demo-broken"
_MIGRATION_COMMAND = (
    "sh",
    "-c",
    'DATABASE_URL=$(echo "$DATABASE_URL" | sed "s#^postgresql://#postgresql+psycopg://#") '
    "/opt/venv/bin/alembic upgrade head",
)

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
_TENANTS = table_id("public", "tenants")
_USERS = table_id("public", "users")
_PRODUCTS = table_id("public", "products")
_ORDERS = table_id("public", "orders")
_ORDER_ITEMS = table_id("public", "order_items")
_SCALE = {_TENANTS: 5, _USERS: 100, _PRODUCTS: 20, _ORDERS: 200_000, _ORDER_ITEMS: 100}
_QUERY = "SELECT id FROM orders WHERE user_id = %(user_id)s"
_PARAMS = {"user_id": 1}
_INDEX = CandidateDDL(
    apply_sql="CREATE INDEX ix_bench_user_id ON orders (user_id)",
    revert_sql="DROP INDEX ix_bench_user_id",
)
_NOOP = CandidateDDL(apply_sql="SELECT 1", revert_sql="SELECT 1")


@pytest.fixture(scope="module")
def seeded() -> Iterator[tuple[GeneratedCredentials, SchemaIR]]:
    network = f"pgproof-net-{uuid.uuid4().hex[:12]}"
    create_network(network)
    lifecycle = DockerPostgresLifecycle()
    database = lifecycle.start(image=_POSTGRES_IMAGE, timeout_seconds=180, network=network)
    try:
        assert database.internal_credentials is not None
        config = RunnerConfig(
            build="Dockerfile", migration_command=_MIGRATION_COMMAND, timeout_seconds=300
        )
        outcome = DockerRunner().run(
            RunSpec(
                source=_DEMO_BROKEN,
                config=config,
                command=_MIGRATION_COMMAND,
                environment={"DATABASE_URL": database.internal_credentials.dsn},
                network=network,
            )
        )
        assert outcome.succeeded, outcome.stderr
        schema = PsycopgCatalogReader().introspect(database.credentials)
        with psycopg.connect(database.credentials.dsn) as conn:
            load_dataset(conn, schema, global_seed=11, scale=_SCALE, epoch=_EPOCH)
        yield database.credentials, schema
    finally:
        lifecycle.stop(database)
        remove_network(network)


@contextmanager
def _fresh(template: GeneratedCredentials) -> Iterator[GeneratedCredentials]:
    clone = f"bench_{uuid.uuid4().hex[:12]}"
    maintenance = replace(template, database="postgres")
    with psycopg.connect(maintenance.dsn, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{clone}" TEMPLATE "{template.database}"')
    try:
        yield replace(template, database=clone)
    finally:
        with psycopg.connect(maintenance.dsn, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{clone}" WITH (FORCE)')


def test_a_beneficial_index_makes_b_faster_and_a2_drifts_back(
    seeded: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, _ = seeded
    with _fresh(template) as credentials, psycopg.connect(credentials.dsn) as conn:
        result = run_experiment(conn, _QUERY, _PARAMS, candidate=_INDEX)
    assert result.control_a1 is not None
    assert result.treatment_b is not None
    assert result.drift_control_a2 is not None
    assert result.ratio is not None
    # A 200,000-row sequential scan against an index lookup on ~2,000
    # matching rows: not asserting the fixture's own hand-measured 34x-51x (a
    # different, much larger dataset), only that the direction reproduces
    # with real margin against CI timing noise.
    assert result.ratio > 1.5
    assert result.drift_detected is False


def test_a_noop_candidate_shows_no_meaningful_speedup(
    seeded: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, _ = seeded
    with _fresh(template) as credentials, psycopg.connect(credentials.dsn) as conn:
        result = run_experiment(conn, _QUERY, _PARAMS, candidate=_NOOP)
    assert result.ratio is not None
    assert 0.3 < result.ratio < 3.0


def test_an_already_cancelled_event_stops_before_the_first_arm(
    seeded: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, _ = seeded
    cancelled = Event()
    cancelled.set()
    with _fresh(template) as credentials, psycopg.connect(credentials.dsn) as conn:
        result = run_experiment(conn, _QUERY, _PARAMS, candidate=_INDEX, cancel_event=cancelled)
    assert result.cancelled is True
    assert result.control_a1 is None
    assert result.inconclusive is True


def test_an_immediate_timeout_stops_before_the_first_arm(
    seeded: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, _ = seeded
    with _fresh(template) as credentials, psycopg.connect(credentials.dsn) as conn:
        result = run_experiment(conn, _QUERY, _PARAMS, candidate=_INDEX, timeout_seconds=0.0)
    assert result.timed_out is True
    assert result.control_a1 is None
    assert result.inconclusive is True


def test_postgres_settings_are_applied_during_the_run_and_restored_after(
    seeded: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, _ = seeded
    with _fresh(template) as credentials, psycopg.connect(credentials.dsn) as conn:
        before = conn.execute("SHOW enable_seqscan").fetchone()
        assert before is not None
        assert before[0] == "on"
        result = run_experiment(
            conn, _QUERY, _PARAMS, candidate=_NOOP, postgres_settings={"enable_seqscan": "off"}
        )
        assert result.control_a1 is not None
        after = conn.execute("SHOW enable_seqscan").fetchone()
        assert after is not None
        assert after[0] == "on"

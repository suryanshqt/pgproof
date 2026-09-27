"""BE-24 accept criterion: "every probe references real generated values and
reports realized — not guessed — selectivity." Real Docker, real PostgreSQL,
BE-23's own seeder filling `fixtures/demo-broken`'s real reconciled schema,
BE-19's real parser producing the `QueryIR` under test — every number this
test checks is cross-verified against an independent raw SQL query, not
trusted from the module under test.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import psycopg
import pytest

from pgproof.adapters.parameters.extract import extract_predicates
from pgproof.adapters.parameters.probe import SelectionMethod, realize_probes
from pgproof.adapters.postgres.catalog import PsycopgCatalogReader
from pgproof.adapters.postgres.lifecycle import DockerPostgresLifecycle
from pgproof.adapters.runner.docker import (
    DockerRunner,
    create_network,
    probe_docker,
    remove_network,
)
from pgproof.adapters.seeder.load import load_dataset
from pgproof.adapters.sql.parser import parse_query
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
_SCALE = {_TENANTS: 5, _USERS: 20, _PRODUCTS: 10, _ORDERS: 200, _ORDER_ITEMS: 300}


@pytest.fixture(scope="module")
def seeded() -> Iterator[tuple[GeneratedCredentials, SchemaIR]]:
    """A single migrated-and-seeded database, reused (via `_fresh`'s
    `CREATE DATABASE ... TEMPLATE`) so every test probes its own copy without
    paying for another migration or generation run.
    """
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
            load_dataset(conn, schema, global_seed=7, scale=_SCALE, epoch=_EPOCH)
        yield database.credentials, schema
    finally:
        lifecycle.stop(database)
        remove_network(network)


@contextmanager
def _fresh(template: GeneratedCredentials) -> Iterator[GeneratedCredentials]:
    clone = f"probe_{uuid.uuid4().hex[:12]}"
    maintenance = replace(template, database="postgres")
    with psycopg.connect(maintenance.dsn, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{clone}" TEMPLATE "{template.database}"')
    try:
        yield replace(template, database=clone)
    finally:
        with psycopg.connect(maintenance.dsn, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{clone}" WITH (FORCE)')


def _independent_count(
    conn: psycopg.Connection[tuple[object, ...]], operator: str, value: object
) -> int:
    row = conn.execute(
        f"SELECT count(*) FROM orders WHERE tenant_id {operator} %s", (value,)
    ).fetchone()
    assert row is not None
    return cast("int", row[0])


def test_an_equality_probes_realized_count_matches_an_independent_query(
    seeded: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, schema = seeded
    query = parse_query("SELECT id FROM orders WHERE tenant_id = %(tenant_id)s", schema=schema)
    predicates = extract_predicates(query, schema=schema)
    assert len(predicates) == 1
    with _fresh(template) as credentials, psycopg.connect(credentials.dsn) as conn:
        probes = realize_probes(conn, predicates, reveal_values=True)
        methods = {probe.method for probe in probes}
        assert methods == {
            SelectionMethod.HIGHLY_SELECTIVE,
            SelectionMethod.MODERATE_SELECTIVITY,
            SelectionMethod.MOST_COMMON_VALUE,
        }
        for probe in probes:
            assert probe.redacted_value is not None
            value = int(probe.redacted_value)
            expected = _independent_count(conn, "=", value)
            assert probe.row_count == expected
            assert probe.total_row_count == _SCALE[_ORDERS]
            assert probe.selectivity == pytest.approx(expected / _SCALE[_ORDERS])
        # `most_common_value` is, by construction, at least as frequent as
        # every other tier for the same column.
        by_method = {probe.method: probe.row_count for probe in probes}
        assert (
            by_method[SelectionMethod.MOST_COMMON_VALUE]
            >= by_method[SelectionMethod.HIGHLY_SELECTIVE]
        )
        assert (
            by_method[SelectionMethod.MOST_COMMON_VALUE]
            >= by_method[SelectionMethod.MODERATE_SELECTIVITY]
        )


def test_probe_values_are_hashed_and_redacted_by_default(
    seeded: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, schema = seeded
    query = parse_query("SELECT id FROM orders WHERE tenant_id = %(tenant_id)s", schema=schema)
    predicates = extract_predicates(query, schema=schema)
    with _fresh(template) as credentials, psycopg.connect(credentials.dsn) as conn:
        probes = realize_probes(conn, predicates)
        assert all(probe.is_redacted for probe in probes)
        assert all(probe.redacted_value is None for probe in probes)
        assert all(probe.value_hash.startswith("sha256:") for probe in probes)


def test_a_numeric_range_probes_realized_count_matches_an_independent_query(
    seeded: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, schema = seeded
    query = parse_query("SELECT id FROM orders WHERE total_cents >= %(minimum)s", schema=schema)
    predicates = extract_predicates(query, schema=schema)
    assert len(predicates) == 1
    with _fresh(template) as credentials, psycopg.connect(credentials.dsn) as conn:
        probes = realize_probes(conn, predicates, reveal_values=True)
        methods = {probe.method for probe in probes}
        assert methods == {
            SelectionMethod.HIGHLY_SELECTIVE,
            SelectionMethod.MODERATE_SELECTIVITY,
            SelectionMethod.BROAD_SELECTIVITY,
        }
        for probe in probes:
            assert probe.redacted_value is not None
            value = float(probe.redacted_value)
            row = conn.execute(
                "SELECT count(*) FROM orders WHERE total_cents >= %s", (value,)
            ).fetchone()
            assert row is not None
            assert probe.row_count == row[0]
        # Ascending operator: the highly-selective cutoff (90th percentile)
        # returns no more rows than the broad cutoff (10th percentile).
        by_method = {probe.method: probe.row_count for probe in probes}
        assert (
            by_method[SelectionMethod.HIGHLY_SELECTIVE]
            <= by_method[SelectionMethod.MODERATE_SELECTIVITY]
        )
        assert (
            by_method[SelectionMethod.MODERATE_SELECTIVITY]
            <= by_method[SelectionMethod.BROAD_SELECTIVITY]
        )


def test_a_timestamp_range_probes_realized_count_matches_an_independent_query(
    seeded: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, schema = seeded
    query = parse_query("SELECT id FROM orders WHERE created_at >= %(since)s", schema=schema)
    predicates = extract_predicates(query, schema=schema)
    assert len(predicates) == 1
    with _fresh(template) as credentials, psycopg.connect(credentials.dsn) as conn:
        probes = realize_probes(conn, predicates, reveal_values=True)
        methods = {probe.method for probe in probes}
        assert methods == {
            SelectionMethod.RECENT_WINDOW,
            SelectionMethod.MONTHLY_WINDOW,
            SelectionMethod.FULL_WINDOW,
        }
        for probe in probes:
            assert probe.redacted_value is not None
            row = conn.execute(
                "SELECT count(*) FROM orders WHERE created_at >= %s", (probe.redacted_value,)
            ).fetchone()
            assert row is not None
            assert probe.row_count == row[0]
        # `full_window` (anchored at the observed minimum) covers at least as
        # many rows as the 7-day `recent_window`.
        by_method = {probe.method: probe.row_count for probe in probes}
        assert by_method[SelectionMethod.FULL_WINDOW] >= by_method[SelectionMethod.RECENT_WINDOW]


def test_an_unsupported_predicate_shape_yields_no_probes(
    seeded: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    _, schema = seeded
    query = parse_query("SELECT id FROM orders WHERE status LIKE %(pattern)s", schema=schema)
    assert extract_predicates(query, schema=schema) == ()

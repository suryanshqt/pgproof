"""BE-23 accept criterion: FK validity, determinism and migration-row
awareness against a real PostgreSQL holding `fixtures/demo-broken`'s real
migrated schema — not a synthetic stand-in and not a mock.

One migration run per module: the migrated database is used as a `CREATE
DATABASE ... TEMPLATE`, so every test gets its own genuinely fresh, identically
shaped database without paying for another Alembic run.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import psycopg
import pytest

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
from pgproof.domain.identifiers import column_names, table_id, table_names
from pgproof.domain.ir.schema import ConstraintKind, SchemaIR
from pgproof.ports.database import GeneratedCredentials
from pgproof.ports.runner import RunSpec

requires_docker = pytest.mark.skipif(
    not probe_docker().daemon_reachable, reason="Docker daemon not reachable"
)
pytestmark = requires_docker

_POSTGRES_IMAGE = "postgres@sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675"
_DEMO_BROKEN = Path(__file__).parents[2] / "fixtures" / "demo-broken"
# The same `postgresql://` -> `postgresql+psycopg://` rewrite
# `tests/integration/test_capture.py` documents for this fixture.
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
_SCALE = {_TENANTS: 5, _USERS: 20, _PRODUCTS: 10, _ORDERS: 40, _ORDER_ITEMS: 60}


@pytest.fixture(scope="module")
def migrated() -> Iterator[tuple[GeneratedCredentials, SchemaIR]]:
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
        yield database.credentials, PsycopgCatalogReader().introspect(database.credentials)
    finally:
        lifecycle.stop(database)
        remove_network(network)


@contextmanager
def _fresh(template: GeneratedCredentials) -> Iterator[GeneratedCredentials]:
    clone = f"seed_{uuid.uuid4().hex[:12]}"
    maintenance = replace(template, database="postgres")
    with psycopg.connect(maintenance.dsn, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{clone}" TEMPLATE "{template.database}"')
    try:
        yield replace(template, database=clone)
    finally:
        with psycopg.connect(maintenance.dsn, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{clone}" WITH (FORCE)')


def _scaled(rows_generated: Mapping[str, int]) -> dict[str, int]:
    return {table: count for table, count in rows_generated.items() if table in _SCALE}


def _count(conn: psycopg.Connection[tuple[object, ...]], table: str) -> int:
    schema_name, table_name = table_names(table)
    row = conn.execute(f'SELECT count(*) FROM "{schema_name}"."{table_name}"').fetchone()
    assert row is not None
    return cast("int", row[0])


def _orphan_count(conn: psycopg.Connection[tuple[object, ...]], schema: SchemaIR) -> int:
    total = 0
    for constraint in schema.constraints:
        if constraint.kind is not ConstraintKind.FOREIGN_KEY:
            continue
        child_schema, child_table, child_column = column_names(constraint.columns[0])
        parent_schema, parent_table, parent_column = column_names(constraint.referenced_columns[0])
        row = conn.execute(
            f'SELECT count(*) FROM "{child_schema}"."{child_table}" c '
            f'LEFT JOIN "{parent_schema}"."{parent_table}" p '
            f'ON c."{child_column}" = p."{parent_column}" '
            f'WHERE c."{child_column}" IS NOT NULL AND p."{parent_column}" IS NULL'
        ).fetchone()
        assert row is not None
        total += cast("int", row[0])
    return total


def test_load_dataset_fills_every_table_without_violating_a_foreign_key(
    migrated: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, schema = migrated
    with _fresh(template) as credentials, psycopg.connect(credentials.dsn) as conn:
        report = load_dataset(
            conn, schema, global_seed=42, scale=_SCALE, epoch=_EPOCH, generator_version=1
        )
        assert _scaled(report.rows_generated) == _SCALE
        # A table absent from `scale` is a table left alone: alembic_version
        # keeps exactly the one row the migration wrote.
        assert report.rows_generated[table_id("public", "alembic_version")] == 0
        assert {table: _count(conn, table) for table in _SCALE} == _SCALE
        assert _orphan_count(conn, schema) == 0
        # demo-broken's planted TENANT-001 defect: orders.tenant_id has no
        # physical foreign key, so no tier-2 fact constrains it.
        strategies = {a.column: a.strategy for a in report.assumptions}
        assert strategies["public.orders.tenant_id"] == "uniform_fallback"
        assert strategies["public.orders.status"] == "check_recognized_set"
        assert strategies["public.orders.user_id"] == "foreign_key"
        assert strategies["public.tenants.slug"] == "unique_sequential_text"
        assert strategies["public.users.email"] == "email_heuristic"
        assert strategies["public.orders.id"] == "database_default"


def test_sequences_are_advanced_past_every_generated_identifier(
    migrated: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, schema = migrated
    with _fresh(template) as credentials, psycopg.connect(credentials.dsn) as conn:
        load_dataset(conn, schema, global_seed=42, scale=_SCALE, epoch=_EPOCH)
        conn.execute(
            "INSERT INTO tenants (slug, name, created_at) VALUES ('after', 'after', now())"
        )
        conn.commit()
        assert _count(conn, _TENANTS) == _SCALE[_TENANTS] + 1


def test_the_same_seed_fills_two_fresh_databases_identically(
    migrated: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, schema = migrated
    query = "SELECT id, user_id, status, total_cents FROM orders ORDER BY id"
    observed = []
    for _ in range(2):
        with _fresh(template) as credentials, psycopg.connect(credentials.dsn) as conn:
            report = load_dataset(conn, schema, global_seed=99, scale=_SCALE, epoch=_EPOCH)
            assert _scaled(report.rows_generated) == _SCALE
            observed.append(conn.execute(query).fetchall())
    assert observed[0] == observed[1]
    assert len(observed[0]) == _SCALE[_ORDERS]


def test_a_second_load_at_the_same_scale_inserts_nothing_more(
    migrated: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, schema = migrated
    with _fresh(template) as credentials, psycopg.connect(credentials.dsn) as conn:
        load_dataset(conn, schema, global_seed=42, scale=_SCALE, epoch=_EPOCH)
        second = load_dataset(conn, schema, global_seed=42, scale=_SCALE, epoch=_EPOCH)
        assert _scaled(second.rows_generated) == dict.fromkeys(_SCALE, 0)
        assert {table: _count(conn, table) for table in _SCALE} == _SCALE

        grown = {**_SCALE, _TENANTS: _SCALE[_TENANTS] + 3}
        third = load_dataset(conn, schema, global_seed=42, scale=grown, epoch=_EPOCH)
        assert third.rows_generated[_TENANTS] == 3
        assert _count(conn, _TENANTS) == grown[_TENANTS]
        assert _orphan_count(conn, schema) == 0


def test_a_nullable_self_referential_cycle_is_created_then_filled(
    migrated: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    template, _ = migrated
    nodes = table_id("public", "nodes")
    with _fresh(template) as credentials:
        with psycopg.connect(credentials.dsn, autocommit=True) as setup:
            setup.execute(
                "CREATE TABLE nodes (id serial PRIMARY KEY, parent_id integer REFERENCES nodes(id))"
            )
        schema = PsycopgCatalogReader().introspect(credentials)
        with psycopg.connect(credentials.dsn) as conn:
            report = load_dataset(conn, schema, global_seed=5, scale={nodes: 12}, epoch=_EPOCH)
            assert report.rows_generated[nodes] == 12
            row = conn.execute(
                "SELECT count(*) FROM nodes n LEFT JOIN nodes p ON n.parent_id = p.id "
                "WHERE n.parent_id IS NULL OR p.id IS NULL"
            ).fetchone()
            assert row is not None
            assert row[0] == 0

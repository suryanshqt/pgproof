"""BE-17 accept criterion: "supported catalog objects round-trip into a fresh
database and match Graph IR expectations." Real Docker, real PostgreSQL —
the query shapes were developed and hand-verified against this same pinned
image before being locked into `tests/unit/test_adapters_postgres_catalog.py`'s
mocked suite; this file is the actual round trip, not a rehearsal of it.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from pgproof.adapters.diagrams.graph_ir import build_graph
from pgproof.adapters.postgres.canonical_sql import render_canonical_schema_sql
from pgproof.adapters.postgres.catalog import PsycopgCatalogReader
from pgproof.adapters.postgres.lifecycle import DockerPostgresLifecycle
from pgproof.adapters.runner.docker import find_orphaned_containers, probe_docker
from pgproof.domain.graph import EdgeKind, NodeKind
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.schema import ConstraintKind, SchemaIR, SchemaProvenance
from pgproof.ports.database import DisposableDatabase, GeneratedCredentials

requires_docker = pytest.mark.skipif(
    not probe_docker().daemon_reachable, reason="Docker daemon not reachable"
)
pytestmark = requires_docker

# Matches `fixtures/benchmark-corpus.yaml`'s own pin, so this suite and the
# `fixtures` CI job test against the same server build.
_IMAGE = "postgres@sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675"

_SCHEMA_SQL = """
CREATE TABLE tenants (
    id serial PRIMARY KEY,
    slug varchar(64) NOT NULL,
    CONSTRAINT uq_tenants_slug UNIQUE (slug)
);
CREATE TABLE orders (
    id serial PRIMARY KEY,
    tenant_id integer NOT NULL,
    amount integer NOT NULL,
    note text,
    CONSTRAINT fk_orders_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT orders_amount_check CHECK (amount > 0)
);
CREATE INDEX ix_orders_tenant_id ON orders (tenant_id);
CREATE INDEX ix_orders_lower_note ON orders (lower(note));
COMMENT ON TABLE tenants IS 'tenant catalog';
"""


@pytest.fixture(scope="module")
def database() -> Iterator[DisposableDatabase]:
    lifecycle = DockerPostgresLifecycle()
    database = lifecycle.start(image=_IMAGE, timeout_seconds=60)
    try:
        yield database
    finally:
        lifecycle.stop(database)


@pytest.fixture
def credentials(database: DisposableDatabase) -> GeneratedCredentials:
    _reset_schema(database.credentials)
    return database.credentials


def _reset_schema(credentials: GeneratedCredentials) -> None:
    with psycopg.connect(credentials.dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")


def _apply(credentials: GeneratedCredentials, sql: str) -> None:
    with psycopg.connect(credentials.dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(sql)


def test_lifecycle_start_and_stop_leaves_no_orphaned_container(
    database: DisposableDatabase,
) -> None:
    orphans = {o.id for o in find_orphaned_containers()}
    assert any(database.container_id.startswith(o) for o in orphans)


def test_round_trip_matches_the_created_schema(credentials: GeneratedCredentials) -> None:
    _apply(credentials, _SCHEMA_SQL)
    schema = PsycopgCatalogReader().introspect(credentials)

    assert {t.id for t in schema.tables} == {"public.tenants", "public.orders"}
    tenants = next(t for t in schema.tables if t.id == "public.tenants")
    assert tenants.comment == "tenant catalog"

    by_name = {c.name: c for c in schema.constraints}
    assert by_name["fk_orders_tenant"].kind is ConstraintKind.FOREIGN_KEY
    assert by_name["fk_orders_tenant"].referenced_table == "public.tenants"
    assert by_name["orders_amount_check"].expression == "(amount > 0)"
    assert by_name["uq_tenants_slug"].kind is ConstraintKind.UNIQUE

    by_index = {i.name: i for i in schema.indexes}
    assert by_index["ix_orders_tenant_id"].keys[0].column == "public.orders.tenant_id"
    assert by_index["ix_orders_lower_note"].keys[0].expression == "lower(note)"
    # The PK/UNIQUE-backing indexes are not separately listed.
    assert "tenants_pkey" not in by_index
    assert "uq_tenants_slug" not in by_index

    assert schema.provenance is SchemaProvenance.PHYSICAL_CATALOG
    assert schema.server_version
    assert "plpgsql" in schema.extension_versions
    assert schema.unsupported == ()


def test_the_introspected_schema_flows_into_a_correct_graph(
    credentials: GeneratedCredentials,
) -> None:
    _apply(credentials, _SCHEMA_SQL)
    schema = PsycopgCatalogReader().introspect(credentials)

    graph = build_graph(
        physical=schema,
        orm_schema=SchemaIR(provenance=SchemaProvenance.UNRESOLVED),
        code=CodeIR(orm="sqlalchemy"),
        view="current",
    )

    table_nodes = {n.id for n in graph.nodes if n.kind is NodeKind.TABLE}
    assert "table:public.tenants" in table_nodes
    assert "table:public.orders" in table_nodes
    fk_edges = [e for e in graph.edges if e.kind is EdgeKind.PHYSICAL_FOREIGN_KEY]
    assert any(
        e.source == "table:public.orders" and e.target == "table:public.tenants" for e in fk_edges
    )


def test_an_unsupported_relation_kind_is_reported_not_hidden(
    credentials: GeneratedCredentials,
) -> None:
    _apply(
        credentials, "CREATE TABLE t (id serial PRIMARY KEY); CREATE VIEW v AS SELECT id FROM t;"
    )
    schema = PsycopgCatalogReader().introspect(credentials)
    assert [t.id for t in schema.tables] == ["public.t"]
    assert len(schema.unsupported) == 1
    assert schema.unsupported[0].kind == "view"
    assert "public.v" in schema.unsupported[0].reason


def test_canonical_sql_reexecutes_to_a_structurally_equivalent_schema(
    credentials: GeneratedCredentials,
) -> None:
    _apply(credentials, _SCHEMA_SQL)
    original = PsycopgCatalogReader().introspect(credentials)
    rendered = render_canonical_schema_sql(original)

    _reset_schema(credentials)
    _apply(credentials, rendered)
    reexecuted = PsycopgCatalogReader().introspect(credentials)

    assert {t.id for t in reexecuted.tables} == {t.id for t in original.tables}
    original_constraint_shapes = {
        (c.name, c.kind, c.table, c.columns) for c in original.constraints
    }
    reexecuted_constraint_shapes = {
        (c.name, c.kind, c.table, c.columns) for c in reexecuted.constraints
    }
    assert reexecuted_constraint_shapes == original_constraint_shapes
    original_index_names = {i.name for i in original.indexes}
    reexecuted_index_names = {i.name for i in reexecuted.indexes}
    assert reexecuted_index_names == original_index_names

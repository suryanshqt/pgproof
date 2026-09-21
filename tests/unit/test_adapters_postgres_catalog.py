"""`PsycopgCatalogReader` against a scripted fake connection.

The query shapes themselves (composite-key ordering, expression-vs-column
index keys, CHECK-expression stripping) were developed and hand-verified
against a real disposable PostgreSQL instance; this file locks in the
resulting `SchemaIR` shape and exercises branches a real single-schema round
trip wouldn't naturally hit (an unsupported relation kind, a DESC index key).
`tests/integration/test_postgres_catalog.py` is the real-daemon round trip.
"""

from __future__ import annotations

from collections.abc import Callable

import psycopg
import pytest
from typing_extensions import override

from pgproof.adapters.postgres.catalog import PsycopgCatalogReader
from pgproof.domain.ir.schema import ConstraintKind, ReferentialAction, SortDirection
from pgproof.ports.database import GeneratedCredentials

Responder = Callable[[str, tuple[object, ...] | None], list[tuple[object, ...]]]


class _FakeCursor:
    def __init__(self, responder: Responder) -> None:
        self._responder = responder
        self._rows: list[tuple[object, ...]] = []
        self.queries: list[tuple[str, tuple[object, ...] | None]] = []

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.queries.append((sql, params))
        self._rows = self._responder(sql, params)

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _responder(sql: str, params: tuple[object, ...] | None) -> list[tuple[object, ...]]:
    if "obj_description(c.oid, 'pg_class')" in sql:
        return [
            ("public", "orders", "r", "order records"),
            ("public", "orders_view", "v", None),
        ]
    if "pg_attrdef ad" in sql:
        return [
            ("id", "integer", False, None, False, False),
            ("tenant_id", "integer", False, None, False, False),
            ("note", "text", True, None, False, False),
        ]
    if "pg_get_constraintdef(con.oid)" in sql:
        return [
            ("orders_pkey", "p", "orders", None, None, " ", " ", "PRIMARY KEY (id)", ["id"], None),
            (
                "fk_orders_tenant",
                "f",
                "orders",
                "public",
                "tenants",
                "r",
                "c",
                "FOREIGN KEY (tenant_id) REFERENCES tenants(id)",
                ["tenant_id"],
                ["id"],
            ),
            (
                "orders_note_check",
                "c",
                "orders",
                None,
                None,
                " ",
                " ",
                "CHECK ((note IS NOT NULL))",
                ["note"],
                None,
            ),
            # A constraint-trigger pseudo-row (contype 't'): not a kind this
            # adapter models; must be skipped, not raise or appear below.
            ("orders_trigger", "t", "orders", None, None, " ", " ", "TRIGGER", None, None),
        ]
    if "ix.indnkeyatts" in sql:
        return [
            ("ix_orders_tenant_id", "btree", False, None, 501, 1, "0"),
            ("ix_orders_lower_note", "btree", False, None, 502, 1, "1"),
        ]
    if "pg_get_indexdef(%s, %s, true)" in sql:
        assert params is not None
        indexrelid, _position = params
        return [("tenant_id",)] if indexrelid == 501 else [("lower(note)",)]
    if "FROM pg_extension" in sql:
        return [("plpgsql", "1.0")]
    if sql == "SHOW server_version":
        return [("17.11 (Debian 17.11-1.pgdg13+2)",)]
    if "FROM pg_settings" in sql:
        return [("max_connections", "100", None), ("shared_buffers", "16384", "8kB")]
    if "FROM alembic_version" in sql:
        return [("6a912ef4c1b8",)]
    raise AssertionError(f"unexpected query: {sql}")


@pytest.fixture
def credentials() -> GeneratedCredentials:
    return GeneratedCredentials(
        host="127.0.0.1", port=1, user="pgproof", password="x", database="pgproof"
    )


def test_introspect_builds_the_expected_schema_ir(
    monkeypatch: pytest.MonkeyPatch, credentials: GeneratedCredentials
) -> None:
    cursor = _FakeCursor(_responder)
    monkeypatch.setattr(
        "pgproof.adapters.postgres.catalog.psycopg.connect",
        lambda _dsn, **_kwargs: _FakeConnection(cursor),
    )
    schema = PsycopgCatalogReader().introspect(credentials)

    assert [t.id for t in schema.tables] == ["public.orders"]
    table = schema.tables[0]
    assert table.comment == "order records"
    assert [c.name for c in table.columns] == ["id", "tenant_id", "note"]
    assert table.columns[2].nullable is True

    by_name = {c.name: c for c in schema.constraints}
    assert "orders_trigger" not in by_name
    assert by_name["orders_pkey"].kind is ConstraintKind.PRIMARY_KEY
    fk = by_name["fk_orders_tenant"]
    assert fk.kind is ConstraintKind.FOREIGN_KEY
    assert fk.referenced_table == "public.tenants"
    assert fk.referenced_columns == ("public.tenants.id",)
    assert fk.on_delete is ReferentialAction.CASCADE
    assert fk.on_update is ReferentialAction.RESTRICT
    assert by_name["orders_note_check"].expression == "(note IS NOT NULL)"

    by_index_name = {i.name: i for i in schema.indexes}
    plain = by_index_name["ix_orders_tenant_id"]
    assert plain.keys[0].column == "public.orders.tenant_id"
    assert plain.keys[0].expression is None
    assert plain.keys[0].direction is SortDirection.ASC

    expr = by_index_name["ix_orders_lower_note"]
    assert expr.keys[0].column is None
    assert expr.keys[0].expression == "lower(note)"
    assert expr.keys[0].direction is SortDirection.DESC

    assert len(schema.unsupported) == 1
    assert schema.unsupported[0].kind == "view"
    assert "orders_view" in schema.unsupported[0].reason

    assert schema.extension_versions == {"plpgsql": "1.0"}
    assert schema.extensions == ("plpgsql",)
    assert schema.server_version == "17.11 (Debian 17.11-1.pgdg13+2)"
    assert schema.settings == {"max_connections": "100", "shared_buffers": "16384 8kB"}
    assert schema.migration_head == "6a912ef4c1b8"


def test_a_missing_alembic_version_table_leaves_migration_head_none(
    monkeypatch: pytest.MonkeyPatch, credentials: GeneratedCredentials
) -> None:
    class _RaisingCursor(_FakeCursor):
        @override
        def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
            if "FROM alembic_version" in sql:
                raise psycopg.errors.UndefinedTable("relation does not exist")
            super().execute(sql, params)

    cursor = _RaisingCursor(_responder)
    monkeypatch.setattr(
        "pgproof.adapters.postgres.catalog.psycopg.connect",
        lambda _dsn, **_kwargs: _FakeConnection(cursor),
    )
    schema = PsycopgCatalogReader().introspect(credentials)
    assert schema.migration_head is None

"""Live catalog introspection. `docs/TECHNICAL_DESIGN.md:218-231`.

Supported: tables, columns, primary/foreign/unique/check constraints,
standalone indexes (btree/hash/gist/gin/spgist/brin, including expression and
partial indexes), extension name+version, server version, and a small named
set of settings (`_CAPTURED_SETTINGS` below). Every relation kind other than
an ordinary table (view, materialized view, sequence, partitioned table,
foreign table) is recorded as an `UnsupportedConstruct` rather than silently
dropped — `docs/PRODUCT_SPEC.md` section 7 forbids hiding unsupported input.
Functions, procedures, triggers, and row-level security policies are outside
this PR's scope entirely: `SchemaIR` has no fields for them yet.

An index backing a PRIMARY KEY or UNIQUE constraint is not separately
represented in `indexes`, only as a `ConstraintIR` — matching how
`adapters.repository.alembic_static` only ever records an index for an
explicit `op.create_index`, never Postgres's own implicit backing index for
a constraint, so a live and a statically-reconstructed schema describe the
same thing the same way.

`SchemaIR.migration_head` (BE-18) is read from the live `alembic_version`
table — the same field `adapters.repository.alembic_static` already sets
from a static replay, so a caller checks "did the migration reach the
expected head" with a plain equality, not a new comparison vocabulary.
"""

from __future__ import annotations

from typing import Final, cast

import psycopg

from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.schema import (
    ColumnIR,
    ConstraintIR,
    ConstraintKind,
    IndexIR,
    IndexKeyIR,
    IndexMethod,
    ReferentialAction,
    SchemaIR,
    SchemaProvenance,
    SortDirection,
    TableIR,
    UnsupportedConstruct,
)
from pgproof.ports.database import GeneratedCredentials

_SYSTEM_SCHEMAS: Final = ("pg_catalog", "information_schema", "pg_toast")
_RELKIND_LABELS: Final[dict[str, str]] = {
    "v": "view",
    "m": "materialized_view",
    "f": "foreign_table",
    "p": "partitioned_table",
    "c": "composite_type",
}
_CONSTRAINT_KIND: Final[dict[str, ConstraintKind]] = {
    "p": ConstraintKind.PRIMARY_KEY,
    "f": ConstraintKind.FOREIGN_KEY,
    "u": ConstraintKind.UNIQUE,
    "c": ConstraintKind.CHECK,
    "x": ConstraintKind.EXCLUSION,
}
_REFERENTIAL_ACTION: Final[dict[str, ReferentialAction]] = {
    "a": ReferentialAction.NO_ACTION,
    "r": ReferentialAction.RESTRICT,
    "c": ReferentialAction.CASCADE,
    "n": ReferentialAction.SET_NULL,
    "d": ReferentialAction.SET_DEFAULT,
}
_INDEX_METHOD: Final[dict[str, IndexMethod]] = {
    "btree": IndexMethod.BTREE,
    "hash": IndexMethod.HASH,
    "gist": IndexMethod.GIST,
    "gin": IndexMethod.GIN,
    "spgist": IndexMethod.SPGIST,
    "brin": IndexMethod.BRIN,
}
# A fixed, named set of GUCs relevant to design review, not an exhaustive
# `pg_settings` dump — `docs/PR_ROADMAP.md`'s "version/settings capture" asks
# for capture, not for everything Postgres can report.
_CAPTURED_SETTINGS: Final = (
    "max_connections",
    "shared_buffers",
    "work_mem",
    "effective_cache_size",
    "wal_level",
    "max_wal_size",
)

_VISIBLE_RELKINDS: Final = ("r", "v", "m", "f", "p", "c")

_TABLES_SQL = """
    SELECT n.nspname, c.relname, c.relkind, obj_description(c.oid, 'pg_class')
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname != ALL(%s)
      AND c.relkind = ANY(%s)
    ORDER BY n.nspname, c.relname
"""

_COLUMNS_SQL = """
    SELECT a.attname,
           pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
           NOT a.attnotnull AS nullable,
           pg_get_expr(ad.adbin, ad.adrelid) AS default_expression,
           a.attidentity <> '' AS is_identity,
           a.attgenerated <> '' AS is_generated
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
    WHERE c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
      AND n.nspname = %s AND c.relname = %s
    ORDER BY a.attnum
"""

_CONSTRAINTS_SQL = """
    SELECT con.conname, con.contype, c.relname,
           fn.nspname, fc.relname,
           con.confupdtype, con.confdeltype,
           pg_get_constraintdef(con.oid) AS definition,
           (SELECT array_agg(a.attname ORDER BY k.ord)
            FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
            JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
           ) AS columns,
           (SELECT array_agg(a.attname ORDER BY k.ord)
            FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
            JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum
           ) AS ref_columns
    FROM pg_constraint con
    JOIN pg_class c ON c.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_class fc ON fc.oid = con.confrelid
    LEFT JOIN pg_namespace fn ON fn.oid = fc.relnamespace
    WHERE n.nspname = %s AND c.relname = %s
    ORDER BY con.conname
"""

_INDEXES_SQL = """
    SELECT ic.relname, am.amname, ix.indisunique,
           pg_get_expr(ix.indpred, ix.indrelid) AS predicate,
           ix.indexrelid, ix.indnkeyatts, ix.indoption
    FROM pg_index ix
    JOIN pg_class ic ON ic.oid = ix.indexrelid
    JOIN pg_class tc ON tc.oid = ix.indrelid
    JOIN pg_namespace n ON n.oid = tc.relnamespace
    JOIN pg_am am ON am.oid = ic.relam
    WHERE n.nspname = %s AND tc.relname = %s
      AND NOT ix.indisprimary
      AND ix.indexrelid NOT IN (SELECT conindid FROM pg_constraint WHERE contype = 'u')
    ORDER BY ic.relname
"""

_INDEX_KEY_SQL = "SELECT pg_get_indexdef(%s, %s, true)"


def _strip_check_expression(definition: str) -> str:
    return definition.removeprefix("CHECK (").removesuffix(")")


def _read_migration_head(credentials: GeneratedCredentials) -> str | None:
    """`None` when the target isn't Alembic-managed at all (no `alembic_version`
    table) rather than an error — this is a fact about the database, not a
    failure of introspection. Its own `autocommit` connection, separate from
    the main introspection one: a missing table would otherwise abort that
    connection's transaction and fail every query issued after it.
    """
    try:
        with psycopg.connect(credentials.dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
            row = cur.fetchone()
    except psycopg.errors.UndefinedTable:
        return None
    return cast("str", row[0]) if row is not None else None


class PsycopgCatalogReader:
    def introspect(self, credentials: GeneratedCredentials) -> SchemaIR:
        with psycopg.connect(credentials.dsn) as conn, conn.cursor() as cur:
            relations = self._relations(cur)
            tables: list[TableIR] = []
            constraints: list[ConstraintIR] = []
            indexes: list[IndexIR] = []
            unsupported: list[UnsupportedConstruct] = []
            for schema_name, table_name, relkind, comment in relations:
                if relkind != "r":
                    unsupported.append(
                        UnsupportedConstruct(
                            kind=_RELKIND_LABELS.get(relkind, relkind),
                            reason=f"{schema_name}.{table_name}: not a supported relation kind",
                        )
                    )
                    continue
                identity = table_id(schema_name, table_name)
                tables.append(
                    TableIR(
                        id=identity,
                        schema_name=schema_name,
                        name=table_name,
                        columns=self._columns(cur, schema_name, table_name, identity),
                        provenance=SchemaProvenance.PHYSICAL_CATALOG,
                        comment=comment,
                    )
                )
                constraints.extend(self._constraints(cur, schema_name, table_name, identity))
                indexes.extend(self._indexes(cur, schema_name, table_name, identity))

            extension_versions = self._extensions(cur)
            cur.execute("SHOW server_version")
            (server_version,) = cast("tuple[str]", cur.fetchone())
            settings = self._settings(cur)

        migration_head = _read_migration_head(credentials)

        return SchemaIR(
            provenance=SchemaProvenance.PHYSICAL_CATALOG,
            tables=tuple(tables),
            constraints=tuple(constraints),
            indexes=tuple(indexes),
            extensions=tuple(sorted(extension_versions)),
            extension_versions=extension_versions,
            migration_head=migration_head,
            server_version=server_version,
            settings=settings,
            unsupported=tuple(unsupported),
        )

    def _relations(
        self, cur: psycopg.Cursor[tuple[object, ...]]
    ) -> list[tuple[str, str, str, str | None]]:
        cur.execute(_TABLES_SQL, (list(_SYSTEM_SCHEMAS), list(_VISIBLE_RELKINDS)))
        return cast("list[tuple[str, str, str, str | None]]", cur.fetchall())

    def _columns(
        self,
        cur: psycopg.Cursor[tuple[object, ...]],
        schema_name: str,
        table_name: str,
        table_identity: str,
    ) -> tuple[ColumnIR, ...]:
        cur.execute(_COLUMNS_SQL, (schema_name, table_name))
        rows = cast("list[tuple[str, str, bool, str | None, bool, bool]]", cur.fetchall())
        return tuple(
            ColumnIR(
                id=column_id(table_identity, row[0]),
                name=row[0],
                data_type=row[1],
                nullable=row[2],
                default_expression=row[3],
                is_identity=row[4],
                is_generated=row[5],
                provenance=SchemaProvenance.PHYSICAL_CATALOG,
            )
            for row in rows
        )

    def _constraints(
        self,
        cur: psycopg.Cursor[tuple[object, ...]],
        schema_name: str,
        table_name: str,
        table_identity: str,
    ) -> list[ConstraintIR]:
        cur.execute(_CONSTRAINTS_SQL, (schema_name, table_name))
        rows = cast(
            "list[tuple[str, str, str, str | None, str | None, str, str, str, "
            "list[str] | None, list[str] | None]]",
            cur.fetchall(),
        )
        result = []
        for (
            name,
            contype,
            _table,
            ref_schema,
            ref_table,
            confupdtype,
            confdeltype,
            definition,
            columns,
            ref_columns,
        ) in rows:
            kind = _CONSTRAINT_KIND.get(contype)
            if kind is None:
                continue
            referenced_table = table_id(ref_schema, ref_table) if ref_schema and ref_table else None
            result.append(
                ConstraintIR(
                    name=name,
                    kind=kind,
                    table=table_identity,
                    columns=tuple(column_id(table_identity, c) for c in (columns or ())),
                    referenced_table=referenced_table,
                    referenced_columns=tuple(
                        column_id(referenced_table, c) for c in (ref_columns or ())
                    )
                    if referenced_table
                    else (),
                    on_delete=_REFERENTIAL_ACTION.get(confdeltype)
                    if kind is ConstraintKind.FOREIGN_KEY
                    else None,
                    on_update=_REFERENTIAL_ACTION.get(confupdtype)
                    if kind is ConstraintKind.FOREIGN_KEY
                    else None,
                    expression=_strip_check_expression(definition)
                    if kind is ConstraintKind.CHECK
                    else None,
                    provenance=SchemaProvenance.PHYSICAL_CATALOG,
                )
            )
        return result

    def _indexes(
        self,
        cur: psycopg.Cursor[tuple[object, ...]],
        schema_name: str,
        table_name: str,
        table_identity: str,
    ) -> list[IndexIR]:
        cur.execute(_INDEXES_SQL, (schema_name, table_name))
        rows = cast("list[tuple[str, str, bool, str | None, int, int, str]]", cur.fetchall())
        known_columns = self._column_names(cur, schema_name, table_name)
        indexes = []
        for name, amname, is_unique, predicate, indexrelid, nkeyatts, indoption in rows:
            options = [int(part) for part in indoption.split()]
            keys = []
            for position in range(1, nkeyatts + 1):
                cur.execute(_INDEX_KEY_SQL, (indexrelid, position))
                (key_text,) = cast("tuple[str]", cur.fetchone())
                direction = SortDirection.DESC if options[position - 1] & 1 else SortDirection.ASC
                if key_text in known_columns:
                    keys.append(
                        IndexKeyIR(column=column_id(table_identity, key_text), direction=direction)
                    )
                else:
                    keys.append(IndexKeyIR(expression=key_text, direction=direction))
            indexes.append(
                IndexIR(
                    name=name,
                    table=table_identity,
                    method=_INDEX_METHOD.get(amname, IndexMethod.BTREE),
                    keys=tuple(keys),
                    is_unique=is_unique,
                    predicate=predicate,
                    provenance=SchemaProvenance.PHYSICAL_CATALOG,
                )
            )
        return indexes

    def _column_names(
        self, cur: psycopg.Cursor[tuple[object, ...]], schema_name: str, table_name: str
    ) -> frozenset[str]:
        cur.execute(_COLUMNS_SQL, (schema_name, table_name))
        rows = cast("list[tuple[str, ...]]", cur.fetchall())
        return frozenset(row[0] for row in rows)

    def _extensions(self, cur: psycopg.Cursor[tuple[object, ...]]) -> dict[str, str]:
        cur.execute("SELECT extname, extversion FROM pg_extension ORDER BY extname")
        return dict(cast("list[tuple[str, str]]", cur.fetchall()))

    def _settings(self, cur: psycopg.Cursor[tuple[object, ...]]) -> dict[str, str]:
        cur.execute(
            "SELECT name, setting, unit FROM pg_settings WHERE name = ANY(%s)",
            (list(_CAPTURED_SETTINGS),),
        )
        rows = cast("list[tuple[str, str, str | None]]", cur.fetchall())
        return {name: f"{setting} {unit}" if unit else setting for name, setting, unit in rows}

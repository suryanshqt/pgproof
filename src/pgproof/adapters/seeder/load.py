"""Deterministic dataset loading. `docs/TECHNICAL_DESIGN.md` section 18.

The psycopg half of the generator: `adapters.seeder.plan` decides every value,
this module reads the facts that decision needs from the live database
(existing row counts, existing unique values, parent key pools), COPYs the
result, synchronizes sequences and runs `ANALYZE`.

Rows a data migration already inserted are preserved: the requested scale is a
target total, not a batch size, and existing unique values are excluded from
the generated ones.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import psycopg
from psycopg import sql

from pgproof.adapters.seeder.plan import (
    ColumnAssumption,
    build_table_order,
    component_stream,
    generate_table_rows,
    unique_value_columns,
)
from pgproof.domain.identifiers import ColumnId, TableId, column_names, table_names
from pgproof.domain.ir.schema import ConstraintKind, SchemaIR, TableIR, UnsupportedConstruct


@dataclass(frozen=True)
class GenerationReport:
    rows_generated: dict[TableId, int]
    assumptions: tuple[ColumnAssumption, ...]
    unsupported: tuple[UnsupportedConstruct, ...]


def _relation(table: TableId) -> sql.Identifier:
    schema_name, table_name = table_names(table)
    return sql.Identifier(schema_name, table_name)


def _existing_count(cur: psycopg.Cursor[tuple[object, ...]], table: TableId) -> int:
    cur.execute(sql.SQL("SELECT count(*) FROM {}").format(_relation(table)))
    return cast("int", cast("tuple[object, ...]", cur.fetchone())[0])


def _column_values(cur: psycopg.Cursor[tuple[object, ...]], column: ColumnId) -> list[object]:
    schema_name, table_name, column_name = column_names(column)
    cur.execute(
        sql.SQL("SELECT {} FROM {} WHERE {} IS NOT NULL").format(
            sql.Identifier(column_name),
            sql.Identifier(schema_name, table_name),
            sql.Identifier(column_name),
        )
    )
    return [row[0] for row in cur.fetchall()]


def _parent_pools(
    cur: psycopg.Cursor[tuple[object, ...]], table: TableIR, schema: SchemaIR
) -> dict[TableId, list[object]]:
    pools: dict[TableId, list[object]] = {}
    for constraint in schema.constraints:
        if constraint.table != table.id or constraint.kind is not ConstraintKind.FOREIGN_KEY:
            continue
        if constraint.referenced_table is None or len(constraint.referenced_columns) != 1:
            continue
        pools[constraint.referenced_table] = _column_values(cur, constraint.referenced_columns[0])
    return pools


def _copy_rows(
    cur: psycopg.Cursor[tuple[object, ...]],
    table: TableIR,
    rows: Sequence[Mapping[str, object]],
) -> None:
    columns = [column.name for column in table.columns if column.name in rows[0]]
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        _relation(table.id),
        sql.SQL(", ").join(sql.Identifier(name) for name in columns),
    )
    with cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(tuple(row[name] for name in columns))


def _synchronize_sequences(cur: psycopg.Cursor[tuple[object, ...]], schema: SchemaIR) -> None:
    for table in schema.tables:
        for column in table.columns:
            if "nextval(" not in (column.default_expression or ""):
                continue
            relation = _relation(table.id)
            cur.execute(
                "SELECT pg_get_serial_sequence(%s, %s)",
                (relation.as_string(cur), column.name),
            )
            row = cur.fetchone()
            if row is None or row[0] is None:
                continue
            cur.execute(
                sql.SQL("SELECT setval(%s, coalesce((SELECT max({}) FROM {}), 1))").format(
                    sql.Identifier(column.name), relation
                ),
                (row[0],),
            )


def _fill_deferred_foreign_keys(
    cur: psycopg.Cursor[tuple[object, ...]],
    schema: SchemaIR,
    deferred: Sequence[ColumnId],
    *,
    global_seed: int,
    generator_version: int,
) -> None:
    """Create-then-fill, second pass: the cycle's tables now hold real rows, so
    the FK columns held NULL on the COPY pass get their values here, from the
    same per-column stream they would have used had they never been deferred.
    """
    by_column = {
        constraint.columns[0]: constraint
        for constraint in schema.constraints
        if constraint.kind is ConstraintKind.FOREIGN_KEY and len(constraint.columns) == 1
    }
    for column in deferred:
        constraint = by_column.get(column)
        if constraint is None or len(constraint.referenced_columns) != 1:
            continue
        pool = _column_values(cur, constraint.referenced_columns[0])
        if not pool:
            continue
        stream = component_stream(global_seed, constraint.table, column, generator_version)
        relation = _relation(constraint.table)
        _, _, column_name = column_names(column)
        cur.execute(sql.SQL("SELECT ctid FROM {} ORDER BY ctid").format(relation))
        # ponytail: one UPDATE per row. Upgrade path: a single UPDATE ... FROM
        # (VALUES ...) once a cycle table is ever loaded at benchmark scale.
        for (ctid,) in cast("list[tuple[object]]", cur.fetchall()):
            cur.execute(
                sql.SQL("UPDATE {} SET {} = %s WHERE ctid = %s").format(
                    relation, sql.Identifier(column_name)
                ),
                (stream.choice(pool), ctid),
            )


def load_dataset(
    conn: psycopg.Connection[tuple[object, ...]],
    schema: SchemaIR,
    *,
    global_seed: int,
    scale: Mapping[TableId, int],
    epoch: datetime,
    generator_version: int = 1,
) -> GenerationReport:
    """Generate and COPY every table in FK dependency order.

    `scale` is a target total per table, so a second call against a database
    this function already filled generates only the shortfall.
    """
    order = build_table_order(schema)
    deferred = frozenset(order.deferred_columns)
    tables = {table.id: table for table in schema.tables}

    rows_generated: dict[TableId, int] = {}
    assumptions: list[ColumnAssumption] = []
    unsupported: list[UnsupportedConstruct] = [*order.unsupported]

    with conn.cursor() as cur:
        for table_id in order.order:
            table = tables[table_id]
            row_count = max(0, scale.get(table_id, 0) - _existing_count(cur, table_id))
            unique_columns, _ = unique_value_columns(table, schema)
            existing = {column: frozenset(_column_values(cur, column)) for column in unique_columns}
            result = generate_table_rows(
                table,
                schema,
                global_seed=global_seed,
                generator_version=generator_version,
                epoch=epoch,
                row_count=row_count,
                parent_key_pools=_parent_pools(cur, table, schema),
                existing_unique_values=existing,
                defer_columns=deferred,
            )
            assumptions.extend(result.assumptions)
            unsupported.extend(result.unsupported)
            rows_generated[table_id] = len(result.rows)
            if result.rows:
                _copy_rows(cur, table, result.rows)
            cur.execute(sql.SQL("ANALYZE {}").format(_relation(table_id)))

        _synchronize_sequences(cur, schema)
        _fill_deferred_foreign_keys(
            cur,
            schema,
            order.deferred_columns,
            global_seed=global_seed,
            generator_version=generator_version,
        )
    conn.commit()

    return GenerationReport(
        rows_generated=rows_generated,
        assumptions=tuple(assumptions),
        unsupported=tuple(unsupported),
    )

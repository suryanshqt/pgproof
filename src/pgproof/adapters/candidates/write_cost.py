"""Index write-cost guard. `docs/TECHNICAL_DESIGN.md` section 22: insert
batch latency, update of an indexed column, update of an unrelated column,
WAL, and index build time/size — the write-side half of a candidate's
trade-off, kept separate from `adapters.benchmark`'s read-side
`ExperimentResult`. "A universal keep/drop verdict requires user-confirmed
workload weighting and policy thresholds" — this module reports observations
only, never a keep/drop string.

Every timed write is measured via `EXPLAIN (ANALYZE, BUFFERS, WAL, TIMING
OFF, FORMAT JSON)` on the write statement itself, the same technique
`adapters.benchmark.explain` already uses for reads: `pg_stat_wal`/
`pg_stat_user_tables` are cumulative, stats-collector-fed views with real
publish lag (confirmed empirically: a delta read immediately after a write
came back zero), unusable for a single before/after measurement in one
short-lived session. `EXPLAIN ANALYZE` really executes an INSERT/UPDATE and
reports its own WAL/timing synchronously off the top `ModifyTable` plan node.

Each measured write runs inside its own `BEGIN`/`ROLLBACK`, so "before" and
"after" always start from identical data — nothing measured here is ever
actually kept, only its cost is observed.

ponytail: HOT-update impact (named in the roadmap) is not observed — the same
`pg_stat_user_tables` lag applies to `n_tup_hot_upd`, and `EXPLAIN` reports no
HOT-eligibility fact to substitute. Upgrade path: an in-process
`pg_stat_clear_snapshot()` wait loop, if this ever needs it badly enough to
accept the added runtime.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import psycopg
from psycopg import sql

from pgproof.adapters.benchmark.explain import parse_explain
from pgproof.adapters.candidates.generate import IndexCandidate
from pgproof.adapters.seeder.plan import generate_table_rows, unique_value_columns
from pgproof.domain.identifiers import ColumnId, TableId, column_names
from pgproof.domain.ir.schema import ConstraintKind, SchemaIR, TableIR

_DEFAULT_BATCH_SIZE = 100


@dataclass(frozen=True)
class WriteOperationCost:
    execution_us_before: float
    execution_us_after: float
    wal_bytes_before: int | None
    wal_bytes_after: int | None


@dataclass(frozen=True)
class WriteCostObservation:
    insert: WriteOperationCost
    update_indexed_column: WriteOperationCost
    update_unrelated_column: WriteOperationCost | None
    build_us: int
    index_size_bytes: int


def _table(schema: SchemaIR, table_id: TableId) -> TableIR:
    for table in schema.tables:
        if table.id == table_id:
            return table
    raise ValueError(f"{table_id} is not in this schema")


def _primary_key_column(schema: SchemaIR, table_id: TableId) -> ColumnId | None:
    for constraint in schema.constraints:
        if (
            constraint.table == table_id
            and constraint.kind is ConstraintKind.PRIMARY_KEY
            and len(constraint.columns) == 1
        ):
            return constraint.columns[0]
    return None


def _unrelated_column(
    table: TableIR, candidate: IndexCandidate, pk: ColumnId | None
) -> ColumnId | None:
    """Any column outside the candidate's own key columns and the primary
    key, database-default (identity/serial) columns excluded — updating a
    generated column is rejected by PostgreSQL outright.
    """
    for column in table.columns:
        if column.id in candidate.columns or column.id == pk:
            continue
        if column.is_identity or column.is_generated:
            continue
        return column.id
    return None


def _relation(table: TableIR) -> sql.Identifier:
    return sql.Identifier(table.schema_name, table.name)


def _existing_values(
    cur: psycopg.Cursor[tuple[object, ...]], column: ColumnId
) -> frozenset[object]:
    schema_name, table_name, column_name = column_names(column)
    cur.execute(
        sql.SQL("SELECT {} FROM {} WHERE {} IS NOT NULL").format(
            sql.Identifier(column_name),
            sql.Identifier(schema_name, table_name),
            sql.Identifier(column_name),
        )
    )
    return frozenset(row[0] for row in cur.fetchall())


def _parent_pools(
    cur: psycopg.Cursor[tuple[object, ...]], schema: SchemaIR, table_id: TableId
) -> dict[TableId, list[object]]:
    pools: dict[TableId, list[object]] = {}
    for constraint in schema.constraints:
        if constraint.table != table_id or constraint.kind is not ConstraintKind.FOREIGN_KEY:
            continue
        if constraint.referenced_table is None or len(constraint.referenced_columns) != 1:
            continue
        pools[constraint.referenced_table] = list(
            _existing_values(cur, constraint.referenced_columns[0])
        )
    return pools


def _batch_rows(
    cur: psycopg.Cursor[tuple[object, ...]],
    table: TableIR,
    schema: SchemaIR,
    *,
    global_seed: int,
    epoch: datetime,
    batch_size: int,
) -> tuple[dict[str, object], ...]:
    unique_columns, _ = unique_value_columns(table, schema)
    existing = {column: _existing_values(cur, column) for column in unique_columns}
    result = generate_table_rows(
        table,
        schema,
        global_seed=global_seed,
        generator_version=1,
        epoch=epoch,
        row_count=batch_size,
        parent_key_pools=_parent_pools(cur, schema, table.id),
        existing_unique_values=existing,
    )
    return result.rows


def _insert_statement(table: TableIR, rows: Sequence[dict[str, object]]) -> sql.Composed:
    columns = list(rows[0])
    rows_sql = sql.SQL(", ").join(
        sql.SQL("({})").format(sql.SQL(", ").join(sql.Literal(row[name]) for name in columns))
        for row in rows
    )
    return sql.SQL("INSERT INTO {} ({}) VALUES {}").format(
        _relation(table), sql.SQL(", ").join(sql.Identifier(name) for name in columns), rows_sql
    )


def _update_statement(
    table: TableIR, pk_column: ColumnId, row_ids: Sequence[object], target: ColumnId, value: object
) -> sql.Composed:
    _, _, pk_name = column_names(pk_column)
    _, _, target_name = column_names(target)
    return sql.SQL("UPDATE {} SET {} = {} WHERE {} = ANY({})").format(
        _relation(table),
        sql.Identifier(target_name),
        sql.Literal(value),
        sql.Identifier(pk_name),
        sql.Literal(list(row_ids)),
    )


def _explain_write(
    cur: psycopg.Cursor[tuple[object, ...]], statement: sql.Composable
) -> tuple[float, int | None]:
    cur.execute(
        sql.SQL("EXPLAIN (ANALYZE, BUFFERS, WAL, TIMING OFF, FORMAT JSON) {}").format(statement)
    )
    row = cur.fetchone()
    assert row is not None
    diagnostics = parse_explain(row[0])
    execution_us = (diagnostics.execution_time_ms or 0.0) * 1000
    wal_bytes = diagnostics.plan.wal.bytes if diagnostics.plan.wal is not None else None
    return execution_us, wal_bytes


def _timed_rollback(
    cur: psycopg.Cursor[tuple[object, ...]], statement: sql.Composable
) -> tuple[float, int | None]:
    cur.execute("BEGIN")
    try:
        return _explain_write(cur, statement)
    finally:
        cur.execute("ROLLBACK")


def measure_write_cost(
    conn: psycopg.Connection[tuple[object, ...]],
    schema: SchemaIR,
    candidate: IndexCandidate,
    *,
    global_seed: int,
    epoch: datetime,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> WriteCostObservation:
    """Insert/update-indexed/update-unrelated cost before the candidate index
    exists, the index is built, then the same three costs after.
    """
    table = _table(schema, candidate.table)
    pk_column = _primary_key_column(schema, candidate.table)
    if pk_column is None:
        raise ValueError(f"{candidate.table} has no single-column primary key to update against")
    unrelated_column = _unrelated_column(table, candidate, pk_column)
    indexed_column = candidate.columns[0]

    with conn.cursor() as cur:
        rows = _batch_rows(
            cur, table, schema, global_seed=global_seed, epoch=epoch, batch_size=batch_size
        )
        insert_statement = _insert_statement(table, rows)
        cur.execute(
            sql.SQL("SELECT {} FROM {} ORDER BY {} LIMIT %s").format(
                sql.Identifier(column_names(pk_column)[2]),
                _relation(table),
                sql.Identifier(column_names(pk_column)[2]),
            ),
            (batch_size,),
        )
        row_ids = [row[0] for row in cur.fetchall()]
        indexed_statement = _update_statement(
            table, pk_column, row_ids, indexed_column, _sentinel(rows, indexed_column)
        )
        unrelated_statement = (
            _update_statement(
                table, pk_column, row_ids, unrelated_column, _sentinel(rows, unrelated_column)
            )
            if unrelated_column is not None
            else None
        )

        insert_before, insert_wal_before = _timed_rollback(cur, insert_statement)
        indexed_before, indexed_wal_before = _timed_rollback(cur, indexed_statement)
        unrelated_before = (
            _timed_rollback(cur, unrelated_statement)
            if unrelated_statement is not None
            else (None, None)
        )

        # `EXPLAIN` cannot wrap DDL at all (PostgreSQL only accepts it around
        # a plannable DML statement) — `CREATE INDEX`'s own cost is measured
        # with a plain wall-clock timer instead.
        cur.execute("BEGIN")
        build_start = time.perf_counter()
        cur.execute(candidate.apply_sql)
        build_us = (time.perf_counter() - build_start) * 1_000_000
        cur.execute("SELECT pg_relation_size(%s)", (candidate.name,))
        size_row = cur.fetchone()
        cur.execute("COMMIT")
        index_size_bytes = cast("int", size_row[0]) if size_row is not None else 0

        insert_after, insert_wal_after = _timed_rollback(cur, insert_statement)
        indexed_after, indexed_wal_after = _timed_rollback(cur, indexed_statement)
        unrelated_after = (
            _timed_rollback(cur, unrelated_statement)
            if unrelated_statement is not None
            else (None, None)
        )

        cur.execute("BEGIN")
        cur.execute(sql.SQL(candidate.revert_sql))
        cur.execute("COMMIT")

    update_unrelated_column = None
    if unrelated_statement is not None:
        update_unrelated_column = WriteOperationCost(
            execution_us_before=unrelated_before[0],  # type: ignore[arg-type]
            execution_us_after=unrelated_after[0],  # type: ignore[arg-type]
            wal_bytes_before=unrelated_before[1],
            wal_bytes_after=unrelated_after[1],
        )

    return WriteCostObservation(
        insert=WriteOperationCost(
            execution_us_before=insert_before,
            execution_us_after=insert_after,
            wal_bytes_before=insert_wal_before,
            wal_bytes_after=insert_wal_after,
        ),
        update_indexed_column=WriteOperationCost(
            execution_us_before=indexed_before,
            execution_us_after=indexed_after,
            wal_bytes_before=indexed_wal_before,
            wal_bytes_after=indexed_wal_after,
        ),
        update_unrelated_column=update_unrelated_column,
        build_us=round(build_us),
        index_size_bytes=index_size_bytes,
    )


def _sentinel(rows: Sequence[dict[str, object]], column: ColumnId) -> object:
    _, _, name = column_names(column)
    for row in rows:
        if name in row and row[name] is not None:
            return row[name]
    return 0

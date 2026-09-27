"""Realized selectivity against a live, generated dataset. `docs/TECHNICAL_DESIGN.md`
section 19: every probe's row count and selectivity are measured with a real
query, never estimated from `pg_stats` or guessed.

`extract.py` decides which predicates are probeable; this module decides what
value each selectivity tier resolves to and realizes it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

import psycopg
from psycopg import sql

from pgproof.adapters.parameters.extract import ExtractedPredicate, PredicateKind
from pgproof.domain.identifiers import ColumnId, TableId, column_names, table_names
from pgproof.domain.primitives import SnakeCaseEnum

_MAX_DISTINCT_VALUES = 10_000
_RECENT_WINDOW = timedelta(days=7)
_MONTHLY_WINDOW = timedelta(days=30)


class SelectionMethod(SnakeCaseEnum):
    HIGHLY_SELECTIVE = "highly_selective"
    MODERATE_SELECTIVITY = "moderate_selectivity"
    BROAD_SELECTIVITY = "broad_selectivity"
    MOST_COMMON_VALUE = "most_common_value"
    RECENT_WINDOW = "recent_window"
    MONTHLY_WINDOW = "monthly_window"
    FULL_WINDOW = "full_window"


@dataclass(frozen=True)
class ParameterProbe:
    table: TableId
    column: ColumnId
    parameter_position: int
    method: SelectionMethod
    value_hash: str
    is_redacted: bool
    redacted_value: str | None
    row_count: int
    total_row_count: int
    selectivity: float


def _hash(value: object) -> str:
    return f"sha256:{hashlib.sha256(str(value).encode('utf-8')).hexdigest()}"


def _relation(table: TableId) -> sql.Identifier:
    schema_name, table_name = table_names(table)
    return sql.Identifier(schema_name, table_name)


def _column(column: ColumnId) -> sql.Identifier:
    _, _, name = column_names(column)
    return sql.Identifier(name)


def _total_row_count(cur: psycopg.Cursor[tuple[object, ...]], table: TableId) -> int:
    cur.execute(sql.SQL("SELECT count(*) FROM {}").format(_relation(table)))
    row = cur.fetchone()
    return cast("int", row[0]) if row is not None else 0


def _realized_count(
    cur: psycopg.Cursor[tuple[object, ...]],
    table: TableId,
    column: ColumnId,
    operator: str,
    value: object,
) -> int:
    cur.execute(
        sql.SQL("SELECT count(*) FROM {} WHERE {} {} %s").format(
            _relation(table), _column(column), sql.SQL(operator)
        ),
        (value,),
    )
    row = cur.fetchone()
    return cast("int", row[0]) if row is not None else 0


def _probe(
    predicate: ExtractedPredicate,
    method: SelectionMethod,
    value: object,
    *,
    row_count: int,
    total_row_count: int,
    reveal_values: bool,
) -> ParameterProbe:
    return ParameterProbe(
        table=predicate.table,
        column=predicate.column,
        parameter_position=predicate.parameter_position,
        method=method,
        value_hash=_hash(value),
        is_redacted=not reveal_values,
        redacted_value=str(value) if reveal_values else None,
        row_count=row_count,
        total_row_count=total_row_count,
        selectivity=(row_count / total_row_count) if total_row_count else 0.0,
    )


def _equality_probes(
    cur: psycopg.Cursor[tuple[object, ...]],
    predicate: ExtractedPredicate,
    *,
    total_row_count: int,
    reveal_values: bool,
) -> tuple[ParameterProbe, ...]:
    """Realized frequency distribution: least-frequent value (highly
    selective), the value nearest the median frequency (moderate), and the
    most-frequent value (most common). `broad_selectivity` is not distinct
    from `most_common_value` for a discrete equality predicate, so it is not
    produced here — `docs/PR_ROADMAP.md`'s accept criterion is about realized,
    not guessed, selectivity, and inventing a fourth distinct value would be
    exactly that guess.
    """
    cur.execute(
        sql.SQL(
            "SELECT {}, count(*) AS n FROM {} WHERE {} IS NOT NULL GROUP BY {} LIMIT %s"
        ).format(
            _column(predicate.column),
            _relation(predicate.table),
            _column(predicate.column),
            _column(predicate.column),
        ),
        (_MAX_DISTINCT_VALUES + 1,),
    )
    rows = cur.fetchall()
    if not rows or len(rows) > _MAX_DISTINCT_VALUES:
        return ()
    by_count = sorted(rows, key=lambda row: cast("int", row[1]))
    least = by_count[0]
    most = by_count[-1]
    counts = sorted(cast("int", row[1]) for row in by_count)
    median_count = counts[len(counts) // 2]
    moderate = min(by_count, key=lambda row: abs(cast("int", row[1]) - median_count))
    return (
        _probe(
            predicate,
            SelectionMethod.HIGHLY_SELECTIVE,
            least[0],
            row_count=cast("int", least[1]),
            total_row_count=total_row_count,
            reveal_values=reveal_values,
        ),
        _probe(
            predicate,
            SelectionMethod.MODERATE_SELECTIVITY,
            moderate[0],
            row_count=cast("int", moderate[1]),
            total_row_count=total_row_count,
            reveal_values=reveal_values,
        ),
        _probe(
            predicate,
            SelectionMethod.MOST_COMMON_VALUE,
            most[0],
            row_count=cast("int", most[1]),
            total_row_count=total_row_count,
            reveal_values=reveal_values,
        ),
    )


def _numeric_range_probes(
    cur: psycopg.Cursor[tuple[object, ...]],
    predicate: ExtractedPredicate,
    *,
    total_row_count: int,
    reveal_values: bool,
) -> tuple[ParameterProbe, ...]:
    """Real `percentile_cont` cutoffs, each re-verified with an actual `COUNT`
    rather than trusted from the estimate — the accept criterion is realized,
    not guessed, selectivity.
    """
    cur.execute(
        sql.SQL(
            "SELECT percentile_cont(0.1) WITHIN GROUP (ORDER BY {col}), "
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY {col}), "
            "percentile_cont(0.9) WITHIN GROUP (ORDER BY {col}) "
            "FROM {table} WHERE {col} IS NOT NULL"
        ).format(col=_column(predicate.column), table=_relation(predicate.table))
    )
    row = cur.fetchone()
    if row is None or row[0] is None:
        return ()
    low, mid, high = row
    ascending = predicate.operator in (">", ">=")
    tiers = (
        (SelectionMethod.HIGHLY_SELECTIVE, high if ascending else low),
        (SelectionMethod.MODERATE_SELECTIVITY, mid),
        (SelectionMethod.BROAD_SELECTIVITY, low if ascending else high),
    )
    return tuple(
        _probe(
            predicate,
            method,
            value,
            row_count=_realized_count(
                cur, predicate.table, predicate.column, predicate.operator, value
            ),
            total_row_count=total_row_count,
            reveal_values=reveal_values,
        )
        for method, value in tiers
    )


def _timestamp_range_probes(
    cur: psycopg.Cursor[tuple[object, ...]],
    predicate: ExtractedPredicate,
    *,
    total_row_count: int,
    reveal_values: bool,
) -> tuple[ParameterProbe, ...]:
    """Recent/monthly/full-window, anchored to the real observed extremes of
    this column — never wall-clock `now()`, matching the seeder's own fixed
    dataset epoch (`docs/TECHNICAL_DESIGN.md` section 18).
    """
    cur.execute(
        sql.SQL("SELECT min({0}), max({0}) FROM {1} WHERE {0} IS NOT NULL").format(
            _column(predicate.column), _relation(predicate.table)
        )
    )
    row = cur.fetchone()
    if row is None or row[0] is None or row[1] is None:
        return ()
    # `datetime` for a timestamp column, `date` for a date column — both
    # support `+ timedelta`, so the exact type is not pinned here.
    low, high = cast("Any", row[0]), cast("Any", row[1])
    ascending = predicate.operator in (">", ">=")
    anchor = high if ascending else low
    edge = low if ascending else high
    sign = -1 if ascending else 1
    tiers = (
        (SelectionMethod.RECENT_WINDOW, anchor + sign * _RECENT_WINDOW),
        (SelectionMethod.MONTHLY_WINDOW, anchor + sign * _MONTHLY_WINDOW),
        (SelectionMethod.FULL_WINDOW, edge),
    )
    return tuple(
        _probe(
            predicate,
            method,
            value,
            row_count=_realized_count(
                cur, predicate.table, predicate.column, predicate.operator, value
            ),
            total_row_count=total_row_count,
            reveal_values=reveal_values,
        )
        for method, value in tiers
    )


def realize_probes(
    conn: psycopg.Connection[tuple[object, ...]],
    predicates: tuple[ExtractedPredicate, ...],
    *,
    reveal_values: bool = False,
) -> tuple[ParameterProbe, ...]:
    """Every applicable selectivity tier for each of `predicates`, realized
    against `conn`'s current data. A predicate this module cannot honestly
    characterize (too many distinct values for an equality probe, an empty
    column) contributes no probe at all, never a guessed one.
    """
    probes: list[ParameterProbe] = []
    with conn.cursor() as cur:
        totals: dict[TableId, int] = {}
        for predicate in predicates:
            if predicate.table not in totals:
                totals[predicate.table] = _total_row_count(cur, predicate.table)
            total = totals[predicate.table]
            if predicate.kind is PredicateKind.EQUALITY:
                probes.extend(
                    _equality_probes(
                        cur, predicate, total_row_count=total, reveal_values=reveal_values
                    )
                )
            elif predicate.kind is PredicateKind.NUMERIC_RANGE:
                probes.extend(
                    _numeric_range_probes(
                        cur, predicate, total_row_count=total, reveal_values=reveal_values
                    )
                )
            elif predicate.kind is PredicateKind.TIMESTAMP_RANGE:
                probes.extend(
                    _timestamp_range_probes(
                        cur, predicate, total_row_count=total, reveal_values=reveal_values
                    )
                )
    return tuple(probes)

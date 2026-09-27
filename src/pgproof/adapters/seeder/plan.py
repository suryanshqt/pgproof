"""Deterministic dataset planning. `docs/TECHNICAL_DESIGN.md` section 18.

Pure: no database connection, no wall clock, no `random` module state. Every
value comes from a `random.Random` seeded by
`H(global_seed, table, component, generator_version)`, so adding a table or a
column shifts no other column's stream. `adapters.seeder.load` runs this
against a live database.

Tier 1 of section 18's hierarchy (user-declared distributions) has no data
source in this codebase yet; tiers 2-4 are implemented here.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, cast

from pglast import ast
from pglast.enums import A_Expr_Kind, BoolExprType
from pglast.parser import ParseError, parse_sql

from pgproof.domain.identifiers import ColumnId, TableId, column_id
from pgproof.domain.ir.schema import (
    ColumnIR,
    ConstraintKind,
    SchemaIR,
    TableIR,
    UnsupportedConstruct,
)

_SEED_MASK: Final = (1 << 63) - 1
_FALLBACK_CEILING: Final = 1_000_000
_RECENT_DAYS: Final = 365
_FALLBACK_DAYS: Final = 3650
_UNIQUE_SPAN_FACTOR: Final = 8
_UNIQUE_SPAN_FLOOR: Final = 1024

_INTEGER_TYPES: Final = frozenset({"integer", "bigint", "smallint", "int", "int2", "int4", "int8"})
_NUMERIC_TYPES: Final = frozenset(
    {"numeric", "decimal", "real", "double precision", "float", "float4", "float8"}
)
_TEXT_TYPES: Final = frozenset(
    {"text", "character varying", "varchar", "character", "char", "bpchar"}
)
_BOOLEAN_TYPES: Final = frozenset({"boolean", "bool"})
_TIMESTAMP_TYPES: Final = frozenset(
    {
        "timestamp",
        "timestamptz",
        "timestamp with time zone",
        "timestamp without time zone",
        "date",
    }
)
_TIMESTAMP_NAMES: Final = frozenset({"created_at", "updated_at", "date"})
_MODIFIER: Final = re.compile(r"\(\s*\d+\s*(?:,\s*\d+\s*)?\)")
_LOWER_OPERATORS: Final = frozenset({">=", ">"})
_UPPER_OPERATORS: Final = frozenset({"<=", "<"})


@dataclass(frozen=True)
class ColumnAssumption:
    """One column's chosen generation strategy.

    `docs/TECHNICAL_DESIGN.md` section 18's "assumptions": the same
    non-hidden-input contract `UnsupportedConstruct` already holds for schema
    reconstruction. `inferred` is False only for tier-2 native facts.
    """

    table: TableId
    column: ColumnId
    strategy: str
    inferred: bool


@dataclass(frozen=True)
class TableGenerationResult:
    rows: tuple[dict[str, object], ...]
    assumptions: tuple[ColumnAssumption, ...]
    unsupported: tuple[UnsupportedConstruct, ...]


@dataclass(frozen=True)
class TableOrderResult:
    order: tuple[TableId, ...]
    deferred_columns: tuple[ColumnId, ...]
    unsupported: tuple[UnsupportedConstruct, ...]


def component_seed(global_seed: int, table: TableId, component: str, generator_version: int) -> int:
    """`component_seed = H(global_seed, table, component_id, generator_version)`.

    The schema is deliberately not an input: hashing it would shift every
    existing stream whenever an unrelated table was added, which is the exact
    property section 18 requires this derivation to preserve.
    """
    canonical = json.dumps(
        [global_seed, table, component, generator_version],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & _SEED_MASK


def component_stream(
    global_seed: int, table: TableId, component: str, generator_version: int
) -> random.Random:
    return random.Random(component_seed(global_seed, table, component, generator_version))


def _base_type(data_type: str) -> str:
    return _MODIFIER.sub("", data_type).strip().lower()


def _family(data_type: str) -> str | None:
    base = _base_type(data_type)
    if base.endswith("]"):
        return None
    if base in _INTEGER_TYPES:
        return "integer"
    if base in _NUMERIC_TYPES:
        return "numeric"
    if base in _TEXT_TYPES:
        return "text"
    if base in _BOOLEAN_TYPES:
        return "boolean"
    if base in _TIMESTAMP_TYPES:
        return "timestamp"
    return None


def _is_date(data_type: str) -> bool:
    return _base_type(data_type) == "date"


# --------------------------------------------------------------------------
# CHECK constraint recognition
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _SetCheck:
    literals: tuple[object, ...]


@dataclass(frozen=True)
class _RangeCheck:
    low: int
    high: int


def _unwrap(node: object) -> object:
    while isinstance(node, ast.TypeCast):
        node = node.arg
    return node


def _column_name(node: object) -> str | None:
    target = _unwrap(node)
    if not isinstance(target, ast.ColumnRef):
        return None
    last = target.fields[-1]
    return str(last.sval) if isinstance(last, ast.String) else None


def _literal(node: object) -> object | None:
    target = _unwrap(node)
    if not isinstance(target, ast.A_Const) or target.isnull:
        return None
    value = target.val
    if isinstance(value, ast.String):
        return cast("str", value.sval)
    if isinstance(value, ast.Integer):
        return cast("int", value.ival)
    if isinstance(value, ast.Float):
        return float(cast("str", value.fval))
    if isinstance(value, ast.Boolean):
        return cast("bool", value.boolval)
    return None


def _operator(node: object) -> str | None:
    if not isinstance(node, ast.A_Expr) or len(node.name) != 1:
        return None
    name = node.name[0]
    return str(name.sval) if isinstance(name, ast.String) else None


def _equality_literal(node: object) -> tuple[str, object] | None:
    if not isinstance(node, ast.A_Expr) or node.kind != A_Expr_Kind.AEXPR_OP:
        return None
    if _operator(node) != "=":
        return None
    name = _column_name(node.lexpr)
    value = _literal(node.rexpr)
    if name is None or value is None:
        return None
    return name, value


def _recognize_set(where: object) -> tuple[str, _SetCheck] | None:
    if isinstance(where, ast.A_Expr) and _operator(where) == "=":
        name = _column_name(where.lexpr)
        if name is None:
            return None
        if where.kind == A_Expr_Kind.AEXPR_IN:
            elements: Iterable[object] = where.rexpr
        elif where.kind == A_Expr_Kind.AEXPR_OP_ANY:
            array = _unwrap(where.rexpr)
            if not isinstance(array, ast.A_ArrayExpr):
                return None
            elements = array.elements
        else:
            return None
        literals = [_literal(element) for element in elements]
        if not literals or any(value is None for value in literals):
            return None
        return name, _SetCheck(literals=tuple(sorted(literals, key=str)))
    if isinstance(where, ast.BoolExpr) and where.boolop == BoolExprType.OR_EXPR:
        pairs = [_equality_literal(arg) for arg in where.args]
        if not pairs or any(pair is None for pair in pairs):
            return None
        names = {pair[0] for pair in pairs if pair is not None}
        if len(names) != 1:
            return None
        values = sorted((pair[1] for pair in pairs if pair is not None), key=str)
        return names.pop(), _SetCheck(literals=tuple(values))
    return None


def _bound(node: object) -> tuple[str, str, int] | None:
    operator = _operator(node)
    if operator is None or not isinstance(node, ast.A_Expr):
        return None
    if node.kind != A_Expr_Kind.AEXPR_OP:
        return None
    name = _column_name(node.lexpr)
    value = _literal(node.rexpr)
    if name is None or not isinstance(value, int) or isinstance(value, bool):
        return None
    if operator not in _LOWER_OPERATORS and operator not in _UPPER_OPERATORS:
        return None
    return name, operator, value


def _apply_bound(low: int | None, high: int | None, operator: str, value: int) -> tuple[int, int]:
    if operator in _LOWER_OPERATORS:
        candidate = value if operator == ">=" else value + 1
        return candidate, high if high is not None else candidate + _FALLBACK_CEILING
    candidate = value if operator == "<=" else value - 1
    return low if low is not None else candidate - _FALLBACK_CEILING, candidate


def _recognize_range(where: object) -> tuple[str, _RangeCheck] | None:
    if isinstance(where, ast.A_Expr) and where.kind == A_Expr_Kind.AEXPR_BETWEEN:
        name = _column_name(where.lexpr)
        bounds = [_literal(node) for node in where.rexpr]
        if name is None or len(bounds) != 2:
            return None
        first, second = bounds
        if not isinstance(first, int) or not isinstance(second, int):
            return None
        return (name, _RangeCheck(low=first, high=second)) if first <= second else None

    if isinstance(where, ast.BoolExpr) and where.boolop == BoolExprType.AND_EXPR:
        parts = [_bound(arg) for arg in where.args]
    else:
        parts = [_bound(where)]
    if not parts or any(part is None for part in parts):
        return None
    names = {part[0] for part in parts if part is not None}
    if len(names) != 1:
        return None
    low: int | None = None
    high: int | None = None
    for part in parts:
        if part is None:  # pragma: no cover - rejected above
            return None
        low, high = _apply_bound(low, high, part[1], part[2])
    if low is None or high is None or low > high:
        return None
    return names.pop(), _RangeCheck(low=low, high=high)


def _recognize_checks(
    table: TableIR, schema: SchemaIR
) -> tuple[dict[ColumnId, _SetCheck | _RangeCheck], tuple[UnsupportedConstruct, ...]]:
    """Structural matching against the WHERE clause root, not a `pglast.visitors`
    walk: a visitor would also match a recognizable fragment nested inside an
    expression whose surrounding operators this generator cannot honour, and
    then generate values that satisfy the fragment while violating the whole.
    """
    known = {column.name for column in table.columns}
    recognized: dict[ColumnId, _SetCheck | _RangeCheck] = {}
    unsupported: list[UnsupportedConstruct] = []
    for constraint in schema.constraints:
        if constraint.table != table.id or constraint.kind is not ConstraintKind.CHECK:
            continue
        expression = constraint.expression
        if expression is None:
            continue
        match = _recognized_check(expression)
        if match is None or match[0] not in known:
            unsupported.append(
                UnsupportedConstruct(kind="unsupported_check_constraint", reason=expression)
            )
            continue
        recognized[column_id(table.id, match[0])] = match[1]
    return recognized, tuple(unsupported)


def _recognized_check(expression: str) -> tuple[str, _SetCheck | _RangeCheck] | None:
    try:
        parsed = parse_sql(f"SELECT 1 WHERE {expression}")
    except ParseError:
        return None
    where = parsed[0].stmt.whereClause
    # ponytail: only an equality-literal set and an integer-literal range are
    # recognized; date and numeric ranges, LIKE patterns and function calls
    # fall through to a lower tier. Upgrade path: extend `_recognized_check`.
    return _recognize_set(where) or _recognize_range(where)


# --------------------------------------------------------------------------
# Table order
# --------------------------------------------------------------------------


def _strongly_connected(
    nodes: Sequence[TableId], successors: Mapping[TableId, frozenset[TableId]]
) -> list[tuple[TableId, ...]]:
    """Iterative Tarjan: a deep FK chain must not overflow the interpreter stack."""
    index: dict[TableId, int] = {}
    low: dict[TableId, int] = {}
    stack: list[TableId] = []
    on_stack: set[TableId] = set()
    components: list[tuple[TableId, ...]] = []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        work: list[tuple[TableId, object]] = [(root, iter(sorted(successors.get(root, ()))))]
        while work:
            node, iterator = work[-1]
            descended = False
            for successor in iterator:  # type: ignore[attr-defined]
                if successor not in index:
                    index[successor] = low[successor] = counter
                    counter += 1
                    stack.append(successor)
                    on_stack.add(successor)
                    work.append((successor, iter(sorted(successors.get(successor, ())))))
                    descended = True
                    break
                if successor in on_stack:
                    low[node] = min(low[node], index[successor])
            if descended:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                component: list[TableId] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(tuple(sorted(component)))
    return components


def build_table_order(schema: SchemaIR) -> TableOrderResult:
    """Parents before children, with section 18's cycle rules applied.

    A cycle whose every within-cycle foreign-key column is nullable is kept and
    those columns deferred (create-then-fill); any other cycle drops every table
    in it, explicitly.
    """
    nodes = tuple(sorted(table.id for table in schema.tables))
    known = frozenset(nodes)
    foreign_keys = [
        constraint
        for constraint in schema.constraints
        if constraint.kind is ConstraintKind.FOREIGN_KEY
        and constraint.referenced_table in known
        and constraint.table in known
    ]
    parents: dict[TableId, set[TableId]] = {node: set() for node in nodes}
    for constraint in foreign_keys:
        assert constraint.referenced_table is not None
        parents[constraint.table].add(constraint.referenced_table)

    nullable_columns = frozenset(
        column.id for table in schema.tables for column in table.columns if column.nullable
    )
    successors = {node: frozenset(targets) for node, targets in parents.items()}

    deferred: set[ColumnId] = set()
    dropped: set[TableId] = set()
    unsupported: list[UnsupportedConstruct] = []
    for component in _strongly_connected(nodes, successors):
        members = frozenset(component)
        self_referential = any(
            constraint.table == constraint.referenced_table and constraint.table in members
            for constraint in foreign_keys
        )
        if len(component) == 1 and not self_referential:
            continue
        inside = [
            constraint
            for constraint in foreign_keys
            if constraint.table in members and constraint.referenced_table in members
        ]
        columns = [column for constraint in inside for column in constraint.columns]
        # ponytail: a deferrable within-cycle FK is indistinguishable from a
        # plain one here because `ConstraintIR` has no `deferrable` field.
        # Upgrade path: add one in a schema-model PR, then branch on it.
        if columns and all(column in nullable_columns for column in columns):
            deferred.update(columns)
            for constraint in inside:
                assert constraint.referenced_table is not None
                parents[constraint.table].discard(constraint.referenced_table)
            continue
        dropped.update(members)
        unsupported.append(
            UnsupportedConstruct(
                kind="fk_cycle",
                reason="non-null foreign key cycle: " + ", ".join(sorted(members)),
            )
        )

    remaining = [node for node in nodes if node not in dropped]
    pending = {
        node: {parent for parent in parents[node] if parent not in dropped and parent != node}
        for node in remaining
    }
    order: list[TableId] = []
    while pending:
        ready = sorted(node for node, blockers in pending.items() if not blockers)
        if not ready:  # pragma: no cover - every cycle is resolved or dropped above
            break
        for node in ready:
            del pending[node]
            order.append(node)
        for blockers in pending.values():
            blockers.difference_update(ready)

    return TableOrderResult(
        order=tuple(order),
        deferred_columns=tuple(sorted(deferred)),
        unsupported=tuple(unsupported),
    )


# --------------------------------------------------------------------------
# Row generation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _ColumnPlan:
    # None means "omit from the row entirely" so PostgreSQL applies its own
    # default; COPY into an identity or generated column is rejected outright.
    values: tuple[object, ...] | None
    strategy: str
    inferred: bool


def _database_default(column: ColumnIR) -> bool:
    if column.is_identity or column.is_generated:
        return True
    default = column.default_expression or ""
    return "nextval(" in default


def unique_value_columns(
    table: TableIR, schema: SchemaIR
) -> tuple[frozenset[ColumnId], tuple[UnsupportedConstruct, ...]]:
    """Single-column PK/UNIQUE columns this generator produces distinct values
    for, plus one `UnsupportedConstruct` for every single-column PK/UNIQUE
    column it does not: a type outside integer/text with no database default
    would otherwise fall through to a lower tier with no distinctness
    guarantee at all, risking a live collision at COPY time instead of an
    honest report.

    Composite constraints are deliberately absent: v1 enforces uniqueness per
    column only, so each of their columns is generated by whichever other tier
    applies to it.
    """
    result: set[ColumnId] = set()
    unsupported: list[UnsupportedConstruct] = []
    by_id = {column.id: column for column in table.columns}
    for constraint in schema.constraints:
        if constraint.table != table.id:
            continue
        if constraint.kind not in (ConstraintKind.PRIMARY_KEY, ConstraintKind.UNIQUE):
            continue
        if len(constraint.columns) != 1:
            continue
        column = by_id.get(constraint.columns[0])
        if column is None or _database_default(column):
            continue
        if _family(column.data_type) in ("integer", "text"):
            result.add(column.id)
        else:
            unsupported.append(
                UnsupportedConstruct(
                    kind="unsupported_unique_constraint",
                    reason=f"{column.id}: no distinctness strategy for {column.data_type}",
                )
            )
    return frozenset(result), tuple(unsupported)


def _unique_values(
    column: ColumnIR, stream: random.Random, row_count: int, existing: frozenset[object]
) -> tuple[object, ...]:
    # ponytail: the skip pool is sized from `len(existing)`, so a table already
    # holding millions of rows samples millions of candidates. Upgrade path:
    # start the sequence past the observed maximum instead.
    needed = row_count + len(existing)
    span = max(needed * _UNIQUE_SPAN_FACTOR, _UNIQUE_SPAN_FLOOR)
    indexes = stream.sample(range(1, span + 1), needed)
    if _family(column.data_type) == "integer":
        candidates: list[object] = list(indexes)
    else:
        candidates = [f"{column.name}-{index:08d}" for index in indexes]
    return tuple(value for value in candidates if value not in existing)[:row_count]


def _timestamp_values(
    column: ColumnIR, stream: random.Random, row_count: int, epoch: datetime, days: int
) -> tuple[object, ...]:
    span = days * 86_400
    values: list[object] = []
    for _ in range(row_count):
        moment = epoch - timedelta(seconds=stream.randrange(span))
        values.append(moment.date() if _is_date(column.data_type) else moment)
    return tuple(values)


def _plan_column(
    column: ColumnIR,
    *,
    stream: random.Random,
    row_count: int,
    foreign_pool: Sequence[object] | None,
    unique: bool,
    existing: frozenset[object],
    check: _SetCheck | _RangeCheck | None,
    epoch: datetime,
    deferred: bool,
) -> _ColumnPlan | None:
    if deferred:
        return _ColumnPlan(
            values=(None,) * row_count, strategy="deferred_foreign_key", inferred=False
        )
    if foreign_pool is not None:
        if not foreign_pool:
            return None
        pool = list(foreign_pool)
        # ponytail: sampled with replacement even when `unique` is also True
        # (a one-to-one relationship's UNIQUE FK column), so a collision is
        # possible when row_count approaches len(pool). Upgrade path: sample
        # without replacement here and report unsupported when the pool is
        # too small to cover row_count distinctly.
        return _ColumnPlan(
            values=tuple(stream.choice(pool) for _ in range(row_count)),
            strategy="foreign_key",
            inferred=False,
        )
    if _database_default(column):
        return _ColumnPlan(values=None, strategy="database_default", inferred=False)

    family = _family(column.data_type)
    if unique and family in ("integer", "text"):
        return _ColumnPlan(
            values=_unique_values(column, stream, row_count, existing),
            strategy=f"unique_sequential_{'int' if family == 'integer' else 'text'}",
            inferred=False,
        )
    if family == "boolean":
        return _ColumnPlan(
            values=tuple(stream.choice([True, False]) for _ in range(row_count)),
            strategy="boolean",
            inferred=False,
        )
    if isinstance(check, _SetCheck):
        return _ColumnPlan(
            values=tuple(stream.choice(check.literals) for _ in range(row_count)),
            strategy="check_recognized_set",
            inferred=False,
        )
    if isinstance(check, _RangeCheck) and family == "integer":
        return _ColumnPlan(
            values=tuple(stream.randint(check.low, check.high) for _ in range(row_count)),
            strategy="check_recognized_range",
            inferred=False,
        )

    name = column.name.lower()
    if family == "timestamp" and ("_at" in name or name in _TIMESTAMP_NAMES):
        return _ColumnPlan(
            values=_timestamp_values(column, stream, row_count, epoch, _RECENT_DAYS),
            strategy="timestamp_heuristic",
            inferred=True,
        )
    if family == "text" and "email" in name:
        # `.test` is IANA-reserved (RFC 2606), so a generated address can never
        # reach a real mailbox if a fixture is ever pointed at a mail sender.
        return _ColumnPlan(
            values=tuple(f"user{index}@example.test" for index in range(row_count)),
            strategy="email_heuristic",
            inferred=True,
        )

    if family == "integer":
        values: tuple[object, ...] = tuple(
            stream.randrange(_FALLBACK_CEILING) for _ in range(row_count)
        )
    elif family == "numeric":
        values = tuple(round(stream.uniform(0, _FALLBACK_CEILING), 2) for _ in range(row_count))
    elif family == "text":
        values = tuple(f"{column.name}-{index}" for index in range(row_count))
    elif family == "timestamp":
        values = _timestamp_values(column, stream, row_count, epoch, _FALLBACK_DAYS)
    else:
        return None
    return _ColumnPlan(values=values, strategy="uniform_fallback", inferred=True)


def _foreign_pools(
    table: TableIR, schema: SchemaIR, parent_key_pools: Mapping[TableId, Sequence[object]]
) -> tuple[dict[ColumnId, Sequence[object]], tuple[UnsupportedConstruct, ...]]:
    pools: dict[ColumnId, Sequence[object]] = {}
    unsupported: list[UnsupportedConstruct] = []
    for constraint in schema.constraints:
        if constraint.table != table.id or constraint.kind is not ConstraintKind.FOREIGN_KEY:
            continue
        if constraint.referenced_table is None:
            continue
        if len(constraint.columns) != 1:
            # ponytail: picking each column of a composite FK independently
            # would fabricate parent tuples that do not exist, so these columns
            # get no value source at all. Upgrade path: key the pool by the
            # whole referenced tuple.
            unsupported.append(
                UnsupportedConstruct(
                    kind="unsupported_composite_foreign_key", reason=constraint.name
                )
            )
            continue
        pools[constraint.columns[0]] = parent_key_pools.get(constraint.referenced_table, ())
    return pools, tuple(unsupported)


def generate_table_rows(
    table: TableIR,
    schema: SchemaIR,
    *,
    global_seed: int,
    generator_version: int,
    epoch: datetime,
    row_count: int,
    parent_key_pools: Mapping[TableId, Sequence[object]],
    existing_unique_values: Mapping[ColumnId, frozenset[object]],
    defer_columns: frozenset[ColumnId] = frozenset(),
) -> TableGenerationResult:
    """`row_count` rows for one table, ready for COPY.

    A NOT NULL column this generator has no value source for drops the whole
    table rather than inventing one: section 18's "non-null unsupported cycles
    fail explicitly", generalized to any such column.
    """
    checks, unsupported_list = _recognize_checks(table, schema)
    pools, pool_unsupported = _foreign_pools(table, schema, parent_key_pools)
    unique, unique_unsupported = unique_value_columns(table, schema)
    unsupported = [*unsupported_list, *pool_unsupported, *unique_unsupported]

    assumptions: list[ColumnAssumption] = []
    plans: list[tuple[str, _ColumnPlan]] = []
    for column in table.columns:
        plan = _plan_column(
            column,
            stream=component_stream(global_seed, table.id, column.id, generator_version),
            row_count=row_count,
            foreign_pool=pools.get(column.id),
            unique=column.id in unique,
            existing=existing_unique_values.get(column.id, frozenset()),
            check=checks.get(column.id),
            epoch=epoch,
            deferred=column.id in defer_columns,
        )
        if plan is None:
            if not column.nullable:
                unsupported.append(
                    UnsupportedConstruct(
                        kind="unsupported_column_type",
                        reason=f"{column.id}: no value source for a NOT NULL {column.data_type}",
                    )
                )
                return TableGenerationResult(
                    rows=(), assumptions=(), unsupported=tuple(unsupported)
                )
            plan = _ColumnPlan(values=(None,) * row_count, strategy="null_fallback", inferred=True)
        assumptions.append(
            ColumnAssumption(
                table=table.id, column=column.id, strategy=plan.strategy, inferred=plan.inferred
            )
        )
        plans.append((column.name, plan))

    rows = tuple(
        {name: plan.values[index] for name, plan in plans if plan.values is not None}
        for index in range(row_count)
    )
    return TableGenerationResult(
        rows=rows, assumptions=tuple(assumptions), unsupported=tuple(unsupported)
    )


__all__ = [
    "ColumnAssumption",
    "TableGenerationResult",
    "TableOrderResult",
    "build_table_order",
    "component_seed",
    "component_stream",
    "generate_table_rows",
    "unique_value_columns",
]

"""Predicate extraction from a normalized query. `docs/TECHNICAL_DESIGN.md`
section 19: "supported predicates receive values from actual generated data."

Pure: walks `QueryIR.normalized_sql` (BE-19's own canonical output — every
literal already stripped to a `$N` `ParamRef`, so unlike
`adapters.seeder.plan`'s CHECK-constraint recognizer this module never has to
handle a raw literal) looking for `column <op> $N` comparisons. Multi-column
expressions, `IN`-lists, `LIKE`, and anything not resolving to exactly one of
`query.relations`' own columns get no predicate — this module never probes
something it cannot honestly characterize.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from pglast import ast, visitors
from pglast.enums import A_Expr_Kind, BoolExprType
from pglast.parser import ParseError, parse_sql

from pgproof.domain.identifiers import ColumnId, TableId, column_id
from pgproof.domain.ir.schema import SchemaIR
from pgproof.domain.ir.workload import QueryIR
from pgproof.domain.primitives import SnakeCaseEnum

_INTEGER_TYPES: Final = frozenset({"integer", "bigint", "smallint", "int", "int2", "int4", "int8"})
_NUMERIC_TYPES: Final = frozenset(
    {"numeric", "decimal", "real", "double precision", "float", "float4", "float8"}
)
_TIMESTAMP_TYPES: Final = frozenset(
    {
        "timestamp",
        "timestamptz",
        "timestamp with time zone",
        "timestamp without time zone",
        "date",
    }
)
_RANGE_OPERATORS: Final = frozenset({">", ">=", "<", "<="})


class PredicateKind(SnakeCaseEnum):
    EQUALITY = "equality"
    NUMERIC_RANGE = "numeric_range"
    TIMESTAMP_RANGE = "timestamp_range"


@dataclass(frozen=True)
class ExtractedPredicate:
    """One probeable `column <op> $N` comparison against a real relation."""

    table: TableId
    column: ColumnId
    parameter_position: int
    operator: str
    kind: PredicateKind


def _base_type(data_type: str) -> str:
    paren = data_type.find("(")
    return (data_type[:paren] if paren != -1 else data_type).strip().lower()


def _column_name(node: object) -> str | None:
    if not isinstance(node, ast.ColumnRef):
        return None
    last = node.fields[-1]
    return str(last.sval) if isinstance(last, ast.String) else None


def _param_number(node: object) -> int | None:
    return node.number if isinstance(node, ast.ParamRef) else None


def _operator(node: ast.A_Expr) -> str | None:
    if node.kind != A_Expr_Kind.AEXPR_OP or len(node.name) != 1:
        return None
    name = node.name[0]
    return str(name.sval) if isinstance(name, ast.String) else None


class _PredicateFinder(visitors.Visitor):
    """Every top-level-or-AND-nested `column <op> $N` comparison. An `OR`
    branch is not descended into: a predicate reachable only through an `OR`
    is not something a probe's realized selectivity could honestly describe
    in isolation from its sibling.
    """

    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[str, str, int]] = []  # (column_name, operator, position)

    def visit_BoolExpr(self, _ancestors: object, node: ast.BoolExpr) -> object:  # noqa: N802
        return visitors.Skip if node.boolop != BoolExprType.AND_EXPR else None

    def visit_A_Expr(self, _ancestors: object, node: ast.A_Expr) -> None:  # noqa: N802
        operator = _operator(node)
        if operator is None:
            return
        column = _column_name(node.lexpr)
        position = _param_number(node.rexpr)
        if column is None or position is None:
            column = _column_name(node.rexpr)
            position = _param_number(node.lexpr)
        if column is not None and position is not None:
            self.found.append((column, operator, position))


def _resolve_column(
    name: str, relations: tuple[TableId, ...], schema: SchemaIR
) -> tuple[TableId, str] | None:
    """The first of `query.relations` (not the whole schema) declaring this
    column name — narrower and less ambiguous than `adapters.sql.parser`'s own
    schema-wide search, since a `QueryIR` already knows which tables it reads.
    """
    by_id = {table.id: table for table in schema.tables}
    for relation in relations:
        table = by_id.get(relation)
        if table is None:
            continue
        for column in table.columns:
            if column.name == name:
                return relation, column.data_type
    return None


def _kind_for(operator: str, data_type: str) -> PredicateKind | None:
    base = _base_type(data_type)
    if operator == "=":
        return PredicateKind.EQUALITY
    if operator in _RANGE_OPERATORS:
        if base in _INTEGER_TYPES or base in _NUMERIC_TYPES:
            return PredicateKind.NUMERIC_RANGE
        if base in _TIMESTAMP_TYPES:
            return PredicateKind.TIMESTAMP_RANGE
    return None


def extract_predicates(query: QueryIR, *, schema: SchemaIR) -> tuple[ExtractedPredicate, ...]:
    """`query.normalized_sql`'s recognized `column <op> $N` predicates.

    A predicate whose column cannot be resolved against `query.relations`, or
    whose operator/type combination this module does not characterize
    (`BETWEEN`, `IN`, `LIKE`, a boolean/text/json column compared with `<`),
    is silently absent from the result — never guessed at.
    """
    try:
        parsed = parse_sql(query.normalized_sql)
    except ParseError:
        return ()
    if not parsed:
        return ()
    where = getattr(parsed[0].stmt, "whereClause", None)
    if where is None:
        return ()
    finder = _PredicateFinder()
    finder(where)

    predicates: list[ExtractedPredicate] = []
    for name, operator, position in finder.found:
        resolved = _resolve_column(name, query.relations, schema)
        if resolved is None:
            continue
        table, data_type = resolved
        kind = _kind_for(operator, data_type)
        if kind is None:
            continue
        predicates.append(
            ExtractedPredicate(
                table=table,
                column=column_id(table, name),
                parameter_position=position,
                operator=operator,
                kind=kind,
            )
        )
    return tuple(predicates)

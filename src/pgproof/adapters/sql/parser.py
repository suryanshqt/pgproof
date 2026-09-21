"""PostgreSQL SQL parsing and query identity. `docs/TECHNICAL_DESIGN.md:274-290`.

DBAPI placeholder canonicalization (psycopg's own pyformat markers, `%s` and
`%(name)s` — the only style this project's own driver ever produces) happens
before `pglast` ever sees the text, since `%s` is not valid PostgreSQL syntax
on its own. Parsing itself is `pglast` (`libpg_query`, PostgreSQL's real
grammar), not a hand-rolled one — literal replacement, relation collection,
and statement classification below all walk the real parse tree, not the raw
text.

Supported: a single statement (a `;`-separated batch is `UNSUPPORTED`, not
silently reduced to its first statement); literal replacement preserving
type casts and operators; relation resolution against a caller-supplied
`SchemaIR` (unqualified names default to `public`, matching this project's
`DEFAULT_SCHEMA` convention elsewhere); best-effort parameter-type inference
from a `column <op> $N` (or reversed) comparison, matched against
`schema.tables[*].columns` across every table regardless of which table the
column actually belongs to — a real, accepted limitation for a query joining
two tables that happen to share a column name; `"unknown"` when no match is
found, never a guess at a fabricated type. Functions, procedures, and
statements the physical catalog's own capture won't reach are explicitly
outside this PR's scope; anything `pglast` itself cannot parse becomes a
`QueryIR` with `statement_class=UNSUPPORTED` and `parse_error` set, never
dropped silently, per `docs/TECHNICAL_DESIGN.md:290`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pglast import ast, stream, visitors
from pglast.parser import ParseError, Token, parse_sql, scan

from pgproof.adapters.sql.fingerprint import fingerprint_query
from pgproof.domain.identifiers import TableId, table_id
from pgproof.domain.ir.schema import SchemaIR
from pgproof.domain.ir.workload import ParameterDescriptor, QueryIR, StatementClass
from pgproof.domain.sources import SourceRef

_DEFAULT_SCHEMA: Final = "public"

_STATEMENT_CLASS_BY_NODE: Final[dict[str, StatementClass]] = {
    "SelectStmt": StatementClass.READ,
    "InsertStmt": StatementClass.WRITE,
    "UpdateStmt": StatementClass.WRITE,
    "DeleteStmt": StatementClass.WRITE,
    "MergeStmt": StatementClass.WRITE,
    "CreateStmt": StatementClass.SCHEMA,
    "CreateTableAsStmt": StatementClass.SCHEMA,
    "AlterTableStmt": StatementClass.SCHEMA,
    "DropStmt": StatementClass.SCHEMA,
    "TruncateStmt": StatementClass.SCHEMA,
    "CreateSchemaStmt": StatementClass.SCHEMA,
    "IndexStmt": StatementClass.SCHEMA,
    "RenameStmt": StatementClass.SCHEMA,
    "TransactionStmt": StatementClass.TRANSACTION,
    "VariableSetStmt": StatementClass.CONTROL,
    "VariableShowStmt": StatementClass.CONTROL,
    "ExplainStmt": StatementClass.CONTROL,
}


def canonicalize_placeholders(sql: str) -> str:
    """Rewrite psycopg pyformat markers (`%s`, `%(name)s`) to PostgreSQL's own
    positional syntax (`$1`, `$2`, ...), the only form `pglast` can parse.

    Token-scanner-based, not a regex: a `%` inside a string literal (e.g. a
    `LIKE` pattern, `'%foo%'`) is already fused into that literal's own
    token by the scanner and never seen as a standalone `%`, so it cannot be
    mistaken for a placeholder — verified directly, not assumed.
    """
    tokens = scan(sql)
    replacements: list[tuple[int, int, str]] = []
    count = 0
    index = 0
    total = len(tokens)
    while index < total:
        token = tokens[index]
        if token.name != "ASCII_37":
            index += 1
            continue
        if _matches_named(tokens, index, sql):
            end = tokens[index + 4]
            count += 1
            replacements.append((token.start, end.end + 1, f"${count}"))
            index += 5
            continue
        if _matches_positional(tokens, index, sql):
            end = tokens[index + 1]
            count += 1
            replacements.append((token.start, end.end + 1, f"${count}"))
            index += 2
            continue
        index += 1
    if not replacements:
        return sql
    return _apply_replacements(sql, replacements)


def _text(sql: str, token: Token) -> str:
    return sql[token.start : token.end + 1]


def _adjacent(a: Token, b: Token) -> bool:
    return b.start == a.end + 1


def _matches_positional(tokens: Sequence[Token], index: int, sql: str) -> bool:
    if index + 1 >= len(tokens):
        return False
    marker = tokens[index + 1]
    return marker.name == "IDENT" and _text(sql, marker) == "s" and _adjacent(tokens[index], marker)


def _matches_named(tokens: Sequence[Token], index: int, sql: str) -> bool:
    if index + 4 >= len(tokens):
        return False
    open_paren, name, close_paren, marker = tokens[index + 1 : index + 5]
    # `name`'s token type is not checked: a placeholder name that happens to be
    # a reserved SQL keyword (e.g. `%(limit)s`) scans as that keyword's own
    # token, not IDENT — its type is irrelevant here since only `count` is used.
    return (
        open_paren.name == "ASCII_40"
        and close_paren.name == "ASCII_41"
        and marker.name == "IDENT"
        and _text(sql, marker) == "s"
        and _adjacent(tokens[index], open_paren)
        and _adjacent(open_paren, name)
        and _adjacent(name, close_paren)
        and _adjacent(close_paren, marker)
    )


def _apply_replacements(sql: str, replacements: Sequence[tuple[int, int, str]]) -> str:
    parts: list[str] = []
    cursor = 0
    for start, end, replacement in replacements:
        parts.append(sql[cursor:start])
        parts.append(replacement)
        cursor = end
    parts.append(sql[cursor:])
    return "".join(parts)


class _MaxParamNumber(visitors.Visitor):
    """The highest `ParamRef.number` already present — a query canonicalized
    from `%s`/`%(name)s` arrives with these already in place; a literal
    constant only ever needs a number past whatever they already claimed."""

    def __init__(self) -> None:
        super().__init__()
        self.value = 0

    def visit_ParamRef(self, _ancestors: object, node: ast.ParamRef) -> None:  # noqa: N802
        self.value = max(self.value, node.number)


class _LiteralStripper(visitors.Visitor):
    """Replaces every `A_Const` with a sequential `ParamRef`, leaving type
    casts and operators untouched — `docs/TECHNICAL_DESIGN.md:283`'s
    "preserving type casts/operators". Numbering starts after any `ParamRef`s
    already in the tree, so a query mixing DBAPI placeholders and literals
    never collides two parameters onto the same number.
    """

    def __init__(self, starting_count: int = 0) -> None:
        super().__init__()
        self.count = starting_count

    def visit_A_Const(self, _ancestors: object, _node: object) -> ast.ParamRef:  # noqa: N802
        self.count += 1
        return ast.ParamRef(number=self.count)  # type: ignore[no-untyped-call]


class _ParamColumnFinder(visitors.Visitor):
    """Best-effort: a `column <op> $N` (either side) comparison names which
    column a parameter was compared against."""

    def __init__(self) -> None:
        super().__init__()
        self.param_columns: dict[int, str] = {}

    def visit_A_Expr(self, _ancestors: object, node: ast.A_Expr) -> None:  # noqa: N802
        left_column, left_param = _column_and_param(node.lexpr)
        right_column, right_param = _column_and_param(node.rexpr)
        if left_column is not None and right_param is not None:
            self.param_columns[right_param] = left_column
        elif right_column is not None and left_param is not None:
            self.param_columns[left_param] = right_column


def _column_and_param(node: object) -> tuple[str | None, int | None]:
    if isinstance(node, ast.ColumnRef):
        last = node.fields[-1]
        return (last.sval if isinstance(last, ast.String) else None, None)
    if isinstance(node, ast.ParamRef):
        return None, node.number
    return None, None


def _resolve_relation(raw_name: str, schema: SchemaIR) -> TableId | None:
    name = raw_name.strip('"')
    if "." in name:
        schema_part, _, table_part = name.rpartition(".")
        schema_part = schema_part.strip('"') or _DEFAULT_SCHEMA
        table_part = table_part.strip('"')
    else:
        schema_part, table_part = _DEFAULT_SCHEMA, name
    for table in schema.tables:
        if table.schema_name == schema_part and table.name == table_part:
            return table_id(table.schema_name, table.name)
    return None


def _infer_data_type(column_name: str | None, schema: SchemaIR) -> str:
    if column_name is None:
        return "unknown"
    for table in schema.tables:
        for column in table.columns:
            if column.name == column_name:
                return column.data_type
    return "unknown"


def _unsupported(sql: str, reason: str, call_sites: tuple[SourceRef, ...]) -> QueryIR:
    # `sql` falls back to a placeholder when empty: `NonEmptyText` rejects "",
    # and an empty query is itself an unsupported-but-real case, not an error.
    normalized_sql = sql or "<empty>"
    return QueryIR(
        id=fingerprint_query(normalized_sql, (), ()),
        statement_class=StatementClass.UNSUPPORTED,
        normalized_sql=normalized_sql,
        call_sites=call_sites,
        parse_error=reason,
    )


def parse_query(sql: str, *, schema: SchemaIR, call_sites: Sequence[SourceRef] = ()) -> QueryIR:
    """`docs/TECHNICAL_DESIGN.md:274-290`'s nine-step pipeline, driven by a
    caller-supplied `SchemaIR` for relation/parameter-type resolution — never
    a live database connection (this module performs no I/O at all)."""
    sites = tuple(call_sites)
    canonical_input = canonicalize_placeholders(sql)
    try:
        parsed = parse_sql(canonical_input)
    except ParseError as exc:
        return _unsupported(sql, str(exc), sites)
    if len(parsed) != 1:
        return _unsupported(sql, "exactly one statement is required, found a batch", sites)

    stmt = parsed[0].stmt
    statement_class = _STATEMENT_CLASS_BY_NODE.get(type(stmt).__name__, StatementClass.UNSUPPORTED)

    existing_params = _MaxParamNumber()
    existing_params(stmt)
    stripper = _LiteralStripper(starting_count=existing_params.value)
    mutated = stripper(stmt)
    normalized_sql = stream.RawStream()(mutated)  # type: ignore[no-untyped-call]

    raw_relations = visitors.referenced_relations(mutated)  # type: ignore[no-untyped-call]
    resolved_relations = tuple(
        sorted(
            {
                resolved
                for name in raw_relations
                if (resolved := _resolve_relation(name, schema)) is not None
            }
        )
    )

    finder = _ParamColumnFinder()
    finder(mutated)
    parameters = tuple(
        ParameterDescriptor(
            position=position,
            data_type=_infer_data_type(finder.param_columns.get(position), schema),
        )
        for position in range(1, stripper.count + 1)
    )

    fingerprint = fingerprint_query(
        normalized_sql, resolved_relations, tuple(p.data_type for p in parameters)
    )
    return QueryIR(
        id=fingerprint,
        statement_class=statement_class,
        normalized_sql=normalized_sql,
        relations=resolved_relations,
        parameters=parameters,
        call_sites=sites,
    )

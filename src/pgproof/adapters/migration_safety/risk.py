"""Migration risk classification. `docs/PR_ROADMAP.md`'s BE-31: destructive/
constraint/type/index risks, version-sensitive lock/rewrite facts,
reversibility, and expand-contract template linkage — never an invented
production duration.

Walks `op.<method>(...)` calls independently of `adapters.repository.
alembic_static`'s own replay engine (that module's operation extraction is
private, and reused here would couple a read-only risk assessment to a
schema-replay engine's internals for no shared benefit). Only the specific
`op.*` methods and keyword arguments a risk rule below actually reads are
resolved; anything else in the call is ignored, not guessed at.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Final

from pgproof.domain.primitives import SnakeCaseEnum
from pgproof.domain.recommendations import ChangeKind
from pgproof.domain.sources import SourceRef

_LOCK_FACT_ASSUMPTION: Final = (
    "assumes PostgreSQL 11+: a constant DEFAULT on a new column is metadata-only; "
    "an added NOT NULL column with no default, or a volatile default, still requires "
    "a full table scan to validate or populate existing rows"
)
_TYPE_CHANGE_ASSUMPTION: Final = (
    "ALTER COLUMN TYPE rewrites the table unless the old and new types are binary "
    "coercible, which this analysis cannot verify statically"
)


class RiskCategory(SnakeCaseEnum):
    DESTRUCTIVE = "destructive"
    CONSTRAINT = "constraint"
    TYPE_CHANGE = "type_change"
    INDEX = "index"


@dataclass(frozen=True)
class MigrationRisk:
    revision: str
    operation: str
    category: RiskCategory
    reason: str
    reversible: bool
    assumption: str | None
    expand_contract_change_kind: ChangeKind | None
    source: SourceRef


def _op_call(node: ast.AST) -> ast.Call | None:
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return None
    call = node.value
    func = call.func
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "op"
    ):
        return call
    return None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _bool_keyword(call: ast.Call, name: str) -> bool:
    value = _keyword(call, name)
    return isinstance(value, ast.Constant) and value.value is True


def _has_keyword(call: ast.Call, name: str) -> bool:
    return _keyword(call, name) is not None


# Alembic's own signatures disagree on which positional argument is the
# table: `create_table`/`drop_table`/`add_column`/`drop_column`/
# `alter_column` take the table first, but every constraint/index method
# takes the constraint or index *name* first and the table second
# (`create_foreign_key(name, source_table, referent_table, ...)`,
# `create_unique_constraint(name, table_name, columns, ...)`,
# `create_index(index_name, table_name, columns, ...)`, likewise
# `drop_constraint`/`drop_index`). Verified against each method's real
# Alembic signature, not assumed uniform.
_TABLE_ARGUMENT_INDEX: Final[dict[str, int]] = {
    "create_table": 0,
    "drop_table": 0,
    "add_column": 0,
    "drop_column": 0,
    "alter_column": 0,
    "create_unique_constraint": 1,
    "create_foreign_key": 1,
    "create_check_constraint": 1,
    "drop_constraint": 1,
    "create_index": 1,
    "drop_index": 1,
}


def _target_table(call: ast.Call, method: str) -> str | None:
    index = _TABLE_ARGUMENT_INDEX.get(method)
    if index is None or len(call.args) <= index:
        return None
    argument = call.args[index]
    if not isinstance(argument, ast.Constant):
        return None
    return argument.value if isinstance(argument.value, str) else None


def _created_tables(upgrade_fn: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    created: set[str] = set()
    for node in ast.walk(upgrade_fn):
        call = _op_call(node)
        if call is None:
            continue
        func = call.func
        assert isinstance(func, ast.Attribute)
        if func.attr != "create_table":
            continue
        table = _target_table(call, "create_table")
        if table is not None:
            created.add(table)
    return frozenset(created)


def _assess_call(
    call: ast.Call, *, revision: str, source: SourceRef, created_tables: frozenset[str]
) -> MigrationRisk | None:
    func = call.func
    assert isinstance(func, ast.Attribute)
    method = func.attr

    # A table created earlier in this same `upgrade()` holds no pre-existing
    # rows yet, so every constraint/column/index risk below — all of which
    # are about validating or locking *existing* data — does not apply to
    # it. `drop_table` is the one exception: dropping whatever the table
    # holds is destructive regardless of when the table was created.
    target = _target_table(call, method)
    if method != "drop_table" and target is not None and target in created_tables:
        return None

    if method == "drop_table":
        return MigrationRisk(
            revision=revision,
            operation=method,
            category=RiskCategory.DESTRUCTIVE,
            reason="drops a table and every row it holds; there is no automatic undo",
            reversible=False,
            assumption=None,
            expand_contract_change_kind=None,
            source=source,
        )
    if method == "drop_column":
        return MigrationRisk(
            revision=revision,
            operation=method,
            category=RiskCategory.DESTRUCTIVE,
            reason="drops a column and every value it holds; there is no automatic undo",
            reversible=False,
            assumption=None,
            expand_contract_change_kind=None,
            source=source,
        )
    if method == "drop_constraint":
        return MigrationRisk(
            revision=revision,
            operation=method,
            category=RiskCategory.CONSTRAINT,
            reason="removes a constraint; re-adding it later re-validates every existing row",
            reversible=True,
            assumption=None,
            expand_contract_change_kind=None,
            source=source,
        )
    if method in ("create_unique_constraint", "create_foreign_key", "create_check_constraint"):
        return MigrationRisk(
            revision=revision,
            operation=method,
            category=RiskCategory.CONSTRAINT,
            reason="a new constraint, added directly, validates every existing row while held",
            reversible=True,
            assumption=None,
            expand_contract_change_kind=ChangeKind.ADD_CONSTRAINT,
            source=source,
        )
    if method == "add_column":
        # `nullable=`/`server_default=` are keywords on the nested
        # `sa.Column(...)` call (`op.add_column`'s second positional
        # argument), not on `op.add_column(...)` itself.
        column_call = (
            call.args[1] if len(call.args) > 1 and isinstance(call.args[1], ast.Call) else None
        )
        not_null = (
            column_call is not None
            and not _bool_keyword(column_call, "nullable")
            and _has_keyword(column_call, "nullable")
        )
        has_default = column_call is not None and _has_keyword(column_call, "server_default")
        if not_null and not has_default:
            return MigrationRisk(
                revision=revision,
                operation=method,
                category=RiskCategory.CONSTRAINT,
                reason="a NOT NULL column with no default requires a full table scan "
                "to populate existing rows before the constraint can be enforced",
                reversible=True,
                assumption=_LOCK_FACT_ASSUMPTION,
                expand_contract_change_kind=None,
                source=source,
            )
        return None
    if method == "alter_column" and _has_keyword(call, "type_"):
        return MigrationRisk(
            revision=revision,
            operation=method,
            category=RiskCategory.TYPE_CHANGE,
            reason="changes a column's declared type",
            reversible=False,
            assumption=_TYPE_CHANGE_ASSUMPTION,
            expand_contract_change_kind=ChangeKind.ALTER_COLUMN,
            source=source,
        )
    if method == "create_index":
        if _bool_keyword(call, "postgresql_concurrently"):
            return None
        return MigrationRisk(
            revision=revision,
            operation=method,
            category=RiskCategory.INDEX,
            reason="an ordinary CREATE INDEX holds a lock that blocks writes to this "
            "table for the duration of the build; CREATE INDEX CONCURRENTLY does not",
            reversible=True,
            assumption=None,
            expand_contract_change_kind=ChangeKind.ADD_INDEX,
            source=source,
        )
    return None


def _upgrade_function(tree: ast.Module) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "upgrade":
            return node
    return None


def assess_migration(
    source_text: str, *, revision: str, source: SourceRef
) -> tuple[MigrationRisk, ...]:
    """Every risk this module recognizes in one migration file's `upgrade()`
    only — `downgrade()` ordinarily mirrors `upgrade()`'s own operations in
    reverse (an `upgrade()` `create_table` paired with a `downgrade()`
    `drop_table` is the normal, expected shape, not a second destructive risk
    to report). An operation this function does not recognize is silently not
    a risk it reports — never a guess at severity for a shape it cannot
    characterize.
    """
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return ()
    upgrade_fn = _upgrade_function(tree)
    if upgrade_fn is None:
        return ()
    created_tables = _created_tables(upgrade_fn)
    risks: list[MigrationRisk] = []
    for node in ast.walk(upgrade_fn):
        call = _op_call(node)
        if call is None:
            continue
        risk = _assess_call(call, revision=revision, source=source, created_tables=created_tables)
        if risk is not None:
            risks.append(risk)
    return tuple(risks)

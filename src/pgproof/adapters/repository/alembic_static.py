"""Static Alembic revision graph and operation parsing, `docs/TECHNICAL_DESIGN.md` section 6.

AST-only: a revision module is parsed as syntax and never imported. Direct
`op.<name>(...)` calls at the top level of `upgrade()`, with literal
arguments, resolve to a typed operation; anything else — a helper wrapper, a
conditional or loop, a non-literal argument, `op.execute` — becomes an
`UnsupportedConstruct` rather than a guess.

The revision graph is analysed independently of whether it replays cleanly:
`docs/ARCHITECTURE.md`'s "Multiple heads are reported; execution never
auto-selects one" means the cumulative `SchemaIR` is only built when the
graph resolves to exactly one head with no cycle and no missing predecessor.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, TypeGuard

from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.schema import (
    ColumnIR,
    ConstraintIR,
    ConstraintKind,
    IndexIR,
    IndexKeyIR,
    ReferentialAction,
    SchemaIR,
    SchemaProvenance,
    TableIR,
    UnsupportedConstruct,
)
from pgproof.domain.sources import SourceRef

DEFAULT_SCHEMA: Final = "public"

_UNRESOLVED: Final = object()

_ON_ACTION: Final[dict[str, ReferentialAction]] = {
    "CASCADE": ReferentialAction.CASCADE,
    "RESTRICT": ReferentialAction.RESTRICT,
    "SET NULL": ReferentialAction.SET_NULL,
    "SET DEFAULT": ReferentialAction.SET_DEFAULT,
    "NO ACTION": ReferentialAction.NO_ACTION,
}


@dataclass(frozen=True)
class RevisionInfo:
    revision: str
    down_revisions: tuple[str, ...]
    branch_labels: tuple[str, ...]
    depends_on: tuple[str, ...]
    message: str | None
    source: SourceRef


@dataclass(frozen=True)
class RevisionGraphReport:
    revisions: tuple[str, ...]
    roots: tuple[str, ...]
    heads: tuple[str, ...]
    merge_revisions: tuple[str, ...]
    missing_predecessors: tuple[str, ...]
    cycle: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlembicStaticResult:
    revisions: tuple[RevisionInfo, ...]
    graph: RevisionGraphReport
    schema: SchemaIR


def _content_hash(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def parse_migrations(version_paths: list[Path], *, root: Path) -> AlembicStaticResult:
    """Parse every path as a candidate Alembic revision module.

    A file with no module-level `revision` assignment is silently skipped: it
    is not a revision module (`env.py`, a helper module alongside `versions/`).
    """
    revisions: list[RevisionInfo] = []
    operations: dict[str, list[_Operation]] = {}
    file_level_unsupported: list[UnsupportedConstruct] = []

    for path in sorted(version_paths):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        source = SourceRef(path=relative, content_hash=_content_hash(text))
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            file_level_unsupported.append(
                UnsupportedConstruct(
                    kind="unparseable_migration", reason="syntax error", source=source
                )
            )
            continue

        info = _extract_revision_info(tree, source)
        if info is None:
            continue
        revisions.append(info)
        operations[info.revision] = _extract_operations(tree, source)

    graph = _build_graph(revisions)
    schema, replay_unsupported = _replay(revisions, operations, graph)
    schema = schema.model_copy(
        update={
            "unsupported": schema.unsupported + tuple(file_level_unsupported) + replay_unsupported
        }
    )
    return AlembicStaticResult(revisions=tuple(revisions), graph=graph, schema=schema)


# --------------------------------------------------------------------------- #
# Revision metadata
# --------------------------------------------------------------------------- #
def _literal(node: ast.expr) -> object:
    """A statically resolvable literal, or `_UNRESOLVED`."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        values = [_literal(elt) for elt in node.elts]
        if any(value is _UNRESOLVED for value in values):
            return _UNRESOLVED
        return tuple(values) if isinstance(node, ast.Tuple) else list(values)
    return _UNRESOLVED


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if value is None or value is _UNRESOLVED:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _module_assignments(tree: ast.Module) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        values[node.targets[0].id] = _literal(node.value)
    return values


def _extract_revision_info(tree: ast.Module, source: SourceRef) -> RevisionInfo | None:
    values = _module_assignments(tree)
    revision = values.get("revision")
    if not isinstance(revision, str):
        return None
    message = ast.get_docstring(tree)
    return RevisionInfo(
        revision=revision,
        down_revisions=_as_str_tuple(values.get("down_revision")),
        branch_labels=_as_str_tuple(values.get("branch_labels")),
        depends_on=_as_str_tuple(values.get("depends_on")),
        message=message.splitlines()[0] if message else None,
        source=source,
    )


# --------------------------------------------------------------------------- #
# Revision graph
# --------------------------------------------------------------------------- #
def _build_graph(revisions: list[RevisionInfo]) -> RevisionGraphReport:
    known = {info.revision for info in revisions}
    children: dict[str, list[str]] = {info.revision: [] for info in revisions}
    missing: set[str] = set()
    for info in revisions:
        for parent in info.down_revisions:
            if parent in known:
                children[parent].append(info.revision)
            else:
                missing.add(parent)

    roots = tuple(sorted(info.revision for info in revisions if not info.down_revisions))
    heads = tuple(sorted(rev for rev in known if not children.get(rev)))
    merges = tuple(sorted(info.revision for info in revisions if len(info.down_revisions) > 1))
    cycle = _find_cycle(revisions)

    return RevisionGraphReport(
        revisions=tuple(sorted(known)),
        roots=roots,
        heads=heads,
        merge_revisions=merges,
        missing_predecessors=tuple(sorted(missing)),
        cycle=cycle,
    )


def _find_cycle(revisions: list[RevisionInfo]) -> tuple[str, ...]:
    parents = {info.revision: info.down_revisions for info in revisions}
    unvisited = set(parents)
    in_stack: dict[str, int] = {}

    def _walk(node: str, stack: list[str]) -> tuple[str, ...]:
        if node in in_stack:
            return tuple(stack[in_stack[node] :])
        if node not in parents:
            return ()
        in_stack[node] = len(stack)
        stack.append(node)
        for parent in parents[node]:
            found = _walk(parent, stack)
            if found:
                return found
        stack.pop()
        del in_stack[node]
        return ()

    for start in list(unvisited):
        found = _walk(start, [])
        if found:
            return found
    return ()


# --------------------------------------------------------------------------- #
# Operation extraction
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Operation:
    kind: str
    args: dict[str, Any]
    source: SourceRef


def _call_in_statement(node: ast.stmt) -> ast.Call | None:
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        return node.value
    return None


def _op_method_name(call: ast.Call) -> str | None:
    func = call.func
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "op"
    ):
        return func.attr
    return None


_SUPPORTED_OPS: Final = frozenset(
    {
        "create_table",
        "drop_table",
        "rename_table",
        "add_column",
        "drop_column",
        "alter_column",
        "create_primary_key",
        "create_foreign_key",
        "create_unique_constraint",
        "create_check_constraint",
        "drop_constraint",
        "create_index",
        "drop_index",
        "execute",
    }
)


def _resolve_call_args(call: ast.Call) -> dict[str, Any] | None:
    """Positional args as `_0`, `_1`, ...; keyword args by name. `None` if any is unresolvable."""
    resolved: dict[str, Any] = {}
    for index, arg in enumerate(call.args):
        value = _literal(arg) if not _is_column_call(arg) else _resolve_column(arg)
        if value is _UNRESOLVED:
            return None
        resolved[f"_{index}"] = value
    for keyword in call.keywords:
        if keyword.arg is None:
            return None
        value = _literal(keyword.value)
        if value is _UNRESOLVED:
            # server_default and type expressions are recorded as source text,
            # not rejected: `docs/TECHNICAL_DESIGN.md` does not require a full
            # SQLAlchemy type/expression model, only the operation's identity.
            if keyword.arg in {"server_default", "type_"}:
                resolved[keyword.arg] = ast.unparse(keyword.value)
                continue
            return None
        resolved[keyword.arg] = value
    return resolved


def _is_column_call(node: ast.expr) -> TypeGuard[ast.Call]:
    return isinstance(node, ast.Call) and _callee_name(node.func) == "Column"


def _callee_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _resolve_column(call: ast.Call) -> dict[str, object] | object:
    if (
        not call.args
        or not isinstance(call.args[0], ast.Constant)
        or not isinstance(call.args[0].value, str)
    ):
        return _UNRESOLVED
    name = call.args[0].value
    type_text = ast.unparse(call.args[1]) if len(call.args) > 1 else "unknown"
    nullable: Any = True
    primary_key = False
    server_default: str | None = None
    for keyword in call.keywords:
        if keyword.arg == "nullable":
            value = _literal(keyword.value)
            nullable = True if value is _UNRESOLVED else value
        elif keyword.arg == "primary_key":
            value = _literal(keyword.value)
            primary_key = bool(value) if value is not _UNRESOLVED else False
        elif keyword.arg == "server_default":
            server_default = ast.unparse(keyword.value)
    return {
        "name": name,
        "type_text": type_text,
        "nullable": bool(nullable),
        "primary_key": primary_key,
        "server_default": server_default,
    }


def _extract_operations(tree: ast.Module, source: SourceRef) -> list[_Operation]:
    upgrade_fn = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "upgrade"
        ),
        None,
    )
    if upgrade_fn is None:
        return []

    operations: list[_Operation] = []
    for statement in upgrade_fn.body:
        call = _call_in_statement(statement)
        method = _op_method_name(call) if call is not None else None
        line_source = SourceRef(
            path=source.path, line=statement.lineno, content_hash=source.content_hash
        )

        if call is None or method is None:
            operations.append(
                _Operation(
                    kind="unsupported",
                    args={"reason": "not a direct op.<name>(...) call"},
                    source=line_source,
                )
            )
            continue
        if method not in _SUPPORTED_OPS:
            operations.append(
                _Operation(
                    kind="unsupported",
                    args={"reason": f"op.{method} is not modeled"},
                    source=line_source,
                )
            )
            continue
        resolved = _resolve_call_args(call)
        if resolved is None:
            operations.append(
                _Operation(
                    kind="unsupported",
                    args={"reason": f"op.{method} has a non-literal argument"},
                    source=line_source,
                )
            )
            continue
        if method == "execute":
            operations.append(
                _Operation(
                    kind="unsupported",
                    args={"reason": "op.execute payload not statically interpreted"},
                    source=line_source,
                )
            )
            continue
        operations.append(_Operation(kind=method, args=resolved, source=line_source))
    return operations


# --------------------------------------------------------------------------- #
# Schema replay
# --------------------------------------------------------------------------- #
@dataclass
class _TableState:
    columns: dict[str, ColumnIR] = field(default_factory=dict)
    name: str = ""


def _replay(
    revisions: list[RevisionInfo],
    operations: dict[str, list[_Operation]],
    graph: RevisionGraphReport,
) -> tuple[SchemaIR, tuple[UnsupportedConstruct, ...]]:
    all_revision_ids = tuple(sorted(info.revision for info in revisions))
    unsupported: list[UnsupportedConstruct] = []
    for info in revisions:
        for op_item in operations.get(info.revision, []):
            if op_item.kind == "unsupported":
                unsupported.append(
                    UnsupportedConstruct(
                        kind="migration_operation",
                        reason=op_item.args["reason"],
                        source=op_item.source,
                    )
                )

    if not revisions:
        return SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION), tuple(unsupported)

    if graph.cycle or graph.missing_predecessors or len(graph.heads) != 1:
        note = (
            "a revision cycle"
            if graph.cycle
            else (
                "a missing predecessor"
                if graph.missing_predecessors
                else f"{len(graph.heads)} heads"
            )
        )
        unsupported.append(
            UnsupportedConstruct(
                kind="ambiguous_revision_graph",
                reason=f"schema not replayed: the revision graph has {note}",
            )
        )
        return (
            SchemaIR(
                provenance=SchemaProvenance.STATIC_MIGRATION, migration_revisions=all_revision_ids
            ),
            tuple(unsupported),
        )

    order = _topological_order(revisions, graph)
    tables: dict[str, _TableState] = {}
    constraints: dict[str, ConstraintIR] = {}
    indexes: dict[str, IndexIR] = {}

    for revision_id in order:
        for op_item in operations.get(revision_id, []):
            if op_item.kind == "unsupported":
                continue
            _apply(op_item, revision_id, tables, constraints, indexes, unsupported)

    table_irs = tuple(
        TableIR(
            id=table_id(DEFAULT_SCHEMA, state.name),
            schema_name=DEFAULT_SCHEMA,
            name=state.name,
            columns=tuple(state.columns.values()),
            provenance=SchemaProvenance.STATIC_MIGRATION,
        )
        for state in tables.values()
    )
    schema = SchemaIR(
        provenance=SchemaProvenance.STATIC_MIGRATION,
        tables=table_irs,
        constraints=tuple(constraints.values()),
        indexes=tuple(indexes.values()),
        migration_head=graph.heads[0],
        migration_revisions=all_revision_ids,
    )
    return schema, tuple(unsupported)


def _topological_order(revisions: list[RevisionInfo], graph: RevisionGraphReport) -> list[str]:
    by_id = {info.revision: info for info in revisions}
    ordered: list[str] = []
    seen: set[str] = set()

    def _visit(revision_id: str) -> None:
        if revision_id in seen:
            return
        seen.add(revision_id)
        for parent in by_id[revision_id].down_revisions:
            _visit(parent)
        ordered.append(revision_id)

    _visit(graph.heads[0])
    return ordered


def _apply(
    op_item: _Operation,
    revision_id: str,
    tables: dict[str, _TableState],
    constraints: dict[str, ConstraintIR],
    indexes: dict[str, IndexIR],
    unsupported: list[UnsupportedConstruct],
) -> None:
    args = op_item.args
    if op_item.kind == "create_table":
        name = args["_0"]
        created = _TableState(name=name)
        for key, value in args.items():
            if key == "_0" or not isinstance(value, dict):
                continue
            column = _column_ir(name, value)
            created.columns[value["name"]] = column
            if value["primary_key"]:
                constraints[f"pk_{name}"] = ConstraintIR(
                    name=f"pk_{name}",
                    kind=ConstraintKind.PRIMARY_KEY,
                    table=table_id(DEFAULT_SCHEMA, name),
                    columns=(column_id(table_id(DEFAULT_SCHEMA, name), value["name"]),),
                    provenance=SchemaProvenance.STATIC_MIGRATION,
                    introduced_by=revision_id,
                )
        tables[name] = created
    elif op_item.kind == "drop_table":
        tables.pop(args["_0"], None)
        for name in [
            n for n, c in constraints.items() if c.table == table_id(DEFAULT_SCHEMA, args["_0"])
        ]:
            del constraints[name]
        for name in [
            n for n, i in indexes.items() if i.table == table_id(DEFAULT_SCHEMA, args["_0"])
        ]:
            del indexes[name]
    elif op_item.kind == "rename_table":
        # ponytail: does not rewrite `table`/`referenced_table` on constraints
        # or indexes already recorded against the old name; a later operation
        # on the renamed table's dependents would misattribute. Upgrade path:
        # index constraints/indexes by table when this is observed in a real
        # migration.
        old, new = args["_0"], args["_1"]
        renamed = tables.pop(old, None)
        if renamed is not None:
            renamed.name = new
            tables[new] = renamed
    elif op_item.kind == "add_column":
        table_name = args["_0"]
        target = tables.get(table_name)
        if target is None:
            unsupported.append(
                UnsupportedConstruct(
                    kind="migration_operation",
                    reason=f"add_column on unknown table {table_name!r}",
                    source=op_item.source,
                )
            )
            return
        column = _column_ir(table_name, args["_1"])
        target.columns[args["_1"]["name"]] = column
    elif op_item.kind == "drop_column":
        table_name = args["_0"]
        existing = tables.get(table_name)
        if existing is not None:
            existing.columns.pop(args["_1"], None)
    elif op_item.kind == "alter_column":
        _apply_alter_column(args, tables)
    elif op_item.kind == "create_primary_key":
        constraints[args["_0"]] = ConstraintIR(
            name=args["_0"],
            kind=ConstraintKind.PRIMARY_KEY,
            table=table_id(DEFAULT_SCHEMA, args["_1"]),
            columns=tuple(column_id(table_id(DEFAULT_SCHEMA, args["_1"]), c) for c in args["_2"]),
            provenance=SchemaProvenance.STATIC_MIGRATION,
            introduced_by=revision_id,
        )
    elif op_item.kind == "create_foreign_key":
        on_delete = _ON_ACTION.get(str(args.get("ondelete", "")).upper())
        on_update = _ON_ACTION.get(str(args.get("onupdate", "")).upper())
        constraints[args["_0"]] = ConstraintIR(
            name=args["_0"],
            kind=ConstraintKind.FOREIGN_KEY,
            table=table_id(DEFAULT_SCHEMA, args["_1"]),
            columns=tuple(column_id(table_id(DEFAULT_SCHEMA, args["_1"]), c) for c in args["_3"]),
            referenced_table=table_id(DEFAULT_SCHEMA, args["_2"]),
            referenced_columns=tuple(
                column_id(table_id(DEFAULT_SCHEMA, args["_2"]), c) for c in args["_4"]
            ),
            on_delete=on_delete,
            on_update=on_update,
            provenance=SchemaProvenance.STATIC_MIGRATION,
            introduced_by=revision_id,
        )
    elif op_item.kind == "create_unique_constraint":
        constraints[args["_0"]] = ConstraintIR(
            name=args["_0"],
            kind=ConstraintKind.UNIQUE,
            table=table_id(DEFAULT_SCHEMA, args["_1"]),
            columns=tuple(column_id(table_id(DEFAULT_SCHEMA, args["_1"]), c) for c in args["_2"]),
            provenance=SchemaProvenance.STATIC_MIGRATION,
            introduced_by=revision_id,
        )
    elif op_item.kind == "create_check_constraint":
        constraints[args["_0"]] = ConstraintIR(
            name=args["_0"],
            kind=ConstraintKind.CHECK,
            table=table_id(DEFAULT_SCHEMA, args["_1"]),
            expression=str(args["_2"]),
            provenance=SchemaProvenance.STATIC_MIGRATION,
            introduced_by=revision_id,
        )
    elif op_item.kind == "drop_constraint":
        constraints.pop(args["_0"], None)
    elif op_item.kind == "create_index":
        table_name = args.get("_1") or args.get("table_name")
        assert isinstance(table_name, str)
        columns = args.get("_2") or args.get("columns", [])
        indexes[args["_0"]] = IndexIR(
            name=args["_0"],
            table=table_id(DEFAULT_SCHEMA, table_name),
            keys=tuple(
                IndexKeyIR(column=column_id(table_id(DEFAULT_SCHEMA, table_name), c))
                for c in columns
            ),
            is_unique=bool(args.get("unique", False)),
            provenance=SchemaProvenance.STATIC_MIGRATION,
            introduced_by=revision_id,
        )
    elif op_item.kind == "drop_index":
        indexes.pop(args["_0"], None)


def _apply_alter_column(args: dict[str, Any], tables: dict[str, _TableState]) -> None:
    table_name, column_name = args["_0"], args["_1"]
    state = tables.get(table_name)
    if state is None or column_name not in state.columns:
        return
    current = state.columns[column_name]
    new_name = args.get("new_column_name", current.name)
    nullable = args.get("nullable", current.nullable)
    type_text = args.get("type_", current.data_type)
    server_default = args.get("server_default", current.default_expression)
    updated = current.model_copy(
        update={
            "id": column_id(table_id(DEFAULT_SCHEMA, table_name), new_name),
            "name": new_name,
            "nullable": bool(nullable),
            "data_type": type_text,
            "default_expression": server_default,
        }
    )
    del state.columns[column_name]
    state.columns[new_name] = updated


def _column_ir(table_name: str, spec: dict[str, Any]) -> ColumnIR:
    return ColumnIR(
        id=column_id(table_id(DEFAULT_SCHEMA, table_name), spec["name"]),
        name=spec["name"],
        data_type=spec["type_text"],
        nullable=spec["nullable"],
        default_expression=spec["server_default"],
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )

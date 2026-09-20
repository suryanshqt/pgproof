"""Static SQLAlchemy/SQLModel model analysis, `docs/TECHNICAL_DESIGN.md` section 7.

AST-only: a model module is parsed as syntax and never imported. A class is a
mapped model only if it declares `__tablename__` as a string literal, or sets
`table=True` (SQLModel), in which case the table name defaults to the class
name lowercased if `__tablename__` is absent.

Within a model body, a column resolves from a direct `Column(...)`,
`mapped_column(...)`, or `Field(...)` call (or, for SQLModel, a bare
annotation with no call) with every identifying argument a literal; a
`relationship(...)` call resolves the same way. Anything else — a helper
wrapper, a loop, a non-literal argument — becomes an `UnsupportedConstruct`.
`__tablename__`, `__table_args__`, `__mapper_args__`, and `__abstract__` are
recognized metadata, not columns, and are never flagged: `__table_args__`'s
composite constraints/indexes are not modeled in this PR (out of scope; see
the module's PR description), which is different from being unresolved.

A relationship's target table is resolved in a second pass across every
model this call was given, so a relationship to a class defined in another
file of the same call resolves; a target found nowhere becomes unsupported
rather than a guess.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from pgproof.adapters.repository._ast_helpers import UNRESOLVED, callee_name, content_hash, literal
from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.code import Cardinality, CodeIR, LoadingStrategy, ModelIR, RelationshipIR
from pgproof.domain.ir.schema import (
    ColumnIR,
    ConstraintIR,
    ConstraintKind,
    IndexIR,
    IndexKeyIR,
    SchemaIR,
    SchemaProvenance,
    TableIR,
    UnsupportedConstruct,
)
from pgproof.domain.sources import SourceRef

DEFAULT_SCHEMA: Final = "public"

_COLUMN_CALL_NAMES: Final = frozenset({"Column", "mapped_column", "Field"})
_METADATA_DUNDERS: Final = frozenset(
    {"__tablename__", "__table_args__", "__mapper_args__", "__abstract__"}
)
_LAZY_STRATEGIES: Final[dict[str, LoadingStrategy]] = {
    "select": LoadingStrategy.SELECT,
    "joined": LoadingStrategy.JOINED,
    "subquery": LoadingStrategy.SUBQUERY,
    "selectin": LoadingStrategy.SELECTIN,
    "immediate": LoadingStrategy.IMMEDIATE,
    "noload": LoadingStrategy.NOLOAD,
    "raise": LoadingStrategy.RAISELOAD,
    "raise_on_sql": LoadingStrategy.RAISELOAD,
    "dynamic": LoadingStrategy.DYNAMIC,
}


@dataclass(frozen=True)
class SqlAlchemyStaticResult:
    code: CodeIR
    schema: SchemaIR


def parse_models(paths: list[Path], *, root: Path) -> SqlAlchemyStaticResult:
    """Parse every path as a candidate module of declarative models."""
    models: list[ModelIR] = []
    table_states: dict[str, _TableState] = {}
    relationship_calls: list[_PendingRelationship] = []
    table_variables: dict[str, str] = {}
    unsupported: list[UnsupportedConstruct] = []

    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        source_file = SourceRef(path=relative, content_hash=content_hash(text))
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            unsupported.append(
                UnsupportedConstruct(
                    kind="unparseable_module", reason="syntax error", source=source_file
                )
            )
            continue

        table_variables.update(_module_table_variables(tree))

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            table_name = _table_name_for_class(node)
            if table_name is None:
                if _has_dunder_assignment(node, "__tablename__"):
                    unsupported.append(
                        UnsupportedConstruct(
                            kind="orm_declaration",
                            reason=f"{node.name}: __tablename__ is not a string literal",
                            source=SourceRef(
                                path=relative,
                                line=node.lineno,
                                content_hash=source_file.content_hash,
                            ),
                        )
                    )
                continue
            model_source = SourceRef(
                path=relative, line=node.lineno, content_hash=source_file.content_hash
            )
            state = _TableState(name=table_name)
            mapped_columns: list[str] = []
            for statement in node.body:
                _process_class_statement(
                    statement,
                    table_name=table_name,
                    module_path=relative,
                    state=state,
                    mapped_columns=mapped_columns,
                    relationship_calls=relationship_calls,
                    unsupported=unsupported,
                    source_content_hash=source_file.content_hash,
                )
            table_states[table_name] = state
            models.append(
                ModelIR(
                    class_name=node.name,
                    table=table_id(DEFAULT_SCHEMA, table_name),
                    module_path=relative,
                    source=model_source,
                    mapped_columns=tuple(
                        column_id(table_id(DEFAULT_SCHEMA, table_name), name)
                        for name in mapped_columns
                    ),
                )
            )

    class_to_table = {model.class_name: model.table for model in models}
    relationships, relationship_unsupported = _resolve_relationships(
        relationship_calls, class_to_table, table_variables
    )
    unsupported.extend(relationship_unsupported)

    tables = tuple(
        TableIR(
            id=table_id(DEFAULT_SCHEMA, state.name),
            schema_name=DEFAULT_SCHEMA,
            name=state.name,
            columns=tuple(state.columns.values()),
            provenance=SchemaProvenance.ORM_DECLARATION,
        )
        for state in table_states.values()
    )
    constraints = tuple(c for state in table_states.values() for c in state.constraints.values())
    indexes = tuple(i for state in table_states.values() for i in state.indexes.values())

    code = CodeIR(
        orm="sqlalchemy",
        models=tuple(models),
        relationships=relationships,
        unsupported=tuple(unsupported),
    )
    schema = SchemaIR(
        provenance=SchemaProvenance.ORM_DECLARATION,
        tables=tables,
        constraints=constraints,
        indexes=indexes,
    )
    return SqlAlchemyStaticResult(code=code, schema=schema)


# --------------------------------------------------------------------------- #
# Standalone `sa.Table(...)` variables, for resolving `secondary=`
# --------------------------------------------------------------------------- #
def _module_table_variables(tree: ast.Module) -> dict[str, str]:
    """`NAME = sa.Table("literal_name", ...)` at module scope, keyed by `NAME`."""
    found: dict[str, str] = {}
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and callee_name(node.value.func) == "Table"
            and node.value.args
        ):
            continue
        name = literal(node.value.args[0])
        if isinstance(name, str):
            found[node.targets[0].id] = name
    return found


# --------------------------------------------------------------------------- #
# Model/table detection
# --------------------------------------------------------------------------- #
def _table_name_for_class(node: ast.ClassDef) -> str | None:
    explicit = _dunder_string(node, "__tablename__")
    if explicit is not None:
        return explicit
    if _has_table_true_keyword(node):
        return node.name.lower()
    return None


def _dunder_string(node: ast.ClassDef, name: str) -> str | None:
    for statement in node.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == name
        ):
            value = literal(statement.value)
            return value if isinstance(value, str) else None
    return None


def _has_dunder_assignment(node: ast.ClassDef, name: str) -> bool:
    """Whether `name` is assigned at all, regardless of whether the value is a literal."""
    return any(
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == name
        for statement in node.body
    )


def _has_table_true_keyword(node: ast.ClassDef) -> bool:
    return any(
        keyword.arg == "table" and literal(keyword.value) is True for keyword in node.keywords
    )


# --------------------------------------------------------------------------- #
# Column/relationship dispatch
# --------------------------------------------------------------------------- #
@dataclass
class _TableState:
    name: str
    columns: dict[str, ColumnIR] = field(default_factory=dict)
    constraints: dict[str, ConstraintIR] = field(default_factory=dict)
    indexes: dict[str, IndexIR] = field(default_factory=dict)


@dataclass(frozen=True)
class _PendingRelationship:
    name: str
    source_table: str
    call: ast.Call
    annotation: ast.expr | None
    source: SourceRef


def _process_class_statement(
    statement: ast.stmt,
    *,
    table_name: str,
    module_path: str,
    state: _TableState,
    mapped_columns: list[str],
    relationship_calls: list[_PendingRelationship],
    unsupported: list[UnsupportedConstruct],
    source_content_hash: str,
) -> None:
    line_source = SourceRef(
        path=module_path, line=statement.lineno, content_hash=source_content_hash
    )

    target_name, annotation, call = _decompose_statement(statement)
    if target_name is None:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            unsupported.append(
                UnsupportedConstruct(
                    kind="orm_declaration",
                    reason="not a recognized column/relationship statement",
                    source=line_source,
                )
            )
        elif isinstance(statement, (ast.For, ast.AsyncFor, ast.If, ast.While)):
            unsupported.append(
                UnsupportedConstruct(
                    kind="orm_declaration",
                    reason="dynamic/loop-generated class body statement",
                    source=line_source,
                )
            )
        return
    if target_name in _METADATA_DUNDERS:
        return

    call_name = callee_name(call.func) if call is not None else None
    if call is not None and call_name == "relationship":
        relationship_calls.append(
            _PendingRelationship(
                name=target_name,
                source_table=table_name,
                call=call,
                annotation=annotation,
                source=line_source,
            )
        )
        return
    if call is not None and call_name not in _COLUMN_CALL_NAMES:
        unsupported.append(
            UnsupportedConstruct(
                kind="orm_declaration",
                reason=f"{target_name}: not a direct Column/mapped_column/Field/relationship call",
                source=line_source,
            )
        )
        return

    resolved = _resolve_column(target_name, annotation, call)
    if resolved is UNRESOLVED:
        unsupported.append(
            UnsupportedConstruct(
                kind="orm_declaration",
                reason=f"{target_name}: column has a non-literal argument",
                source=line_source,
            )
        )
        return
    assert isinstance(resolved, dict)
    mapped_columns.append(target_name)
    state.columns[target_name] = ColumnIR(
        id=column_id(table_id(DEFAULT_SCHEMA, table_name), target_name),
        name=target_name,
        data_type=resolved["type_text"],
        nullable=resolved["nullable"],
        default_expression=resolved["server_default"],
        provenance=SchemaProvenance.ORM_DECLARATION,
    )
    if resolved["primary_key"]:
        state.constraints[f"pk_{table_name}"] = ConstraintIR(
            name=f"pk_{table_name}",
            kind=ConstraintKind.PRIMARY_KEY,
            table=table_id(DEFAULT_SCHEMA, table_name),
            columns=(column_id(table_id(DEFAULT_SCHEMA, table_name), target_name),),
            provenance=SchemaProvenance.ORM_DECLARATION,
        )
    if resolved["fk_target"] is not None:
        ref_table, _, ref_column = resolved["fk_target"].partition(".")
        if ref_table and ref_column:
            name = f"fk_{table_name}_{target_name}"
            state.constraints[name] = ConstraintIR(
                name=name,
                kind=ConstraintKind.FOREIGN_KEY,
                table=table_id(DEFAULT_SCHEMA, table_name),
                columns=(column_id(table_id(DEFAULT_SCHEMA, table_name), target_name),),
                referenced_table=table_id(DEFAULT_SCHEMA, ref_table),
                referenced_columns=(column_id(table_id(DEFAULT_SCHEMA, ref_table), ref_column),),
                provenance=SchemaProvenance.ORM_DECLARATION,
            )
    if resolved["unique"]:
        name = f"uq_{table_name}_{target_name}"
        state.constraints[name] = ConstraintIR(
            name=name,
            kind=ConstraintKind.UNIQUE,
            table=table_id(DEFAULT_SCHEMA, table_name),
            columns=(column_id(table_id(DEFAULT_SCHEMA, table_name), target_name),),
            provenance=SchemaProvenance.ORM_DECLARATION,
        )
    if resolved["index"]:
        name = f"ix_{table_name}_{target_name}"
        state.indexes[name] = IndexIR(
            name=name,
            table=table_id(DEFAULT_SCHEMA, table_name),
            keys=(IndexKeyIR(column=column_id(table_id(DEFAULT_SCHEMA, table_name), target_name)),),
            provenance=SchemaProvenance.ORM_DECLARATION,
        )


def _decompose_statement(
    statement: ast.stmt,
) -> tuple[str | None, ast.expr | None, ast.Call | None]:
    """`(target_name, annotation, call)`; `call` is `None` for a bare SQLModel annotation.

    A plain `Assign` (no annotation) whose value is neither a call nor one of
    the recognized metadata dunders is not decomposed at all: a class-level
    constant unrelated to mapping is common and ambiguous to tell apart from
    an attempted column from AST shape alone, so it is silently ignored
    rather than guessed at as a column or flagged as unsupported.
    """
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        call = statement.value if isinstance(statement.value, ast.Call) else None
        return statement.target.id, statement.annotation, call
    if (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
    ):
        name = statement.targets[0].id
        if isinstance(statement.value, ast.Call):
            return name, None, statement.value
        if name in _METADATA_DUNDERS:
            return name, None, None
    return None, None, None


# --------------------------------------------------------------------------- #
# Column resolution
# --------------------------------------------------------------------------- #
def _unwrap_mapped(annotation: ast.expr) -> ast.expr:
    if isinstance(annotation, ast.Subscript) and callee_name(annotation.value) == "Mapped":
        return annotation.slice
    return annotation


def _annotation_allows_none(annotation: ast.expr) -> bool:
    inner = _unwrap_mapped(annotation)
    if isinstance(inner, ast.BinOp) and isinstance(inner.op, ast.BitOr):
        return _is_none(inner.left) or _is_none(inner.right)
    return isinstance(inner, ast.Subscript) and callee_name(inner.value) == "Optional"


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _resolve_column(
    name: str, annotation: ast.expr | None, call: ast.Call | None
) -> dict[str, object] | object:
    del name
    type_text: str | None = (
        ast.unparse(_unwrap_mapped(annotation)) if annotation is not None else None
    )
    primary_key = False
    nullable: bool | None = _annotation_allows_none(annotation) if annotation is not None else None
    unique = False
    index = False
    server_default: str | None = None
    fk_target: str | None = None

    if call is not None:
        for arg in call.args:
            if isinstance(arg, ast.Call) and callee_name(arg.func) == "ForeignKey":
                if not arg.args:
                    return UNRESOLVED
                target = literal(arg.args[0])
                if not isinstance(target, str):
                    return UNRESOLVED
                fk_target = target
            elif type_text is None:
                type_text = ast.unparse(arg)
        for keyword in call.keywords:
            if keyword.arg is None:
                return UNRESOLVED
            if keyword.arg == "primary_key":
                value = literal(keyword.value)
                primary_key = bool(value) if value is not UNRESOLVED else False
            elif keyword.arg == "nullable":
                value = literal(keyword.value)
                nullable = bool(value) if value is not UNRESOLVED else nullable
            elif keyword.arg == "unique":
                value = literal(keyword.value)
                unique = bool(value) if value is not UNRESOLVED else False
            elif keyword.arg == "index":
                value = literal(keyword.value)
                index = bool(value) if value is not UNRESOLVED else False
            elif keyword.arg == "server_default":
                server_default = ast.unparse(keyword.value)
            # `default`, `onupdate`, `sa_column_kwargs`, `description`, etc. are
            # accepted but not modeled: they do not change the column's shape.

    if nullable is None:
        nullable = True
    return {
        "type_text": type_text or "unknown",
        "primary_key": primary_key,
        "nullable": nullable,
        "unique": unique,
        "index": index,
        "server_default": server_default,
        "fk_target": fk_target,
    }


# --------------------------------------------------------------------------- #
# Relationship resolution
# --------------------------------------------------------------------------- #
def _is_list_annotation(annotation: ast.expr) -> bool:
    inner = _unwrap_mapped(annotation)
    return isinstance(inner, ast.Subscript) and callee_name(inner.value) in {"list", "List"}


def _target_class_name(annotation: ast.expr | None) -> str | None:
    if annotation is None:
        return None
    node = _unwrap_mapped(annotation)
    while isinstance(node, ast.Subscript) and callee_name(node.value) in {
        "list",
        "List",
        "Optional",
    }:
        node = node.slice
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        node = node.right if _is_none(node.left) else node.left
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    return None


def _resolve_relationships(
    pending: list[_PendingRelationship],
    class_to_table: dict[str, str],
    table_variables: dict[str, str],
) -> tuple[tuple[RelationshipIR, ...], list[UnsupportedConstruct]]:
    relationships: list[RelationshipIR] = []
    unsupported: list[UnsupportedConstruct] = []
    for item in pending:
        parsed = _parse_relationship_call(item.call)
        if parsed is UNRESOLVED:
            unsupported.append(
                UnsupportedConstruct(
                    kind="orm_declaration",
                    reason=f"{item.name}: relationship has a non-literal argument",
                    source=item.source,
                )
            )
            continue
        assert isinstance(parsed, dict)
        target_class = _target_class_name(item.annotation) or parsed["target"]
        target_table = class_to_table.get(target_class) if target_class else None
        if target_table is None:
            unsupported.append(
                UnsupportedConstruct(
                    kind="orm_declaration",
                    reason=f"{item.name}: relationship target "
                    f"{target_class!r} not found among parsed models",
                    source=item.source,
                )
            )
            continue
        secondary_variable = parsed["secondary"]
        cardinality = _infer_cardinality(item.annotation, secondary_variable, parsed["uselist"])
        lazy = parsed["lazy"]
        loading_strategy = (
            _LAZY_STRATEGIES.get(lazy, LoadingStrategy.UNRESOLVED)
            if lazy is not None
            else LoadingStrategy.SELECT
        )
        secondary_name = (
            table_variables.get(secondary_variable) if secondary_variable is not None else None
        )
        relationships.append(
            RelationshipIR(
                name=item.name,
                source_table=table_id(DEFAULT_SCHEMA, item.source_table),
                target_table=target_table,
                cardinality=cardinality,
                loading_strategy=loading_strategy,
                back_populates=parsed["back_populates"],
                secondary_table=table_id(DEFAULT_SCHEMA, secondary_name)
                if secondary_name is not None
                else None,
                cascade=parsed["cascade"],
                passive_deletes=parsed["passive_deletes"],
                source=item.source,
            )
        )
    return tuple(relationships), unsupported


def _parse_relationship_call(call: ast.Call) -> dict[str, object] | object:
    target: str | None = None
    if call.args:
        value = literal(call.args[0])
        target = value if isinstance(value, str) else None
    back_populates: str | None = None
    secondary: str | None = None
    cascade: tuple[str, ...] = ()
    passive_deletes = False
    lazy: str | None = None
    uselist: bool | None = None
    for keyword in call.keywords:
        if keyword.arg is None:
            return UNRESOLVED
        if keyword.arg == "back_populates":
            value = literal(keyword.value)
            back_populates = value if isinstance(value, str) else None
        elif keyword.arg == "secondary":
            # A bare `Table` variable resolves via `_module_table_variables`; a
            # string table name or any other expression is recorded by its
            # source text so cardinality inference still sees "secondary is
            # set", even though `secondary_table` then stays unresolved.
            secondary = (
                keyword.value.id
                if isinstance(keyword.value, ast.Name)
                else ast.unparse(keyword.value)
            )
        elif keyword.arg == "cascade":
            value = literal(keyword.value)
            if isinstance(value, str):
                cascade = tuple(part.strip() for part in value.split(",") if part.strip())
        elif keyword.arg == "passive_deletes":
            value = literal(keyword.value)
            passive_deletes = bool(value) if value is not UNRESOLVED else False
        elif keyword.arg == "lazy":
            value = literal(keyword.value)
            lazy = value if isinstance(value, str) else None
        elif keyword.arg == "uselist":
            value = literal(keyword.value)
            uselist = value if isinstance(value, bool) else None
        # `order_by`, `foreign_keys`, `primaryjoin`, etc. are accepted but not
        # modeled: they refine the join, not the relationship's identity.
    return {
        "target": target,
        "back_populates": back_populates,
        "secondary": secondary,
        "cascade": cascade,
        "passive_deletes": passive_deletes,
        "lazy": lazy,
        "uselist": uselist,
    }


def _infer_cardinality(
    annotation: ast.expr | None, secondary: str | None, uselist: bool | None
) -> Cardinality:
    is_list = annotation is not None and _is_list_annotation(annotation)
    if secondary is not None:
        return Cardinality.MANY_TO_MANY if is_list else Cardinality.UNRESOLVED
    if is_list:
        return Cardinality.ONE_TO_MANY
    if uselist is False:
        return Cardinality.ONE_TO_ONE
    if annotation is not None:
        return Cardinality.MANY_TO_ONE
    return Cardinality.UNRESOLVED

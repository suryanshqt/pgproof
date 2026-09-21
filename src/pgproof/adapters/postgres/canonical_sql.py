"""Canonical schema SQL, rendered from `SchemaIR`. `docs/TECHNICAL_DESIGN.md:233`:
"produced from the successful database, not by concatenating migration source."

A pure text transformation of already-introspected data, no I/O — the same
shape as `adapters.diagrams.mermaid`/`dbml` rendering domain IR into a target
textual format, just targeting SQL instead of a diagram language.

A `nextval('...')` column default is never rendered: `SchemaIR` has no
sequence model at all (out of scope for BE-17), so the sequence such a
default names would not exist in a fresh database the rendered SQL runs
against. Emitting it anyway would be invalid, non-executable SQL, verified by
`tests/integration/test_postgres_catalog.py::test_canonical_sql_reexecutes_to_a_structurally_equivalent_schema`,
which literally re-executes the output.
"""

from __future__ import annotations

from pgproof.domain.identifiers import column_names, table_names
from pgproof.domain.ir.schema import (
    ConstraintIR,
    ConstraintKind,
    IndexIR,
    SchemaIR,
    SortDirection,
    TableIR,
)


def _column_name(column_id: str) -> str:
    return column_names(column_id)[2]


def render_canonical_schema_sql(schema: SchemaIR) -> str:
    statements: list[str] = []
    for table in sorted(schema.tables, key=lambda t: t.id):
        statements.append(_render_table(table))
    # Every PRIMARY KEY/UNIQUE constraint across every table before any FOREIGN
    # KEY: a foreign key can reference another table's key, so alphabetical
    # order alone (e.g. "orders" before "tenants") can execute a reference
    # before the constraint it points at exists.
    constraints = sorted(schema.constraints, key=lambda c: (c.table, c.name))
    for constraint in constraints:
        if constraint.kind is not ConstraintKind.FOREIGN_KEY:
            rendered = _render_constraint(constraint)
            if rendered is not None:
                statements.append(rendered)
    for constraint in constraints:
        if constraint.kind is ConstraintKind.FOREIGN_KEY:
            rendered = _render_constraint(constraint)
            if rendered is not None:
                statements.append(rendered)
    for index in sorted(schema.indexes, key=lambda i: (i.table, i.name)):
        statements.append(_render_index(index))
    return "\n\n".join(statements) + ("\n" if statements else "")


def _renderable_default(default_expression: str | None) -> str | None:
    if default_expression is None or default_expression.startswith("nextval("):
        return None
    return f"DEFAULT {default_expression}"


def _render_table(table: TableIR) -> str:
    columns = ",\n    ".join(
        " ".join(
            part
            for part in (
                f'"{column.name}"',
                column.data_type,
                "NOT NULL" if not column.nullable else None,
                _renderable_default(column.default_expression),
            )
            if part is not None
        )
        for column in table.columns
    )
    return f'CREATE TABLE "{table.schema_name}"."{table.name}" (\n    {columns}\n);'


_ACTION_TEXT = {
    "no_action": "NO ACTION",
    "restrict": "RESTRICT",
    "cascade": "CASCADE",
    "set_null": "SET NULL",
    "set_default": "SET DEFAULT",
}


def _render_constraint(constraint: ConstraintIR) -> str | None:
    schema_name, table_name = table_names(constraint.table)
    qualified = f'"{schema_name}"."{table_name}"'
    columns = ", ".join(f'"{_column_name(c)}"' for c in constraint.columns)
    header = f'ALTER TABLE {qualified} ADD CONSTRAINT "{constraint.name}"'

    if constraint.kind is ConstraintKind.PRIMARY_KEY:
        return f"{header} PRIMARY KEY ({columns});"
    if constraint.kind is ConstraintKind.UNIQUE:
        return f"{header} UNIQUE ({columns});"
    if constraint.kind is ConstraintKind.CHECK:
        return f"{header} CHECK {constraint.expression};"
    if constraint.kind is ConstraintKind.FOREIGN_KEY:
        assert constraint.referenced_table is not None
        ref_schema, ref_table = table_names(constraint.referenced_table)
        ref_columns = ", ".join(f'"{_column_name(c)}"' for c in constraint.referenced_columns)
        clause = (
            f"{header} FOREIGN KEY ({columns}) "
            f'REFERENCES "{ref_schema}"."{ref_table}" ({ref_columns})'
        )
        if constraint.on_delete is not None:
            clause += f" ON DELETE {_ACTION_TEXT[constraint.on_delete.value]}"
        if constraint.on_update is not None:
            clause += f" ON UPDATE {_ACTION_TEXT[constraint.on_update.value]}"
        return clause + ";"
    return None  # NOT_NULL is column-level; EXCLUSION is out of scope for BE-17.


def _render_index(index: IndexIR) -> str:
    schema_name, table_name = table_names(index.table)
    key_parts = []
    for key in index.keys:
        text = f'"{_column_name(key.column)}"' if key.column is not None else (key.expression or "")
        if key.direction is SortDirection.DESC:
            text += " DESC"
        key_parts.append(text)
    keys = ", ".join(key_parts)
    unique = "UNIQUE " if index.is_unique else ""
    clause = (
        f'CREATE {unique}INDEX "{index.name}" ON "{schema_name}"."{table_name}" '
        f"USING {index.method.value} ({keys})"
    )
    if index.predicate:
        clause += f" WHERE {index.predicate}"
    return clause + ";"

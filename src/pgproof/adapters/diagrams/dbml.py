"""DBML export.

`docs/INTERFACE_DESIGN.md` section 7: "Exported Mermaid/DBML/SVG preserves
evidence labels where the format allows." DBML's inline `ref` column setting
only expresses an enforced foreign key, so a physical foreign key becomes a
`ref`, and an ORM-only relationship becomes a `note` naming what the ORM
declares — never the same syntax, so a reader cannot mistake one for the
other. A composite (multi-column) foreign key has no single column to carry
an inline `ref` and falls back to a table-level comment instead: the format's
own limit, not a guess.
"""

from __future__ import annotations

from pgproof.domain.graph import EdgeKind, GraphIR, NodeKind


def _column_settings(attributes: dict[str, str]) -> str:
    settings = []
    if attributes.get("primary_key") == "true":
        settings.append("pk")
    if attributes.get("nullable") == "false":
        settings.append("not null")
    if "physical_fk_target" in attributes:
        target = attributes["physical_fk_target"]
        table, _, column = target.rpartition(".")
        settings.append(f"ref: > {table}.{column}")
    elif "orm_fk_target" in attributes:
        settings.append(
            f"note: 'ORM-only relationship to {attributes['orm_fk_target']}, no physical "
            "foreign key'"
        )
    return f" [{', '.join(settings)}]" if settings else ""


def to_dbml(graph: GraphIR) -> str:
    tables = {node.id: node for node in graph.nodes if node.kind is NodeKind.TABLE}
    columns_by_table: dict[str, list[str]] = {table_id: [] for table_id in tables}
    for edge in graph.edges:
        if edge.kind is EdgeKind.CONTAINS and edge.source in tables:
            columns_by_table.setdefault(edge.source, []).append(edge.target)
    column_nodes = {node.id: node for node in graph.nodes if node.kind is NodeKind.COLUMN}

    blocks = []
    for table_id in sorted(tables):
        table = tables[table_id]
        lines = [f"Table {table.label} {{"]
        for column_id in sorted(columns_by_table.get(table_id, [])):
            column = column_nodes.get(column_id)
            if column is None:
                continue
            settings = _column_settings(column.attributes)
            lines.append(f"  {column.label} {column.attributes.get('data_type', 'text')}{settings}")
        lines.append("}")
        blocks.append("\n".join(lines))

    composite_notes = []
    for edge in sorted(graph.edges, key=lambda e: e.id):
        if edge.kind is not EdgeKind.ORM_ONLY_RELATIONSHIP:
            continue
        if edge.source not in tables or edge.target not in tables:
            continue
        composite_notes.append(
            f"// ORM-only relationship: {tables[edge.source].label} -> "
            f"{tables[edge.target].label} ({edge.label}) — no physical foreign key"
        )
    return "\n\n".join([*blocks, *(["\n".join(composite_notes)] if composite_notes else [])])

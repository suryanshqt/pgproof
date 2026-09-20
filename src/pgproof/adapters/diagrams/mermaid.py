"""Mermaid flowchart export.

`docs/TECHNICAL_DESIGN.md` section 16: physical and ORM-only relationships
differ by line style and label, never colour alone. Mermaid's `erDiagram`
syntax has no per-edge line-style control, so this renders a `flowchart`
instead, table nodes only — full column detail belongs in `dbml.py` and
`text.py`, which are not constrained to a diagramming tool's own vocabulary.
"""

from __future__ import annotations

import re

from pgproof.domain.graph import EdgeKind, GraphIR, GraphStatus, NodeKind

_UNSAFE = re.compile(r"[^A-Za-z0-9_]")


def _mermaid_id(node_id: str) -> str:
    return _UNSAFE.sub("_", node_id)


def _status_suffix(status: GraphStatus) -> str:
    if status is GraphStatus.PROPOSED_ADDITION:
        return " [+]"
    if status is GraphStatus.PROPOSED_REMOVAL:
        return " [-]"
    return ""


def to_mermaid(graph: GraphIR) -> str:
    """Table-level flowchart: solid edges for physical foreign keys, dashed for
    ORM-only relationships, each labelled with its own name so the kind is never
    carried by colour alone.
    """
    tables = {node.id: node for node in graph.nodes if node.kind is NodeKind.TABLE}
    lines = ["flowchart LR"]
    for table_id in sorted(tables):
        table = tables[table_id]
        lines.append(f'    {_mermaid_id(table_id)}["{table.label}{_status_suffix(table.status)}"]')
    for edge in sorted(graph.edges, key=lambda e: e.id):
        if edge.source not in tables or edge.target not in tables:
            continue
        if edge.kind is EdgeKind.PHYSICAL_FOREIGN_KEY:
            arrow = "-->"
        elif edge.kind is EdgeKind.ORM_ONLY_RELATIONSHIP:
            arrow = "-.->"
        else:
            continue
        label = edge.label or edge.kind.value
        if edge.kind is EdgeKind.ORM_ONLY_RELATIONSHIP:
            label = f"{label} (ORM only)"
        label += _status_suffix(edge.status)
        source = _mermaid_id(edge.source)
        target = _mermaid_id(edge.target)
        lines.append(f'    {source} {arrow}|"{label}"| {target}')
    return "\n".join(lines)

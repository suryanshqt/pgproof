"""Plain-text fallback export.

`docs/INTERFACE_DESIGN.md` section 7: "All graphs have a semantic table/list
fallback." Unlike `mermaid.py`/`dbml.py`, nothing here is dropped for a
diagramming tool's own vocabulary limits — every node and edge kind, and
every proposed/current status, is listed by name.
"""

from __future__ import annotations

from pgproof.domain.graph import EdgeKind, GraphIR, GraphStatus, NodeKind

_KIND_ORDER = (
    NodeKind.SCHEMA,
    NodeKind.TABLE,
    NodeKind.COLUMN,
    NodeKind.INDEX,
    NodeKind.OPERATION,
    NodeKind.TRANSACTION,
    NodeKind.QUERY,
    NodeKind.PROCEDURE,
    NodeKind.TOPOLOGY_COMPONENT,
)


def _status_label(status: GraphStatus) -> str:
    return "" if status is GraphStatus.CURRENT else f" ({status.value})"


def to_text(graph: GraphIR) -> str:
    lines = [f"Graph: {graph.view}"]
    nodes_by_kind: dict[NodeKind, list[str]] = {kind: [] for kind in _KIND_ORDER}
    for node in graph.nodes:
        nodes_by_kind.setdefault(node.kind, []).append(node.id)
    for kind in _KIND_ORDER:
        ids = sorted(nodes_by_kind.get(kind, []))
        if not ids:
            continue
        lines.append(f"{kind.value}:")
        nodes_by_id = {node.id: node for node in graph.nodes if node.kind is kind}
        for node_id in ids:
            node = nodes_by_id[node_id]
            lines.append(f"  - {node.label}{_status_label(node.status)} [{node.id}]")

    edges_by_kind: dict[EdgeKind, list[str]] = {}
    for edge in graph.edges:
        edges_by_kind.setdefault(edge.kind, []).append(edge.id)
    for edge_kind in EdgeKind:
        ids = sorted(edges_by_kind.get(edge_kind, []))
        if not ids:
            continue
        lines.append(f"{edge_kind.value} edges:")
        edges_by_id = {edge.id: edge for edge in graph.edges if edge.kind is edge_kind}
        for edge_id in ids:
            edge = edges_by_id[edge_id]
            label = f' "{edge.label}"' if edge.label else ""
            lines.append(f"  - {edge.source} -> {edge.target}{label}{_status_label(edge.status)}")
    return "\n".join(lines)

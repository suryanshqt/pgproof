"""Build a canonical `GraphIR` from schema/code IR, project an ER view, and hash it.

`docs/TECHNICAL_DESIGN.md` section 16: canonical nodes cover schemas, tables,
columns (and more, added by later roadmap items); an ER export keeps only
table/column/key-relationship data. `docs/ARCHITECTURE.md` section 5 reserves
this module's name and its `mermaid.py`/`dbml.py` siblings for exactly this.

Only a `current` graph is built from real data here: a `target` graph needs a
migration plan (`BE-14`) that does not exist yet, so `view` is a plain
parameter, not a populated second graph.
"""

from __future__ import annotations

import hashlib

from pgproof.domain.graph import EdgeKind, GraphEdge, GraphIR, GraphNode, NodeKind
from pgproof.domain.identifiers import frame_components, node_id, table_names
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.schema import ColumnIR, ConstraintIR, ConstraintKind, SchemaIR, TableIR
from pgproof.domain.primitives import Sha256
from pgproof.domain.reconciliation import fk_holding_relationships, foreign_key_pairs

_ER_NODE_KINDS = frozenset({NodeKind.SCHEMA, NodeKind.TABLE, NodeKind.COLUMN, NodeKind.INDEX})
_ER_EDGE_KINDS = frozenset(
    {EdgeKind.PHYSICAL_FOREIGN_KEY, EdgeKind.ORM_ONLY_RELATIONSHIP, EdgeKind.CONTAINS}
)


def _merged_tables(physical: SchemaIR, orm_schema: SchemaIR) -> dict[str, TableIR]:
    """Physical wins where both sides declare a table: it is closer to final truth."""
    merged: dict[str, TableIR] = {table.id: table for table in orm_schema.tables}
    merged.update({table.id: table for table in physical.tables})
    return merged


def _merged_columns(tables: dict[str, TableIR]) -> dict[str, dict[str, ColumnIR]]:
    """Physical wins per column too, independent of which side's table won above."""
    result: dict[str, dict[str, ColumnIR]] = {}
    for table_id, table in tables.items():
        columns: dict[str, ColumnIR] = {column.id: column for column in table.columns}
        result[table_id] = columns
    return result


def _single_column_targets(
    constraints: tuple[ConstraintIR, ...],
) -> dict[str, str]:
    """A single-column foreign key's source column id to its target column id.

    A composite (multi-column) foreign key is excluded: there is no single
    column to attach the target to, and DBML's inline `ref` annotation is a
    per-column construct — the table-level relationship edge still carries it.
    """
    targets: dict[str, str] = {}
    for constraint in constraints:
        if (
            constraint.kind is ConstraintKind.FOREIGN_KEY
            and len(constraint.columns) == 1
            and constraint.referenced_columns
            and len(constraint.referenced_columns) == 1
        ):
            targets[constraint.columns[0]] = constraint.referenced_columns[0]
    return targets


def _primary_key_columns(schema: SchemaIR) -> frozenset[str]:
    return frozenset(
        column
        for constraint in schema.constraints
        if constraint.kind is ConstraintKind.PRIMARY_KEY
        for column in constraint.columns
    )


def _column_node(
    column: ColumnIR,
    *,
    is_primary_key: bool,
    physical_target: str | None,
    orm_target: str | None,
) -> GraphNode:
    attributes = {
        "data_type": column.data_type,
        "nullable": "true" if column.nullable else "false",
        "primary_key": "true" if is_primary_key else "false",
    }
    if physical_target is not None:
        attributes["physical_fk_target"] = physical_target
    elif orm_target is not None:
        attributes["orm_fk_target"] = orm_target
    return GraphNode(
        id=node_id(NodeKind.COLUMN.value, column.id),
        kind=NodeKind.COLUMN,
        label=column.name,
        attributes=attributes,
    )


def _relationship_edge_id(kind: EdgeKind, name: str, source: str, target: str) -> str:
    return frame_components("edge", kind.value, name, source, target)


def build_graph(
    physical: SchemaIR, orm_schema: SchemaIR, code: CodeIR, *, view: str = "current"
) -> GraphIR:
    """Reconcile-and-project in one pass: every table/column, plus the physical
    and ORM-only relationship edges between them, matched exactly as
    `pgproof.domain.reconciliation` matches them.
    """
    tables = _merged_tables(physical, orm_schema)
    columns_by_table = _merged_columns(tables)
    primary_key_columns = _primary_key_columns(physical) | _primary_key_columns(orm_schema)
    physical_fk_targets = {
        table_id: _single_column_targets(
            tuple(c for c in physical.constraints if c.table == table_id)
        )
        for table_id in tables
    }
    orm_fk_targets = {
        table_id: _single_column_targets(
            tuple(c for c in orm_schema.constraints if c.table == table_id)
        )
        for table_id in tables
    }

    schema_names = sorted({table.schema_name for table in tables.values()})
    nodes: list[GraphNode] = [
        GraphNode(id=node_id(NodeKind.SCHEMA.value, name), kind=NodeKind.SCHEMA, label=name)
        for name in schema_names
    ]
    edges: list[GraphEdge] = []

    for table_id in sorted(tables):
        table = tables[table_id]
        table_node_id = node_id(NodeKind.TABLE.value, table_id)
        nodes.append(
            GraphNode(
                id=table_node_id,
                kind=NodeKind.TABLE,
                label=table.name,
                attributes={"schema": table.schema_name},
            )
        )
        schema_node_id = node_id(NodeKind.SCHEMA.value, table.schema_name)
        edges.append(
            GraphEdge(
                id=frame_components("edge", "contains", schema_node_id, table_node_id),
                kind=EdgeKind.CONTAINS,
                source=schema_node_id,
                target=table_node_id,
            )
        )
        physical_targets = physical_fk_targets[table_id]
        orm_targets = orm_fk_targets[table_id]
        for column_id in sorted(columns_by_table[table_id]):
            column = columns_by_table[table_id][column_id]
            physical_target = physical_targets.get(column_id)
            orm_target = None if physical_target is not None else orm_targets.get(column_id)
            column_node = _column_node(
                column,
                is_primary_key=column_id in primary_key_columns,
                physical_target=physical_target,
                orm_target=orm_target,
            )
            nodes.append(column_node)
            edges.append(
                GraphEdge(
                    id=frame_components("edge", "contains", table_node_id, column_node.id),
                    kind=EdgeKind.CONTAINS,
                    source=table_node_id,
                    target=column_node.id,
                )
            )

    foreign_keys = foreign_key_pairs(physical)
    relationships = fk_holding_relationships(code)
    for pair, constraint in foreign_keys.items():
        source_table, target_table = pair
        edges.append(
            GraphEdge(
                id=_relationship_edge_id(
                    EdgeKind.PHYSICAL_FOREIGN_KEY, constraint.name, source_table, target_table
                ),
                kind=EdgeKind.PHYSICAL_FOREIGN_KEY,
                source=node_id(NodeKind.TABLE.value, source_table),
                target=node_id(NodeKind.TABLE.value, target_table),
                label=constraint.name,
            )
        )
    for pair, relationship in relationships.items():
        if pair in foreign_keys:
            continue
        source_table, target_table = pair
        edges.append(
            GraphEdge(
                id=_relationship_edge_id(
                    EdgeKind.ORM_ONLY_RELATIONSHIP, relationship.name, source_table, target_table
                ),
                kind=EdgeKind.ORM_ONLY_RELATIONSHIP,
                source=node_id(NodeKind.TABLE.value, source_table),
                target=node_id(NodeKind.TABLE.value, target_table),
                label=relationship.name,
            )
        )
    for relationship in code.relationships:
        if relationship.secondary_table is None:
            continue
        pair = (relationship.source_table, relationship.target_table)
        edges.append(
            GraphEdge(
                id=_relationship_edge_id(
                    EdgeKind.ORM_ONLY_RELATIONSHIP,
                    relationship.name,
                    pair[0],
                    pair[1],
                ),
                kind=EdgeKind.ORM_ONLY_RELATIONSHIP,
                source=node_id(NodeKind.TABLE.value, pair[0]),
                target=node_id(NodeKind.TABLE.value, pair[1]),
                label=f"{relationship.name} (via {table_names(relationship.secondary_table)[1]})",
            )
        )

    nodes.sort(key=lambda node: node.id)
    edges.sort(key=lambda edge: edge.id)
    return GraphIR(view=view, nodes=tuple(nodes), edges=tuple(edges))


def er_view(graph: GraphIR) -> GraphIR:
    """The subset TECHNICAL_DESIGN section 16 calls an ER export: table/column/key
    relationships only. Operation, transaction, query, procedure and topology
    nodes, and their reads/writes/calls/routes-to/owns edges, are dropped —
    those belong in a focused architecture overlay, not the canonical ER view.
    """
    kept_nodes = tuple(node for node in graph.nodes if node.kind in _ER_NODE_KINDS)
    kept_ids = {node.id for node in kept_nodes}
    kept_edges = tuple(
        edge
        for edge in graph.edges
        if edge.kind in _ER_EDGE_KINDS and edge.source in kept_ids and edge.target in kept_ids
    )
    return GraphIR(view=graph.view, nodes=kept_nodes, edges=kept_edges)


def graph_identity(graph: GraphIR) -> Sha256:
    """A hash stable under node/edge insertion order, per TECHNICAL_DESIGN section 16's
    "layout is not canonical evidence... positions persist keyed by graph/node hash."
    """
    canonical = graph.model_copy(
        update={
            "nodes": tuple(sorted(graph.nodes, key=lambda node: node.id)),
            "edges": tuple(sorted(graph.edges, key=lambda edge: edge.id)),
        }
    )
    digest = hashlib.sha256(canonical.canonical_json().encode("utf-8")).hexdigest()
    return f"sha256:{digest}"

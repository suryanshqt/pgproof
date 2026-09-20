"""Mermaid export: physical vs ORM-only distinguished by line style and label."""

from pgproof.adapters.diagrams.mermaid import to_mermaid
from pgproof.domain.graph import EdgeKind, GraphEdge, GraphIR, GraphNode, GraphStatus, NodeKind


def _graph(*, edge_status: GraphStatus = GraphStatus.CURRENT) -> GraphIR:
    orders = GraphNode(id="table:public.orders", kind=NodeKind.TABLE, label="orders")
    tenants = GraphNode(id="table:public.tenants", kind=NodeKind.TABLE, label="tenants")
    users = GraphNode(id="table:public.users", kind=NodeKind.TABLE, label="users")
    return GraphIR(
        view="current",
        nodes=(orders, tenants, users),
        edges=(
            GraphEdge(
                id="e1",
                kind=EdgeKind.PHYSICAL_FOREIGN_KEY,
                source=orders.id,
                target=users.id,
                label="fk_orders_user_id",
                status=edge_status,
            ),
            GraphEdge(
                id="e2",
                kind=EdgeKind.ORM_ONLY_RELATIONSHIP,
                source=orders.id,
                target=tenants.id,
                label="tenant",
            ),
        ),
    )


def test_physical_foreign_keys_render_as_solid_labelled_edges() -> None:
    text = to_mermaid(_graph())
    assert 'table_public_orders -->|"fk_orders_user_id"| table_public_users' in text


def test_orm_only_relationships_render_as_dashed_edges_labelled_orm_only() -> None:
    text = to_mermaid(_graph())
    assert 'table_public_orders -.->|"tenant (ORM only)"| table_public_tenants' in text


def test_every_table_node_is_declared() -> None:
    text = to_mermaid(_graph())
    assert 'table_public_orders["orders"]' in text
    assert 'table_public_tenants["tenants"]' in text
    assert 'table_public_users["users"]' in text


def test_node_ids_are_sanitized_for_mermaid() -> None:
    text = to_mermaid(_graph())
    assert ":" not in text.split("\n")[1]
    assert "." not in text.split("\n")[1].split("[")[0]


def test_a_proposed_addition_edge_carries_a_status_marker() -> None:
    text = to_mermaid(_graph(edge_status=GraphStatus.PROPOSED_ADDITION))
    assert "[+]" in text


def test_a_proposed_removal_edge_carries_a_status_marker() -> None:
    text = to_mermaid(_graph(edge_status=GraphStatus.PROPOSED_REMOVAL))
    assert "[-]" in text


def test_a_contains_edge_between_two_tables_is_not_rendered() -> None:
    orders = GraphNode(id="table:public.orders", kind=NodeKind.TABLE, label="orders")
    tenants = GraphNode(id="table:public.tenants", kind=NodeKind.TABLE, label="tenants")
    graph = GraphIR(
        view="current",
        nodes=(orders, tenants),
        edges=(GraphEdge(id="e1", kind=EdgeKind.CONTAINS, source=orders.id, target=tenants.id),),
    )
    text = to_mermaid(graph)
    assert "-->" not in text
    assert "-.->" not in text


def test_contains_edges_are_not_rendered() -> None:
    table = GraphNode(id="table:public.orders", kind=NodeKind.TABLE, label="orders")
    column = GraphNode(id="column:public.orders.id", kind=NodeKind.COLUMN, label="id")
    graph = GraphIR(
        view="current",
        nodes=(table, column),
        edges=(GraphEdge(id="e1", kind=EdgeKind.CONTAINS, source=table.id, target=column.id),),
    )
    text = to_mermaid(graph)
    assert "-->" not in text
    assert "-.->" not in text


def test_an_edge_to_a_non_table_node_is_skipped() -> None:
    table = GraphNode(id="table:public.orders", kind=NodeKind.TABLE, label="orders")
    column = GraphNode(id="column:public.orders.id", kind=NodeKind.COLUMN, label="id")
    graph = GraphIR(
        view="current",
        nodes=(table, column),
        edges=(
            GraphEdge(
                id="e1",
                kind=EdgeKind.PHYSICAL_FOREIGN_KEY,
                source=table.id,
                target=column.id,
            ),
        ),
    )
    text = to_mermaid(graph)
    assert "-->" not in text

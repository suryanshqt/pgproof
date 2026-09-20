"""Plain-text fallback export: every node and edge kind listed, nothing dropped."""

from pgproof.adapters.diagrams.text import to_text
from pgproof.domain.graph import EdgeKind, GraphEdge, GraphIR, GraphNode, GraphStatus, NodeKind


def test_nodes_are_grouped_and_listed_under_their_kind() -> None:
    table = GraphNode(id="table:public.orders", kind=NodeKind.TABLE, label="orders")
    column = GraphNode(id="column:public.orders.id", kind=NodeKind.COLUMN, label="id")
    graph = GraphIR(view="current", nodes=(table, column), edges=())
    text = to_text(graph)
    assert "table:" in text
    assert "  - orders [table:public.orders]" in text
    assert "column:" in text
    assert "  - id [column:public.orders.id]" in text


def test_an_operation_node_still_appears_in_the_fallback() -> None:
    operation = GraphNode(
        id="operation:app::place_order", kind=NodeKind.OPERATION, label="place_order"
    )
    graph = GraphIR(view="current", nodes=(operation,), edges=())
    text = to_text(graph)
    assert "operation:" in text
    assert "place_order" in text


def test_edges_are_grouped_by_kind_with_source_target_and_label() -> None:
    a = GraphNode(id="table:public.a", kind=NodeKind.TABLE, label="a")
    b = GraphNode(id="table:public.b", kind=NodeKind.TABLE, label="b")
    graph = GraphIR(
        view="current",
        nodes=(a, b),
        edges=(
            GraphEdge(
                id="e1",
                kind=EdgeKind.PHYSICAL_FOREIGN_KEY,
                source=a.id,
                target=b.id,
                label="fk_a_b",
            ),
        ),
    )
    text = to_text(graph)
    assert "physical_foreign_key edges:" in text
    assert f'  - {a.id} -> {b.id} "fk_a_b"' in text


def test_a_proposed_addition_status_is_named_not_dropped() -> None:
    node = GraphNode(
        id="table:public.orders",
        kind=NodeKind.TABLE,
        label="orders",
        status=GraphStatus.PROPOSED_ADDITION,
    )
    graph = GraphIR(view="current", nodes=(node,), edges=())
    text = to_text(graph)
    assert "orders (proposed_addition)" in text


def test_an_unlabelled_edge_omits_the_quoted_label() -> None:
    a = GraphNode(id="table:public.a", kind=NodeKind.TABLE, label="a")
    b = GraphNode(id="table:public.b", kind=NodeKind.TABLE, label="b")
    graph = GraphIR(
        view="current",
        nodes=(a, b),
        edges=(GraphEdge(id="e1", kind=EdgeKind.CONTAINS, source=a.id, target=b.id),),
    )
    text = to_text(graph)
    assert f"  - {a.id} -> {b.id}\n" in text + "\n"
    assert '""' not in text


def test_the_graph_view_name_is_the_first_line() -> None:
    graph = GraphIR(view="target", nodes=(), edges=())
    text = to_text(graph)
    assert text.splitlines()[0] == "Graph: target"


def test_an_empty_graph_produces_only_the_header() -> None:
    graph = GraphIR(view="current", nodes=(), edges=())
    assert to_text(graph) == "Graph: current"

"""DBML export: a physical foreign key becomes `ref`, an ORM-only one becomes `note`."""

from pgproof.adapters.diagrams.dbml import to_dbml
from pgproof.domain.graph import EdgeKind, GraphEdge, GraphIR, GraphNode, NodeKind


def _column(table: str, name: str, **attributes: str) -> GraphNode:
    return GraphNode(
        id=f"column:public.{table}.{name}",
        kind=NodeKind.COLUMN,
        label=name,
        attributes={"data_type": "int", "nullable": "false", "primary_key": "false", **attributes},
    )


def _table(name: str) -> GraphNode:
    return GraphNode(id=f"table:public.{name}", kind=NodeKind.TABLE, label=name)


def _contains(table: GraphNode, column: GraphNode) -> GraphEdge:
    return GraphEdge(
        id=f"contains:{table.id}:{column.id}",
        kind=EdgeKind.CONTAINS,
        source=table.id,
        target=column.id,
    )


def test_a_physical_foreign_key_column_becomes_an_inline_ref() -> None:
    orders = _table("orders")
    tenants = _table("tenants")
    tenant_id = _column("orders", "tenant_id", physical_fk_target="public.tenants.id")
    graph = GraphIR(
        view="current",
        nodes=(orders, tenants, tenant_id),
        edges=(_contains(orders, tenant_id),),
    )
    text = to_dbml(graph)
    assert "ref: > public.tenants.id" in text
    assert "note:" not in text


def test_an_orm_only_foreign_key_column_becomes_a_note_not_a_ref() -> None:
    orders = _table("orders")
    tenant_id = _column("orders", "tenant_id", orm_fk_target="public.tenants.id")
    graph = GraphIR(
        view="current", nodes=(orders, tenant_id), edges=(_contains(orders, tenant_id),)
    )
    text = to_dbml(graph)
    assert "ref:" not in text
    assert "note: 'ORM-only relationship to public.tenants.id, no physical foreign key'" in text


def test_a_primary_key_column_is_marked_pk() -> None:
    orders = _table("orders")
    order_id = _column("orders", "id", primary_key="true", nullable="true")
    graph = GraphIR(view="current", nodes=(orders, order_id), edges=(_contains(orders, order_id),))
    text = to_dbml(graph)
    assert "id int [pk]" in text


def test_a_nullable_column_carries_no_not_null_setting() -> None:
    orders = _table("orders")
    note = _column("orders", "note", nullable="true")
    graph = GraphIR(view="current", nodes=(orders, note), edges=(_contains(orders, note),))
    text = to_dbml(graph)
    assert "not null" not in text
    assert "  note int" in text


def test_an_orm_only_relationship_between_tables_gets_a_table_level_comment() -> None:
    orders = _table("orders")
    tenants = _table("tenants")
    graph = GraphIR(
        view="current",
        nodes=(orders, tenants),
        edges=(
            GraphEdge(
                id="e1",
                kind=EdgeKind.ORM_ONLY_RELATIONSHIP,
                source=orders.id,
                target=tenants.id,
                label="tenant",
            ),
        ),
    )
    text = to_dbml(graph)
    assert "// ORM-only relationship: orders -> tenants (tenant)" in text


def test_every_table_gets_its_own_block() -> None:
    orders = _table("orders")
    tenants = _table("tenants")
    graph = GraphIR(view="current", nodes=(orders, tenants), edges=())
    text = to_dbml(graph)
    assert "Table orders {" in text
    assert "Table tenants {" in text


def test_a_contains_edge_to_a_non_column_node_is_skipped() -> None:
    orders = _table("orders")
    tenants = _table("tenants")
    graph = GraphIR(
        view="current",
        nodes=(orders, tenants),
        edges=(GraphEdge(id="e1", kind=EdgeKind.CONTAINS, source=orders.id, target=tenants.id),),
    )
    text = to_dbml(graph)
    assert text == "Table orders {\n}\n\nTable tenants {\n}"


def test_an_orm_only_edge_to_a_non_table_node_produces_no_comment() -> None:
    orders = _table("orders")
    column = _column("orders", "id")
    graph = GraphIR(
        view="current",
        nodes=(orders, column),
        edges=(
            _contains(orders, column),
            GraphEdge(
                id="e1", kind=EdgeKind.ORM_ONLY_RELATIONSHIP, source=orders.id, target=column.id
            ),
        ),
    )
    text = to_dbml(graph)
    assert "//" not in text

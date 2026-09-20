"""Canonical graph building, the ER-view projection, and graph identity."""

from pathlib import Path

from pgproof.adapters.diagrams.graph_ir import build_graph, er_view, graph_identity
from pgproof.adapters.repository.alembic_static import parse_migrations
from pgproof.adapters.repository.sqlalchemy_static import parse_models
from pgproof.domain.graph import EdgeKind, GraphEdge, GraphIR, GraphNode, NodeKind
from pgproof.domain.identifiers import column_id, node_id, table_id
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.schema import (
    ColumnIR,
    ConstraintIR,
    ConstraintKind,
    SchemaIR,
    SchemaProvenance,
    TableIR,
)

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _table(name: str, columns: tuple[ColumnIR, ...]) -> TableIR:
    return TableIR(
        id=table_id("public", name),
        schema_name="public",
        name=name,
        columns=columns,
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )


def _column(table: str, name: str, *, nullable: bool = False) -> ColumnIR:
    return ColumnIR(
        id=column_id(table_id("public", table), name),
        name=name,
        data_type="int",
        nullable=nullable,
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )


def _fk(
    source_table: str,
    columns: tuple[str, ...],
    target_table: str,
    referenced_columns: tuple[str, ...],
) -> ConstraintIR:
    return ConstraintIR(
        name=f"fk_{source_table}",
        kind=ConstraintKind.FOREIGN_KEY,
        table=table_id("public", source_table),
        columns=tuple(column_id(table_id("public", source_table), c) for c in columns),
        referenced_table=table_id("public", target_table),
        referenced_columns=tuple(
            column_id(table_id("public", target_table), c) for c in referenced_columns
        ),
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )


def _empty_orm() -> tuple[SchemaIR, CodeIR]:
    return SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION), CodeIR(orm="sqlalchemy")


def _table_node(graph: GraphIR, table: str) -> GraphNode:
    target = node_id(NodeKind.TABLE.value, table_id("public", table))
    return next(node for node in graph.nodes if node.id == target)


def _edges(graph: GraphIR, kind: EdgeKind) -> tuple[GraphEdge, ...]:
    return tuple(edge for edge in graph.edges if edge.kind is kind)


# --------------------------------------------------------------------------- #
# Composite and self-referential foreign keys
# --------------------------------------------------------------------------- #
def test_a_composite_foreign_key_produces_one_table_level_edge_and_no_inline_target() -> None:
    order_lines = _table(
        "order_lines", (_column("order_lines", "order_id"), _column("order_lines", "line_no"))
    )
    shipments = _table(
        "shipments", (_column("shipments", "order_id"), _column("shipments", "line_no"))
    )
    physical = SchemaIR(
        provenance=SchemaProvenance.STATIC_MIGRATION,
        tables=(order_lines, shipments),
        constraints=(
            ConstraintIR(
                name="pk_order_lines",
                kind=ConstraintKind.PRIMARY_KEY,
                table=order_lines.id,
                columns=(order_lines.columns[0].id, order_lines.columns[1].id),
                provenance=SchemaProvenance.STATIC_MIGRATION,
            ),
            _fk("shipments", ("order_id", "line_no"), "order_lines", ("order_id", "line_no")),
        ),
    )
    orm_schema, code = _empty_orm()
    graph = build_graph(physical, orm_schema, code)

    fk_edges = _edges(graph, EdgeKind.PHYSICAL_FOREIGN_KEY)
    assert len(fk_edges) == 1
    assert fk_edges[0].source == _table_node(graph, "shipments").id
    assert fk_edges[0].target == _table_node(graph, "order_lines").id

    shipment_order_id = next(
        node_id(NodeKind.COLUMN.value, c.id) for c in shipments.columns if c.name == "order_id"
    )
    column_node = next(n for n in graph.nodes if n.id == shipment_order_id)
    assert "physical_fk_target" not in column_node.attributes


def test_a_self_referential_foreign_key_is_a_self_loop_edge() -> None:
    employees = _table(
        "employees", (_column("employees", "id"), _column("employees", "manager_id", nullable=True))
    )
    physical = SchemaIR(
        provenance=SchemaProvenance.STATIC_MIGRATION,
        tables=(employees,),
        constraints=(
            ConstraintIR(
                name="pk_employees",
                kind=ConstraintKind.PRIMARY_KEY,
                table=employees.id,
                columns=(employees.columns[0].id,),
                provenance=SchemaProvenance.STATIC_MIGRATION,
            ),
            _fk("employees", ("manager_id",), "employees", ("id",)),
        ),
    )
    orm_schema, code = _empty_orm()
    graph = build_graph(physical, orm_schema, code)

    fk_edges = _edges(graph, EdgeKind.PHYSICAL_FOREIGN_KEY)
    assert len(fk_edges) == 1
    employees_node_id = _table_node(graph, "employees").id
    assert fk_edges[0].source == employees_node_id
    assert fk_edges[0].target == employees_node_id

    manager_id = next(
        n for n in graph.nodes if n.kind is NodeKind.COLUMN and n.label == "manager_id"
    )
    assert manager_id.attributes["physical_fk_target"] == column_id(
        table_id("public", "employees"), "id"
    )


# --------------------------------------------------------------------------- #
# Many-to-many, and the one-to-one non-scope carried over from BE-10
# --------------------------------------------------------------------------- #
def test_many_to_many_produces_an_orm_only_edge_in_both_directions() -> None:
    root = FIXTURES / "sqlalchemy-static" / "relationships"
    orm = parse_models([root / "models.py"], root=root)
    physical = SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION)
    graph = build_graph(physical, orm.schema, orm.code)

    orm_only = _edges(graph, EdgeKind.ORM_ONLY_RELATIONSHIP)
    pairs = {(e.source, e.target) for e in orm_only}
    posts_id = _table_node(graph, "posts").id
    tags_id = _table_node(graph, "tags").id
    assert (posts_id, tags_id) in pairs
    assert (tags_id, posts_id) in pairs
    tags_edge = next(e for e in orm_only if e.source == posts_id and e.target == tags_id)
    assert "post_tags" in (tags_edge.label or "")


def test_a_one_to_one_relationship_produces_no_edge() -> None:
    root = FIXTURES / "sqlalchemy-static" / "relationships"
    orm = parse_models([root / "models.py"], root=root)
    physical = SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION)
    graph = build_graph(physical, orm.schema, orm.code)

    authors_id = _table_node(graph, "authors").id
    profiles_id = _table_node(graph, "profiles").id
    all_edges = {(e.source, e.target) for e in graph.edges if e.kind is not EdgeKind.CONTAINS}
    assert (authors_id, profiles_id) not in all_edges


# --------------------------------------------------------------------------- #
# ORM-only vs physical: the real demo-broken/demo-clean fixtures
# --------------------------------------------------------------------------- #
def _build_from_fixture(name: str) -> GraphIR:
    root = FIXTURES / name
    versions = sorted((root / "migrations" / "versions").glob("*.py"))
    physical = parse_migrations(versions, root=root).schema
    orm = parse_models([root / "app" / "models.py"], root=root)
    return build_graph(physical, orm.schema, orm.code)


def test_demo_broken_has_exactly_one_orm_only_edge() -> None:
    graph = _build_from_fixture("demo-broken")
    orm_only = _edges(graph, EdgeKind.ORM_ONLY_RELATIONSHIP)
    assert len(orm_only) == 1
    assert orm_only[0].source == _table_node(graph, "orders").id
    assert orm_only[0].target == _table_node(graph, "tenants").id


def test_demo_clean_has_no_orm_only_edges_and_the_real_fk_instead() -> None:
    graph = _build_from_fixture("demo-clean")
    assert _edges(graph, EdgeKind.ORM_ONLY_RELATIONSHIP) == ()
    physical_fk = _edges(graph, EdgeKind.PHYSICAL_FOREIGN_KEY)
    pairs = {(e.source, e.target) for e in physical_fk}
    assert (_table_node(graph, "orders").id, _table_node(graph, "tenants").id) in pairs


# --------------------------------------------------------------------------- #
# ER view projection
# --------------------------------------------------------------------------- #
def test_er_view_drops_operation_nodes_and_their_edges() -> None:
    table = GraphNode(id="table:public.orders", kind=NodeKind.TABLE, label="orders")
    operation = GraphNode(
        id="operation:app::place_order", kind=NodeKind.OPERATION, label="place_order"
    )
    graph = GraphIR(
        view="current",
        nodes=(table, operation),
        edges=(GraphEdge(id="e1", kind=EdgeKind.WRITES, source=operation.id, target=table.id),),
    )
    view = er_view(graph)
    assert view.nodes == (table,)
    assert view.edges == ()


def test_er_view_keeps_table_column_and_key_relationship_data() -> None:
    table = GraphNode(id="table:public.orders", kind=NodeKind.TABLE, label="orders")
    column = GraphNode(id="column:public.orders.id", kind=NodeKind.COLUMN, label="id")
    graph = GraphIR(
        view="current",
        nodes=(table, column),
        edges=(GraphEdge(id="e1", kind=EdgeKind.CONTAINS, source=table.id, target=column.id),),
    )
    view = er_view(graph)
    assert view.nodes == (table, column)
    assert view.edges == graph.edges


# --------------------------------------------------------------------------- #
# Deterministic graph identity
# --------------------------------------------------------------------------- #
def test_graph_identity_is_stable_under_node_and_edge_order() -> None:
    a = GraphNode(id="table:public.a", kind=NodeKind.TABLE, label="a")
    b = GraphNode(id="table:public.b", kind=NodeKind.TABLE, label="b")
    edge = GraphEdge(id="e1", kind=EdgeKind.PHYSICAL_FOREIGN_KEY, source=a.id, target=b.id)
    forward = GraphIR(view="current", nodes=(a, b), edges=(edge,))
    backward = GraphIR(view="current", nodes=(b, a), edges=(edge,))
    assert graph_identity(forward) == graph_identity(backward)


def test_graph_identity_changes_when_content_changes() -> None:
    a = GraphNode(id="table:public.a", kind=NodeKind.TABLE, label="a")
    b = GraphNode(id="table:public.b", kind=NodeKind.TABLE, label="b")
    with_edge = GraphIR(
        view="current",
        nodes=(a, b),
        edges=(GraphEdge(id="e1", kind=EdgeKind.PHYSICAL_FOREIGN_KEY, source=a.id, target=b.id),),
    )
    without_edge = GraphIR(view="current", nodes=(a, b))
    assert graph_identity(with_edge) != graph_identity(without_edge)

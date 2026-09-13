"""Canonical graph IR.

`docs/TECHNICAL_DESIGN.md` section 16 requires physical and ORM-only edges to
differ by kind rather than by presentation, and `docs/INTERFACE_DESIGN.md`
section 6 requires colour to be secondary. Both hold here because edge meaning is
carried by `EdgeKind`, and layout is explicitly not part of this contract.
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from pgproof.domain.identifiers import NodeId
from pgproof.domain.primitives import Contract, NonEmptyText, SnakeCaseEnum


class NodeKind(SnakeCaseEnum):
    SCHEMA = "schema"
    TABLE = "table"
    COLUMN = "column"
    INDEX = "index"
    OPERATION = "operation"
    TRANSACTION = "transaction"
    QUERY = "query"
    PROCEDURE = "procedure"
    TOPOLOGY_COMPONENT = "topology_component"


class EdgeKind(SnakeCaseEnum):
    """A physical foreign key and an ORM-only relationship are distinct kinds."""

    PHYSICAL_FOREIGN_KEY = "physical_foreign_key"
    ORM_ONLY_RELATIONSHIP = "orm_only_relationship"
    CONTAINS = "contains"
    READS = "reads"
    WRITES = "writes"
    CALLS = "calls"
    ROUTES_TO = "routes_to"
    OWNS = "owns"
    PROPOSED = "proposed"


class GraphStatus(SnakeCaseEnum):
    CURRENT = "current"
    PROPOSED_ADDITION = "proposed_addition"
    PROPOSED_REMOVAL = "proposed_removal"


class GraphNode(Contract):
    """A node. Position is presentation state and deliberately absent."""

    id: NodeId
    kind: NodeKind
    label: NonEmptyText
    status: GraphStatus = GraphStatus.CURRENT
    attributes: dict[str, str] = Field(default_factory=dict)


class GraphEdge(Contract):
    """A directed edge whose meaning is its kind."""

    id: NonEmptyText
    kind: EdgeKind
    source: NodeId
    target: NodeId
    label: NonEmptyText | None = None
    status: GraphStatus = GraphStatus.CURRENT


class GraphIR(Contract):
    """A canonical graph with referential integrity enforced on construction."""

    view: NonEmptyText
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()

    @model_validator(mode="after")
    def _validate_references(self) -> Self:
        ids = {node.id for node in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("graph node ids must be unique")
        dangling = sorted(
            {
                endpoint
                for edge in self.edges
                for endpoint in (edge.source, edge.target)
                if endpoint not in ids
            }
        )
        if dangling:
            raise ValueError(f"graph edges reference unknown nodes: {dangling}")
        edge_ids = {edge.id for edge in self.edges}
        if len(edge_ids) != len(self.edges):
            raise ValueError("graph edge ids must be unique")
        return self

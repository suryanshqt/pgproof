"""EXPLAIN (ANALYZE, BUFFERS, WAL, TIMING OFF, FORMAT JSON) parsing and plan
identity. `docs/PR_ROADMAP.md`'s BE-26: "timing/cost/row changes do not alter
plan identity but join/scan/relation changes do."

Pure: the raw JSON object `adapters.benchmark.run._explain` already fetched
from a live connection, never a connection of its own.

Fingerprint fields (node type, strategy, relation/index name, join type, sort
and group key *column names*) are a distinct set from diagnostic fields
(cost, row counts, buffers, WAL, timing): a condition/filter's literal text
(e.g. `"(id = 3)"`) is deliberately excluded from both — including it would
make two runs of the identical plan against different parameter values
fingerprint differently, exactly the false distinction this module exists to
avoid. `scripts/fixture_measurements.py`'s own hand-validated `_plan_shape`
already established this same node-type/relation/index convention; this
module is its formalized, tested superset (also covering joins and sorts,
which that fixture script's index-only cases never needed).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

_BUFFER_FIELDS = (
    "Shared Hit Blocks",
    "Shared Read Blocks",
    "Shared Dirtied Blocks",
    "Shared Written Blocks",
    "Local Hit Blocks",
    "Local Read Blocks",
    "Local Dirtied Blocks",
    "Local Written Blocks",
    "Temp Read Blocks",
    "Temp Written Blocks",
)


@dataclass(frozen=True)
class BufferStats:
    shared_hit_blocks: int
    shared_read_blocks: int
    shared_dirtied_blocks: int
    shared_written_blocks: int
    local_hit_blocks: int
    local_read_blocks: int
    local_dirtied_blocks: int
    local_written_blocks: int
    temp_read_blocks: int
    temp_written_blocks: int


@dataclass(frozen=True)
class WalStats:
    records: int
    full_page_images: int
    bytes: int


@dataclass(frozen=True)
class PlanNode:
    """One EXPLAIN plan node. Every field here except `children` is either
    identity-bearing (see module docstring) or a diagnostic fact — never both,
    so `fingerprint_plan` knows exactly which fields to read.
    """

    node_type: str
    strategy: str | None
    relation_name: str | None
    index_name: str | None
    join_type: str | None
    scan_direction: str | None
    sort_key: tuple[str, ...]
    group_key: tuple[str, ...]
    children: tuple[PlanNode, ...]
    # Diagnostic only, excluded from the fingerprint.
    plan_rows: float | None
    actual_rows: float | None
    total_cost: float | None
    buffers: BufferStats | None
    wal: WalStats | None


@dataclass(frozen=True)
class PlanDiagnostics:
    plan: PlanNode
    planning_time_ms: float | None
    execution_time_ms: float | None
    normalized_shape: str
    plan_fingerprint: str


def _int(node: Mapping[str, object], key: str) -> int:
    return cast("int", node.get(key, 0))


def _str(node: Mapping[str, object], key: str) -> str | None:
    return cast("str | None", node.get(key))


def _float(node: Mapping[str, object], key: str) -> float | None:
    return cast("float | None", node.get(key))


def _buffer_stats(node: Mapping[str, object]) -> BufferStats | None:
    if not any(field in node for field in _BUFFER_FIELDS):
        return None
    return BufferStats(
        shared_hit_blocks=_int(node, "Shared Hit Blocks"),
        shared_read_blocks=_int(node, "Shared Read Blocks"),
        shared_dirtied_blocks=_int(node, "Shared Dirtied Blocks"),
        shared_written_blocks=_int(node, "Shared Written Blocks"),
        local_hit_blocks=_int(node, "Local Hit Blocks"),
        local_read_blocks=_int(node, "Local Read Blocks"),
        local_dirtied_blocks=_int(node, "Local Dirtied Blocks"),
        local_written_blocks=_int(node, "Local Written Blocks"),
        temp_read_blocks=_int(node, "Temp Read Blocks"),
        temp_written_blocks=_int(node, "Temp Written Blocks"),
    )


def _wal_stats(node: Mapping[str, object]) -> WalStats | None:
    if "WAL Records" not in node and "WAL Bytes" not in node:
        return None
    return WalStats(
        records=_int(node, "WAL Records"),
        full_page_images=_int(node, "WAL FPI"),
        bytes=_int(node, "WAL Bytes"),
    )


def _parse_node(node: Mapping[str, object]) -> PlanNode:
    raw_children = cast("Sequence[Mapping[str, object]]", node.get("Plans", ()))
    children = tuple(_parse_node(child) for child in raw_children)
    sort_key = cast("Sequence[str]", node.get("Sort Key", ()))
    group_key = cast("Sequence[str]", node.get("Group Key", ()))
    return PlanNode(
        node_type=str(node["Node Type"]),
        strategy=_str(node, "Strategy"),
        relation_name=_str(node, "Relation Name"),
        index_name=_str(node, "Index Name"),
        join_type=_str(node, "Join Type"),
        scan_direction=_str(node, "Scan Direction"),
        sort_key=tuple(sort_key),
        group_key=tuple(group_key),
        children=children,
        plan_rows=_float(node, "Plan Rows"),
        actual_rows=_float(node, "Actual Rows"),
        total_cost=_float(node, "Total Cost"),
        buffers=_buffer_stats(node),
        wal=_wal_stats(node),
    )


def _identity(node: PlanNode) -> dict[str, object]:
    return {
        "node_type": node.node_type,
        "strategy": node.strategy,
        "relation_name": node.relation_name,
        "index_name": node.index_name,
        "join_type": node.join_type,
        "scan_direction": node.scan_direction,
        "sort_key": list(node.sort_key),
        "group_key": list(node.group_key),
        "children": [_identity(child) for child in node.children],
    }


def fingerprint_plan(node: PlanNode) -> str:
    canonical = json.dumps(
        _identity(node), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def normalized_shape(node: PlanNode) -> str:
    """A human-readable rendering of the same identity fields `fingerprint_plan`
    hashes — for a diff or a report, not for equality comparison.
    """
    entry = node.node_type
    if node.strategy:
        entry += f" ({node.strategy})"
    if node.join_type:
        entry = f"{node.join_type} {entry}"
    if node.index_name:
        entry += f" using {node.index_name}"
    elif node.relation_name:
        entry += f" on {node.relation_name}"
    if not node.children:
        return entry
    return entry + " -> (" + ", ".join(normalized_shape(child) for child in node.children) + ")"


def parse_explain(raw: object) -> PlanDiagnostics:
    """`raw` is exactly what `adapters.benchmark.run._explain` returns: the
    JSON value `FORMAT JSON` produced, already decoded by psycopg into a
    one-element Python list.
    """
    if not isinstance(raw, list) or not raw or "Plan" not in raw[0]:
        raise ValueError("not a FORMAT JSON EXPLAIN result")
    document = raw[0]
    plan = _parse_node(document["Plan"])
    return PlanDiagnostics(
        plan=plan,
        planning_time_ms=document.get("Planning Time"),
        execution_time_ms=document.get("Execution Time"),
        normalized_shape=normalized_shape(plan),
        plan_fingerprint=fingerprint_plan(plan),
    )

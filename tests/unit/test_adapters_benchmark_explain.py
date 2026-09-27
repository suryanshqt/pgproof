"""`adapters.benchmark.explain` against real
`EXPLAIN (ANALYZE, BUFFERS, WAL, TIMING OFF, FORMAT JSON)` output (captured
from a live PostgreSQL 17, not hand-written). `docs/PR_ROADMAP.md`'s BE-26
accept criterion: "timing/cost/row changes do not alter plan identity but
join/scan/relation changes do."
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from pgproof.adapters.benchmark.explain import fingerprint_plan, parse_explain

_INDEX_SCAN: list[dict[str, Any]] = [
    {
        "Plan": {
            "Node Type": "Sort",
            "Startup Cost": 34.07,
            "Total Cost": 34.14,
            "Plan Rows": 25,
            "Actual Rows": 100,
            "Actual Loops": 1,
            "Sort Key": ["id"],
            "Shared Hit Blocks": 27,
            "Shared Read Blocks": 2,
            "WAL Records": 0,
            "WAL FPI": 0,
            "WAL Bytes": 0,
            "Plans": [
                {
                    "Node Type": "Bitmap Heap Scan",
                    "Relation Name": "orders",
                    "Alias": "orders",
                    "Total Cost": 33.49,
                    "Plan Rows": 25,
                    "Actual Rows": 100,
                    "Recheck Cond": "(user_id = 3)",
                    "Shared Hit Blocks": 27,
                    "Shared Read Blocks": 2,
                    "WAL Records": 0,
                    "WAL FPI": 0,
                    "WAL Bytes": 0,
                    "Plans": [
                        {
                            "Node Type": "Bitmap Index Scan",
                            "Index Name": "ix_orders_user_id",
                            "Total Cost": 4.47,
                            "Plan Rows": 25,
                            "Actual Rows": 100,
                            "Index Cond": "(user_id = 3)",
                            "Shared Hit Blocks": 0,
                            "Shared Read Blocks": 2,
                            "WAL Records": 0,
                            "WAL FPI": 0,
                            "WAL Bytes": 0,
                        }
                    ],
                }
            ],
        },
        "Planning Time": 0.082,
        "Execution Time": 0.051,
        "Triggers": [],
    }
]

_SEQ_SCAN_JOIN: list[dict[str, Any]] = [
    {
        "Plan": {
            "Node Type": "Nested Loop",
            "Join Type": "Inner",
            "Total Cost": 93.12,
            "Plan Rows": 100,
            "Actual Rows": 100,
            "Shared Hit Blocks": 29,
            "WAL Records": 0,
            "WAL FPI": 0,
            "WAL Bytes": 0,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "users",
                    "Alias": "u",
                    "Total Cost": 1.62,
                    "Plan Rows": 1,
                    "Actual Rows": 1,
                    "Filter": "(id = 3)",
                    "Shared Hit Blocks": 1,
                    "WAL Records": 0,
                    "WAL FPI": 0,
                    "WAL Bytes": 0,
                },
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "orders",
                    "Alias": "o",
                    "Total Cost": 90.5,
                    "Plan Rows": 100,
                    "Actual Rows": 100,
                    "Filter": "(user_id = 3)",
                    "Shared Hit Blocks": 28,
                    "WAL Records": 0,
                    "WAL FPI": 0,
                    "WAL Bytes": 0,
                },
            ],
        },
        "Planning Time": 0.1,
        "Execution Time": 0.2,
        "Triggers": [],
    }
]


def test_the_top_level_node_type_and_relation_are_parsed() -> None:
    diagnostics = parse_explain(_INDEX_SCAN)
    assert diagnostics.plan.node_type == "Sort"
    child = diagnostics.plan.children[0]
    assert child.node_type == "Bitmap Heap Scan"
    assert child.relation_name == "orders"
    grandchild = child.children[0]
    assert grandchild.index_name == "ix_orders_user_id"


def test_sort_key_is_captured() -> None:
    diagnostics = parse_explain(_INDEX_SCAN)
    assert diagnostics.plan.sort_key == ("id",)


def test_buffers_and_wal_are_captured() -> None:
    diagnostics = parse_explain(_INDEX_SCAN)
    assert diagnostics.plan.buffers is not None
    assert diagnostics.plan.buffers.shared_hit_blocks == 27
    assert diagnostics.plan.buffers.shared_read_blocks == 2
    assert diagnostics.plan.wal is not None
    assert diagnostics.plan.wal.records == 0


def test_planning_and_execution_time_are_captured() -> None:
    diagnostics = parse_explain(_INDEX_SCAN)
    assert diagnostics.planning_time_ms == 0.082
    assert diagnostics.execution_time_ms == 0.051


def test_join_type_is_captured() -> None:
    diagnostics = parse_explain(_SEQ_SCAN_JOIN)
    assert diagnostics.plan.join_type == "Inner"
    assert {child.relation_name for child in diagnostics.plan.children} == {"users", "orders"}


def test_cost_and_row_changes_do_not_alter_the_fingerprint() -> None:
    """The exact accept criterion: "timing/cost/row changes do not alter plan
    identity." """
    changed = copy.deepcopy(_INDEX_SCAN)
    changed[0]["Plan"]["Total Cost"] = 999.99
    changed[0]["Plan"]["Actual Rows"] = 1
    changed[0]["Plan"]["Plans"][0]["Actual Rows"] = 1
    changed[0]["Execution Time"] = 999.0
    assert fingerprint_plan(parse_explain(_INDEX_SCAN).plan) == fingerprint_plan(
        parse_explain(changed).plan
    )


def test_buffer_and_wal_changes_do_not_alter_the_fingerprint() -> None:
    changed = copy.deepcopy(_INDEX_SCAN)
    changed[0]["Plan"]["Shared Hit Blocks"] = 999999
    changed[0]["Plan"]["WAL Bytes"] = 12345
    assert fingerprint_plan(parse_explain(_INDEX_SCAN).plan) == fingerprint_plan(
        parse_explain(changed).plan
    )


def test_a_different_parameter_values_condition_text_does_not_alter_the_fingerprint() -> None:
    changed = copy.deepcopy(_INDEX_SCAN)
    changed[0]["Plan"]["Plans"][0]["Recheck Cond"] = "(user_id = 999)"
    changed[0]["Plan"]["Plans"][0]["Plans"][0]["Index Cond"] = "(user_id = 999)"
    assert fingerprint_plan(parse_explain(_INDEX_SCAN).plan) == fingerprint_plan(
        parse_explain(changed).plan
    )


def test_a_different_index_name_alters_the_fingerprint() -> None:
    changed = copy.deepcopy(_INDEX_SCAN)
    changed[0]["Plan"]["Plans"][0]["Plans"][0]["Index Name"] = "ix_orders_status"
    assert fingerprint_plan(parse_explain(_INDEX_SCAN).plan) != fingerprint_plan(
        parse_explain(changed).plan
    )


def test_a_seq_scan_instead_of_an_index_scan_alters_the_fingerprint() -> None:
    fingerprint_index = fingerprint_plan(parse_explain(_INDEX_SCAN).plan)
    fingerprint_join = fingerprint_plan(parse_explain(_SEQ_SCAN_JOIN).plan)
    assert fingerprint_index != fingerprint_join


def test_a_different_relation_alters_the_fingerprint() -> None:
    changed = copy.deepcopy(_SEQ_SCAN_JOIN)
    changed[0]["Plan"]["Plans"][0]["Relation Name"] = "tenants"
    assert fingerprint_plan(parse_explain(_SEQ_SCAN_JOIN).plan) != fingerprint_plan(
        parse_explain(changed).plan
    )


def test_a_different_join_type_alters_the_fingerprint() -> None:
    changed = copy.deepcopy(_SEQ_SCAN_JOIN)
    changed[0]["Plan"]["Join Type"] = "Left"
    assert fingerprint_plan(parse_explain(_SEQ_SCAN_JOIN).plan) != fingerprint_plan(
        parse_explain(changed).plan
    )


def test_normalized_shape_is_a_readable_string() -> None:
    shape = parse_explain(_INDEX_SCAN).normalized_shape
    assert "Bitmap Index Scan using ix_orders_user_id" in shape
    assert "Bitmap Heap Scan on orders" in shape


def test_not_a_format_json_result_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a FORMAT JSON EXPLAIN result"):
        parse_explain({"not": "a list"})
    with pytest.raises(ValueError, match="not a FORMAT JSON EXPLAIN result"):
        parse_explain([])

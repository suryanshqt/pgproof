"""`rules.proposed_tests`: every sketch is plain text, never a file write."""

from __future__ import annotations

import pytest

from pgproof.rules.proposed_tests import (
    ProposedTestKind,
    render_alembic_test,
    render_catalog_test,
    render_equivalence_test,
    render_query_count_test,
    render_raiseload_test,
    render_test_sketch,
)


def test_catalog_sketch_names_the_table_and_columns() -> None:
    sketch = render_catalog_test(table="orders", index_columns=("user_id",))
    assert "orders" in sketch
    assert "user_id" in sketch


def test_alembic_sketch_names_the_revision_and_table() -> None:
    sketch = render_alembic_test(revision="abc123", table="orders")
    assert "abc123" in sketch
    assert "orders" in sketch


def test_query_count_sketch_pins_the_expected_count() -> None:
    sketch = render_query_count_test(operation="list_user_orders", expected_count=1)
    assert "list_user_orders" in sketch
    assert "counter.count == 1" in sketch


def test_raiseload_sketch_names_the_relationship() -> None:
    sketch = render_raiseload_test(relationship="line_items")
    assert sketch.count("line_items") >= 2


def test_equivalence_sketch_compares_baseline_and_treatment() -> None:
    sketch = render_equivalence_test(operation="list_user_orders")
    assert "baseline.list_user_orders()" in sketch
    assert "treatment.list_user_orders()" in sketch


def test_render_test_sketch_dispatches_by_kind() -> None:
    sketch = render_test_sketch(ProposedTestKind.RAISELOAD, relationship="line_items")
    assert sketch == render_raiseload_test(relationship="line_items")


def test_render_test_sketch_rejects_a_param_the_kind_does_not_accept() -> None:
    with pytest.raises(TypeError):
        render_test_sketch(ProposedTestKind.RAISELOAD, revision="abc123")

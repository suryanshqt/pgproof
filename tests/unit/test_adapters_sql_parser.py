"""`adapters.sql.parser` against a corpus shaped by this project's own real
fixture queries (`fixtures/demo-broken/app/repositories.py`), plus targeted
edge cases for each pipeline step. `docs/PR_ROADMAP.md`'s own accept
criterion: "idempotence and semantic-distinction tests."
"""

from __future__ import annotations

import pytest

from pgproof.adapters.sql.parser import canonicalize_placeholders, parse_query
from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.schema import ColumnIR, SchemaIR, SchemaProvenance, TableIR
from pgproof.domain.ir.workload import StatementClass
from pgproof.domain.sources import SourceRef

_P = SchemaProvenance.PHYSICAL_CATALOG
_TENANTS = table_id("public", "tenants")
_ORDERS = table_id("public", "orders")
_ORDER_ITEMS = table_id("public", "order_items")


def _column(table: str, name: str, data_type: str) -> ColumnIR:
    return ColumnIR(
        id=column_id(table, name), name=name, data_type=data_type, nullable=True, provenance=_P
    )


_SCHEMA = SchemaIR(
    provenance=_P,
    tables=(
        TableIR(
            id=_TENANTS,
            schema_name="public",
            name="tenants",
            provenance=_P,
            columns=(_column(_TENANTS, "id", "integer"),),
        ),
        TableIR(
            id=_ORDERS,
            schema_name="public",
            name="orders",
            provenance=_P,
            columns=(
                _column(_ORDERS, "id", "integer"),
                _column(_ORDERS, "tenant_id", "integer"),
                _column(_ORDERS, "user_id", "integer"),
                _column(_ORDERS, "status", "text"),
                _column(_ORDERS, "created_at", "timestamp with time zone"),
            ),
        ),
        TableIR(
            id=_ORDER_ITEMS,
            schema_name="public",
            name="order_items",
            provenance=_P,
            columns=(
                _column(_ORDER_ITEMS, "order_id", "integer"),
                _column(_ORDER_ITEMS, "quantity", "integer"),
            ),
        ),
    ),
)

# Real query shapes, transcribed from `fixtures/demo-broken/app/repositories.py`'s
# actual `select()` statements — not synthetic toy strings.
_CORPUS = [
    (
        "list_tenant_orders",
        "SELECT id FROM orders WHERE tenant_id = %(tenant_id)s AND status = %(status)s "
        "ORDER BY created_at DESC LIMIT %(limit)s",
        StatementClass.READ,
    ),
    (
        "list_user_orders",
        "SELECT id FROM orders WHERE user_id = %s",
        StatementClass.READ,
    ),
    (
        "count_order_items",
        "SELECT id FROM order_items WHERE order_id = %s",
        StatementClass.READ,
    ),
    (
        "insert_order",
        "INSERT INTO orders (tenant_id, status) VALUES (%s, %s)",
        StatementClass.WRITE,
    ),
    (
        "update_order_status",
        "UPDATE orders SET status = %s WHERE id = %s",
        StatementClass.WRITE,
    ),
]


# --------------------------------------------------------------------------- #
# canonicalize_placeholders
# --------------------------------------------------------------------------- #
def test_positional_placeholders_become_dollar_numbered() -> None:
    assert (
        canonicalize_placeholders("SELECT * FROM t WHERE a = %s AND b = %s")
        == "SELECT * FROM t WHERE a = $1 AND b = $2"
    )


def test_named_placeholders_become_dollar_numbered_in_order() -> None:
    assert (
        canonicalize_placeholders("SELECT * FROM t WHERE a = %(a)s AND b = %(b)s")
        == "SELECT * FROM t WHERE a = $1 AND b = $2"
    )


def test_a_percent_inside_a_string_literal_is_never_touched() -> None:
    sql = "SELECT * FROM t WHERE name LIKE '%foo%' AND id = %s"
    assert canonicalize_placeholders(sql) == "SELECT * FROM t WHERE name LIKE '%foo%' AND id = $1"


def test_a_doubled_percent_escape_is_left_alone() -> None:
    sql = "SELECT * FROM t WHERE a %% b = 1"
    assert canonicalize_placeholders(sql) == sql


def test_sql_with_no_placeholders_passes_through_unchanged() -> None:
    sql = "SELECT * FROM orders"
    assert canonicalize_placeholders(sql) == sql


def test_a_modulo_operator_is_not_mistaken_for_a_placeholder() -> None:
    sql = "SELECT a % 2 FROM orders"
    assert canonicalize_placeholders(sql) == sql


def test_a_trailing_percent_with_nothing_after_it_is_left_alone() -> None:
    sql = "SELECT a %"
    assert canonicalize_placeholders(sql) == sql


# --------------------------------------------------------------------------- #
# Statement classification, over the real-shaped corpus
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("_name", "sql", "expected"), _CORPUS, ids=[c[0] for c in _CORPUS])
def test_corpus_statement_classification(_name: str, sql: str, expected: StatementClass) -> None:
    assert parse_query(sql, schema=_SCHEMA).statement_class is expected


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT 1", StatementClass.READ),
        ("WITH x AS (SELECT 1) SELECT * FROM x", StatementClass.READ),
        ("INSERT INTO orders (id) VALUES (1)", StatementClass.WRITE),
        ("UPDATE orders SET status = 'x'", StatementClass.WRITE),
        ("DELETE FROM orders", StatementClass.WRITE),
        ("CREATE TABLE t (id int)", StatementClass.SCHEMA),
        ("ALTER TABLE orders ADD COLUMN x int", StatementClass.SCHEMA),
        ("DROP TABLE orders", StatementClass.SCHEMA),
        ("TRUNCATE orders", StatementClass.SCHEMA),
        ("BEGIN", StatementClass.TRANSACTION),
        ("COMMIT", StatementClass.TRANSACTION),
        ("ROLLBACK", StatementClass.TRANSACTION),
        ("SET search_path = public", StatementClass.CONTROL),
        ("SHOW search_path", StatementClass.CONTROL),
        ("EXPLAIN SELECT 1", StatementClass.CONTROL),
    ],
)
def test_statement_classification_by_node_type(sql: str, expected: StatementClass) -> None:
    assert parse_query(sql, schema=_SCHEMA).statement_class is expected


# --------------------------------------------------------------------------- #
# Idempotence, over the real-shaped corpus
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("_name", "sql", "_expected"), _CORPUS, ids=[c[0] for c in _CORPUS])
def test_corpus_normalization_is_idempotent(
    _name: str, sql: str, _expected: StatementClass
) -> None:
    first = parse_query(sql, schema=_SCHEMA)
    second = parse_query(first.normalized_sql, schema=_SCHEMA)
    assert second.id == first.id
    assert second.normalized_sql == first.normalized_sql


# --------------------------------------------------------------------------- #
# Semantic distinction: literals collapse, structure does not
# --------------------------------------------------------------------------- #
def test_differing_only_by_literal_value_fingerprints_identically() -> None:
    a = parse_query("SELECT id FROM orders WHERE tenant_id = 1", schema=_SCHEMA)
    b = parse_query("SELECT id FROM orders WHERE tenant_id = 42", schema=_SCHEMA)
    assert a.id == b.id


def test_a_literal_and_an_equivalent_placeholder_fingerprint_identically() -> None:
    a = parse_query("SELECT id FROM orders WHERE tenant_id = 1", schema=_SCHEMA)
    b = parse_query("SELECT id FROM orders WHERE tenant_id = %s", schema=_SCHEMA)
    assert a.id == b.id


def test_a_different_table_fingerprints_differently() -> None:
    a = parse_query("SELECT id FROM orders WHERE tenant_id = 1", schema=_SCHEMA)
    b = parse_query("SELECT id FROM order_items WHERE order_id = 1", schema=_SCHEMA)
    assert a.id != b.id


def test_a_different_column_fingerprints_differently() -> None:
    a = parse_query("SELECT id FROM orders WHERE tenant_id = 1", schema=_SCHEMA)
    b = parse_query("SELECT id FROM orders WHERE user_id = 1", schema=_SCHEMA)
    assert a.id != b.id


def test_a_different_cast_type_fingerprints_differently() -> None:
    """The one real gap in `pglast.fingerprint()` this module's own hash closes."""
    a = parse_query("SELECT id FROM orders WHERE id = 1::bigint", schema=_SCHEMA)
    b = parse_query("SELECT id FROM orders WHERE id = 1::int", schema=_SCHEMA)
    assert a.id != b.id
    assert "bigint" in a.normalized_sql
    assert "integer" in b.normalized_sql


def test_a_mixed_placeholder_and_literal_query_numbers_without_collision() -> None:
    result = parse_query(
        "SELECT id FROM orders WHERE tenant_id = %s AND status = 'paid'", schema=_SCHEMA
    )
    assert result.normalized_sql == "SELECT id FROM orders WHERE tenant_id = $1 AND status = $2"
    assert [p.position for p in result.parameters] == [1, 2]


# --------------------------------------------------------------------------- #
# Relation resolution
# --------------------------------------------------------------------------- #
def test_an_unqualified_relation_resolves_against_the_default_schema() -> None:
    result = parse_query("SELECT id FROM orders", schema=_SCHEMA)
    assert result.relations == (_ORDERS,)


def test_a_schema_qualified_relation_resolves_exactly() -> None:
    result = parse_query("SELECT id FROM public.orders", schema=_SCHEMA)
    assert result.relations == (_ORDERS,)


def test_a_join_resolves_every_relation() -> None:
    result = parse_query(
        "SELECT o.id FROM orders o JOIN tenants t ON o.tenant_id = t.id", schema=_SCHEMA
    )
    assert set(result.relations) == {_ORDERS, _TENANTS}


def test_an_unresolvable_relation_is_simply_absent_not_a_guess() -> None:
    result = parse_query("SELECT id FROM nonexistent_table", schema=_SCHEMA)
    assert result.relations == ()
    assert result.statement_class is StatementClass.READ  # still parsed fine


def test_a_cte_name_is_not_treated_as_a_relation() -> None:
    result = parse_query(
        "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent", schema=_SCHEMA
    )
    assert result.relations == (_ORDERS,)


# --------------------------------------------------------------------------- #
# Parameter-type inference
# --------------------------------------------------------------------------- #
def test_a_parameter_compared_to_a_known_column_infers_its_type() -> None:
    result = parse_query("SELECT id FROM orders WHERE tenant_id = %s", schema=_SCHEMA)
    assert [p.data_type for p in result.parameters] == ["integer"]


def test_a_parameter_with_no_inferable_column_is_unknown_not_a_guess() -> None:
    result = parse_query("SELECT %s", schema=_SCHEMA)
    assert [p.data_type for p in result.parameters] == ["unknown"]


def test_the_column_may_be_on_either_side_of_the_comparison() -> None:
    result = parse_query("SELECT id FROM orders WHERE %s = tenant_id", schema=_SCHEMA)
    assert [p.data_type for p in result.parameters] == ["integer"]


def test_a_parameter_compared_to_an_unrecognized_column_is_unknown_not_a_guess() -> None:
    result = parse_query("SELECT id FROM orders WHERE nonexistent_col = %s", schema=_SCHEMA)
    assert [p.data_type for p in result.parameters] == ["unknown"]


# --------------------------------------------------------------------------- #
# Unsupported input
# --------------------------------------------------------------------------- #
def test_unparseable_sql_is_reported_not_dropped() -> None:
    result = parse_query("SELEKT * FROM orders", schema=_SCHEMA)
    assert result.statement_class is StatementClass.UNSUPPORTED
    assert result.parse_error is not None
    assert "SELEKT" in result.parse_error
    assert result.normalized_sql == "SELEKT * FROM orders"  # falls back to the original


def test_a_multi_statement_batch_is_unsupported() -> None:
    result = parse_query("SELECT 1; SELECT 2;", schema=_SCHEMA)
    assert result.statement_class is StatementClass.UNSUPPORTED
    assert result.parse_error is not None


def test_empty_sql_is_unsupported() -> None:
    result = parse_query("", schema=_SCHEMA)
    assert result.statement_class is StatementClass.UNSUPPORTED


def test_an_unsupported_query_still_fingerprints_deterministically() -> None:
    a = parse_query("SELEKT * FROM orders", schema=_SCHEMA)
    b = parse_query("SELEKT * FROM orders", schema=_SCHEMA)
    assert a.id == b.id


# --------------------------------------------------------------------------- #
# call_sites propagation
# --------------------------------------------------------------------------- #
def test_call_sites_are_carried_through_on_both_success_and_failure() -> None:
    site = SourceRef(path="app/repositories.py", line=18, content_hash="sha256:" + "a" * 64)
    ok = parse_query("SELECT 1", schema=_SCHEMA, call_sites=(site,))
    assert ok.call_sites == (site,)
    bad = parse_query("SELEKT 1", schema=_SCHEMA, call_sites=(site,))
    assert bad.call_sites == (site,)

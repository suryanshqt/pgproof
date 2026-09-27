"""`adapters.parameters.extract.extract_predicates` against synthetic
`QueryIR`/`SchemaIR` fixtures. `docs/TECHNICAL_DESIGN.md` section 19:
"supported predicates receive values from actual generated data" — this
module decides which predicates are supported at all.
"""

from __future__ import annotations

from pgproof.adapters.parameters.extract import PredicateKind, extract_predicates
from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.schema import ColumnIR, SchemaIR, SchemaProvenance, TableIR
from pgproof.domain.ir.workload import QueryIR, StatementClass

_P = SchemaProvenance.PHYSICAL_CATALOG
_ORDERS = table_id("public", "orders")
_TENANTS = table_id("public", "tenants")


def _column(table: str, name: str, data_type: str) -> ColumnIR:
    return ColumnIR(
        id=column_id(table, name), name=name, data_type=data_type, nullable=True, provenance=_P
    )


_ORDERS_TABLE = TableIR(
    id=_ORDERS,
    schema_name="public",
    name="orders",
    provenance=_P,
    columns=(
        _column(_ORDERS, "tenant_id", "integer"),
        _column(_ORDERS, "status", "character varying(32)"),
        _column(_ORDERS, "total_cents", "integer"),
        _column(_ORDERS, "created_at", "timestamp with time zone"),
        _column(_ORDERS, "note", "text"),
        _column(_ORDERS, "paid", "boolean"),
    ),
)
_TENANTS_TABLE = TableIR(
    id=_TENANTS, schema_name="public", name="tenants", provenance=_P, columns=()
)
_SCHEMA = SchemaIR(provenance=_P, tables=(_ORDERS_TABLE, _TENANTS_TABLE))


def _query(sql: str, relations: tuple[str, ...] = (_ORDERS,)) -> QueryIR:
    return QueryIR(
        id="sha256:" + "a" * 64,
        statement_class=StatementClass.READ,
        normalized_sql=sql,
        relations=relations,
    )


def test_an_equality_predicate_against_an_integer_column_is_recognized() -> None:
    predicates = extract_predicates(
        _query("SELECT id FROM orders WHERE tenant_id = $1"), schema=_SCHEMA
    )
    assert len(predicates) == 1
    predicate = predicates[0]
    assert predicate.column == column_id(_ORDERS, "tenant_id")
    assert predicate.parameter_position == 1
    assert predicate.operator == "="
    assert predicate.kind is PredicateKind.EQUALITY


def test_a_reversed_comparison_param_on_the_left_is_still_recognized() -> None:
    predicates = extract_predicates(
        _query("SELECT id FROM orders WHERE $1 = tenant_id"), schema=_SCHEMA
    )
    assert len(predicates) == 1
    assert predicates[0].column == column_id(_ORDERS, "tenant_id")


def test_an_and_chain_yields_one_predicate_per_comparison() -> None:
    predicates = extract_predicates(
        _query(
            "SELECT id FROM orders WHERE tenant_id = $1 AND status = $2 "
            "AND created_at >= $3 ORDER BY created_at DESC LIMIT $4"
        ),
        schema=_SCHEMA,
    )
    assert {(p.column, p.parameter_position, p.kind) for p in predicates} == {
        (column_id(_ORDERS, "tenant_id"), 1, PredicateKind.EQUALITY),
        (column_id(_ORDERS, "status"), 2, PredicateKind.EQUALITY),
        (column_id(_ORDERS, "created_at"), 3, PredicateKind.TIMESTAMP_RANGE),
    }


def test_a_numeric_range_comparison_is_recognized() -> None:
    predicates = extract_predicates(
        _query("SELECT id FROM orders WHERE total_cents <= $1"), schema=_SCHEMA
    )
    assert len(predicates) == 1
    assert predicates[0].kind is PredicateKind.NUMERIC_RANGE
    assert predicates[0].operator == "<="


def test_an_or_branch_is_never_descended_into() -> None:
    predicates = extract_predicates(
        _query("SELECT id FROM orders WHERE tenant_id = $1 OR status = $2"), schema=_SCHEMA
    )
    assert predicates == ()


def test_a_text_column_range_comparison_is_not_recognized() -> None:
    predicates = extract_predicates(_query("SELECT id FROM orders WHERE note > $1"), schema=_SCHEMA)
    assert predicates == ()


def test_a_boolean_column_equality_is_still_a_recognized_predicate() -> None:
    # Equality has no type restriction (unlike a numeric/timestamp range): a
    # boolean column just degenerates to at most two frequency groups, which
    # `probe.py`'s realized-frequency logic already handles generically.
    predicates = extract_predicates(_query("SELECT id FROM orders WHERE paid = $1"), schema=_SCHEMA)
    assert len(predicates) == 1
    assert predicates[0].kind is PredicateKind.EQUALITY


def test_a_like_predicate_is_not_recognized() -> None:
    predicates = extract_predicates(
        _query("SELECT id FROM orders WHERE note LIKE $1"), schema=_SCHEMA
    )
    assert predicates == ()


def test_a_column_outside_the_querys_own_relations_is_not_resolved() -> None:
    predicates = extract_predicates(
        _query("SELECT id FROM orders WHERE tenant_id = $1", relations=()), schema=_SCHEMA
    )
    assert predicates == ()


def test_an_unparseable_statement_yields_no_predicates() -> None:
    predicates = extract_predicates(_query("not valid sql at all"), schema=_SCHEMA)
    assert predicates == ()


def test_a_statement_with_no_where_clause_yields_no_predicates() -> None:
    predicates = extract_predicates(_query("SELECT id FROM orders"), schema=_SCHEMA)
    assert predicates == ()

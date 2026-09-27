"""`adapters.candidates.generate.generate_candidates` against synthetic
`SchemaIR`/`ExtractedPredicate` fixtures. `docs/TECHNICAL_DESIGN.md` section
21: single/composite B-tree, five-candidate budget, structural dedup.
"""

from __future__ import annotations

from pgproof.adapters.candidates.generate import generate_candidates
from pgproof.adapters.parameters.extract import ExtractedPredicate, PredicateKind
from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.schema import (
    ConstraintIR,
    ConstraintKind,
    IndexIR,
    IndexKeyIR,
    SchemaIR,
    SchemaProvenance,
    SortDirection,
)

_P = SchemaProvenance.PHYSICAL_CATALOG
_ORDERS = table_id("public", "orders")
_TENANT_ID = column_id(_ORDERS, "tenant_id")
_STATUS = column_id(_ORDERS, "status")
_CREATED_AT = column_id(_ORDERS, "created_at")
_USER_ID = column_id(_ORDERS, "user_id")
_ID = column_id(_ORDERS, "id")


def _predicate(column: str, kind: PredicateKind, position: int = 1) -> ExtractedPredicate:
    return ExtractedPredicate(
        table=_ORDERS, column=column, parameter_position=position, operator="=", kind=kind
    )


def _schema(
    *, indexes: tuple[IndexIR, ...] = (), constraints: tuple[ConstraintIR, ...] = ()
) -> SchemaIR:
    return SchemaIR(provenance=_P, indexes=indexes, constraints=constraints)


def test_a_single_equality_predicate_yields_one_single_column_candidate() -> None:
    result = generate_candidates(_schema(), [_predicate(_TENANT_ID, PredicateKind.EQUALITY)])
    assert len(result.candidates) == 1
    assert result.candidates[0].columns == (_TENANT_ID,)
    assert result.candidates[0].apply_sql.startswith("CREATE INDEX")
    assert "DROP INDEX" in result.candidates[0].revert_sql


def test_two_equality_predicates_yield_a_composite_and_two_singles() -> None:
    predicates = [
        _predicate(_TENANT_ID, PredicateKind.EQUALITY, position=1),
        _predicate(_STATUS, PredicateKind.EQUALITY, position=2),
    ]
    result = generate_candidates(_schema(), predicates)
    columns = {c.columns for c in result.candidates}
    assert (_TENANT_ID, _STATUS) in columns
    assert (_TENANT_ID,) in columns
    assert (_STATUS,) in columns
    assert len(result.candidates) == 3


def test_an_equality_and_a_range_predicate_yield_an_equality_prefix_composite() -> None:
    predicates = [
        _predicate(_TENANT_ID, PredicateKind.EQUALITY, position=1),
        _predicate(_CREATED_AT, PredicateKind.TIMESTAMP_RANGE, position=2),
    ]
    result = generate_candidates(_schema(), predicates)
    columns = {c.columns for c in result.candidates}
    assert (_TENANT_ID, _CREATED_AT) in columns


def test_more_than_five_shapes_discards_the_overflow_with_a_budget_reason() -> None:
    predicates = [
        _predicate(column_id(_ORDERS, f"col{i}"), PredicateKind.EQUALITY, position=i)
        for i in range(6)
    ]
    result = generate_candidates(_schema(), predicates)
    assert len(result.candidates) == 5
    assert any(d.reason == "over_candidate_budget" for d in result.discarded)


def test_a_candidate_matching_an_existing_index_prefix_is_a_duplicate() -> None:
    existing = IndexIR(
        name="ix_orders_tenant_status",
        table=_ORDERS,
        keys=(
            IndexKeyIR(column=_TENANT_ID, direction=SortDirection.ASC),
            IndexKeyIR(column=_STATUS, direction=SortDirection.ASC),
        ),
        provenance=_P,
    )
    result = generate_candidates(
        _schema(indexes=(existing,)), [_predicate(_TENANT_ID, PredicateKind.EQUALITY)]
    )
    assert result.candidates == ()
    assert result.discarded[0].reason == "duplicate_of_existing_index:ix_orders_tenant_status"


def test_a_candidate_matching_a_primary_key_is_a_duplicate() -> None:
    pk = ConstraintIR(
        name="pk_orders",
        kind=ConstraintKind.PRIMARY_KEY,
        table=_ORDERS,
        columns=(_ID,),
        provenance=_P,
    )
    result = generate_candidates(
        _schema(constraints=(pk,)), [_predicate(_ID, PredicateKind.EQUALITY)]
    )
    assert result.candidates == ()
    assert result.discarded[0].reason == "duplicate_of_existing_index:pk_orders"


def test_a_candidate_narrower_than_an_existing_composite_index_is_still_a_duplicate() -> None:
    existing = IndexIR(
        name="ix_orders_tenant_status_created",
        table=_ORDERS,
        keys=(
            IndexKeyIR(column=_TENANT_ID, direction=SortDirection.ASC),
            IndexKeyIR(column=_STATUS, direction=SortDirection.ASC),
            IndexKeyIR(column=_CREATED_AT, direction=SortDirection.ASC),
        ),
        provenance=_P,
    )
    result = generate_candidates(
        _schema(indexes=(existing,)), [_predicate(_TENANT_ID, PredicateKind.EQUALITY)]
    )
    assert result.candidates == ()


def test_a_candidate_wider_than_an_existing_index_is_not_a_duplicate() -> None:
    existing = IndexIR(
        name="ix_orders_tenant_id",
        table=_ORDERS,
        keys=(IndexKeyIR(column=_TENANT_ID),),
        provenance=_P,
    )
    predicates = [
        _predicate(_TENANT_ID, PredicateKind.EQUALITY, position=1),
        _predicate(_STATUS, PredicateKind.EQUALITY, position=2),
    ]
    result = generate_candidates(_schema(indexes=(existing,)), predicates)
    columns = {c.columns for c in result.candidates}
    assert (_TENANT_ID, _STATUS) in columns


def test_a_partial_index_on_the_same_columns_does_not_block_a_candidate() -> None:
    partial = IndexIR(
        name="ix_orders_user_id_paid",
        table=_ORDERS,
        keys=(IndexKeyIR(column=_USER_ID),),
        predicate="status = 'paid'",
        provenance=_P,
    )
    result = generate_candidates(
        _schema(indexes=(partial,)), [_predicate(_USER_ID, PredicateKind.EQUALITY)]
    )
    assert len(result.candidates) == 1


def test_predicates_on_different_tables_generate_independent_candidates() -> None:
    other_table = table_id("public", "users")
    predicates = [
        _predicate(_TENANT_ID, PredicateKind.EQUALITY, position=1),
        ExtractedPredicate(
            table=other_table,
            column=column_id(other_table, "email"),
            parameter_position=2,
            operator="=",
            kind=PredicateKind.EQUALITY,
        ),
    ]
    result = generate_candidates(_schema(), predicates)
    assert {c.table for c in result.candidates} == {_ORDERS, other_table}

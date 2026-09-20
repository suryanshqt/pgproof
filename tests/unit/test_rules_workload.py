"""Workload rule: an uncovered foreign key column, conservative under unresolved indexes."""

from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.context import ContextIR
from pgproof.domain.ir.schema import (
    ConstraintIR,
    ConstraintKind,
    IndexIR,
    IndexKeyIR,
    SchemaIR,
    SchemaProvenance,
    UnsupportedConstruct,
)
from pgproof.domain.recommendations import RecommendationCategory, RecommendationPriority
from pgproof.domain.reconciliation import ReconciliationReport
from pgproof.rules.base import RuleContext
from pgproof.rules.workload import unindexed_foreign_key


def _fk(table: str, column: str, target: str) -> ConstraintIR:
    return ConstraintIR(
        name=f"fk_{table}_{column}",
        kind=ConstraintKind.FOREIGN_KEY,
        table=table_id("public", table),
        columns=(column_id(table_id("public", table), column),),
        referenced_table=table_id("public", target),
        referenced_columns=(column_id(table_id("public", target), "id"),),
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )


def _index(table: str, column: str) -> IndexIR:
    return IndexIR(
        name=f"ix_{table}_{column}",
        table=table_id("public", table),
        keys=(IndexKeyIR(column=column_id(table_id("public", table), column)),),
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )


def _ctx(
    *,
    constraints: tuple[ConstraintIR, ...],
    indexes: tuple[IndexIR, ...] = (),
    unsupported: tuple[UnsupportedConstruct, ...] = (),
) -> RuleContext:
    physical = SchemaIR(
        provenance=SchemaProvenance.STATIC_MIGRATION,
        constraints=constraints,
        indexes=indexes,
        unsupported=unsupported,
    )
    return RuleContext(
        physical=physical,
        orm_schema=SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION),
        code=CodeIR(orm="sqlalchemy"),
        reconciliation=ReconciliationReport(),
        context=ContextIR(),
    )


def test_an_uncovered_foreign_key_is_reported() -> None:
    result = unindexed_foreign_key(_ctx(constraints=(_fk("orders", "user_id", "users"),)))
    assert len(result.recommendations) == 1
    rec = result.recommendations[0]
    assert rec.id == "IDX-001"
    assert rec.category is RecommendationCategory.QUERY
    assert rec.priority is RecommendationPriority.WORTH_EVALUATING
    assert rec.affected_objects == (column_id(table_id("public", "orders"), "user_id"),)


def test_a_foreign_key_with_a_covering_index_is_not_reported() -> None:
    result = unindexed_foreign_key(
        _ctx(
            constraints=(_fk("orders", "user_id", "users"),),
            indexes=(_index("orders", "user_id"),),
        )
    )
    assert result.recommendations == ()


def test_a_foreign_key_covered_by_a_unique_constraint_is_not_reported() -> None:
    unique = ConstraintIR(
        name="uq_orders_user_id",
        kind=ConstraintKind.UNIQUE,
        table=table_id("public", "orders"),
        columns=(column_id(table_id("public", "orders"), "user_id"),),
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )
    result = unindexed_foreign_key(_ctx(constraints=(_fk("orders", "user_id", "users"), unique)))
    assert result.recommendations == ()


def test_a_foreign_key_covered_by_being_the_primary_key_is_not_reported() -> None:
    pk = ConstraintIR(
        name="pk_orders",
        kind=ConstraintKind.PRIMARY_KEY,
        table=table_id("public", "orders"),
        columns=(column_id(table_id("public", "orders"), "user_id"),),
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )
    result = unindexed_foreign_key(_ctx(constraints=(_fk("orders", "user_id", "users"), pk)))
    assert result.recommendations == ()


def test_a_composite_foreign_key_is_not_evaluated() -> None:
    composite = ConstraintIR(
        name="fk_orders_composite",
        kind=ConstraintKind.FOREIGN_KEY,
        table=table_id("public", "orders"),
        columns=(
            column_id(table_id("public", "orders"), "a"),
            column_id(table_id("public", "orders"), "b"),
        ),
        referenced_table=table_id("public", "targets"),
        referenced_columns=(
            column_id(table_id("public", "targets"), "a"),
            column_id(table_id("public", "targets"), "b"),
        ),
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )
    result = unindexed_foreign_key(_ctx(constraints=(composite,)))
    assert result.recommendations == ()


def test_an_unresolved_index_operation_suppresses_the_whole_rule() -> None:
    unsupported = (
        UnsupportedConstruct(
            kind="migration_operation", reason="op.create_index has a non-literal argument"
        ),
    )
    result = unindexed_foreign_key(
        _ctx(constraints=(_fk("orders", "user_id", "users"),), unsupported=unsupported)
    )
    assert result.recommendations == ()
    assert len(result.unsupported_reasons) == 1


def test_multiple_gaps_are_numbered_in_sorted_column_order() -> None:
    result = unindexed_foreign_key(
        _ctx(
            constraints=(
                _fk("orders", "user_id", "users"),
                _fk("order_items", "product_id", "products"),
            )
        )
    )
    assert [r.id for r in result.recommendations] == ["IDX-001", "IDX-002"]

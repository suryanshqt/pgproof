"""Tenancy rule: ask for the isolation model only when there is a real signal to ask about."""

from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.context import ContextIR, TenantModel
from pgproof.domain.ir.schema import ColumnIR, SchemaIR, SchemaProvenance, TableIR
from pgproof.domain.questions import CORE_TENANT_MODEL
from pgproof.domain.recommendations import RecommendationSet
from pgproof.domain.reconciliation import ReconciliationReport
from pgproof.rules.base import RuleContext
from pgproof.rules.tenancy import confirm_isolation_model


def _column(table: str, name: str) -> ColumnIR:
    return ColumnIR(
        id=column_id(table_id("public", table), name),
        name=name,
        data_type="int",
        nullable=False,
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )


def _schema_with(*columns: str) -> SchemaIR:
    table = TableIR(
        id=table_id("public", "orders"),
        schema_name="public",
        name="orders",
        columns=tuple(_column("orders", c) for c in columns),
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )
    return SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION, tables=(table,))


def _ctx(
    *, physical: SchemaIR, orm_schema: SchemaIR | None = None, context: ContextIR
) -> RuleContext:
    return RuleContext(
        physical=physical,
        orm_schema=orm_schema
        if orm_schema is not None
        else SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION),
        code=CodeIR(orm="sqlalchemy"),
        reconciliation=ReconciliationReport(),
        context=context,
    )


def test_a_tenant_id_column_with_no_confirmed_model_asks_the_question() -> None:
    result = confirm_isolation_model(
        _ctx(physical=_schema_with("id", "tenant_id"), context=ContextIR())
    )
    assert [q.id for q in result.questions] == [CORE_TENANT_MODEL]
    assert result.recommendations == ()


def test_no_tenant_id_column_asks_nothing() -> None:
    result = confirm_isolation_model(_ctx(physical=_schema_with("id"), context=ContextIR()))
    assert result == RecommendationSet()


def test_an_already_confirmed_model_asks_nothing_even_with_a_tenant_column() -> None:
    context = ContextIR(tenant_model=TenantModel.SHARED_SCHEMA_TENANT_ID)
    result = confirm_isolation_model(
        _ctx(physical=_schema_with("id", "tenant_id"), context=context)
    )
    assert result == RecommendationSet()


def test_a_tenant_id_column_only_on_the_orm_side_still_asks() -> None:
    result = confirm_isolation_model(
        _ctx(
            physical=_schema_with("id"),
            orm_schema=_schema_with("id", "tenant_id"),
            context=ContextIR(),
        )
    )
    assert [q.id for q in result.questions] == [CORE_TENANT_MODEL]

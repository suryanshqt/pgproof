"""`adapters.architecture.tenancy.find_tenant_enforcement_gaps` against
synthetic `WorkloadIR`/`SchemaIR`/`ContextIR` fixtures.
"""

from __future__ import annotations

from pgproof.adapters.architecture.tenancy import find_tenant_enforcement_gaps
from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.context import ContextIR, TenantModel
from pgproof.domain.ir.schema import ColumnIR, SchemaIR, SchemaProvenance, TableIR
from pgproof.domain.ir.workload import QueryIR, StatementClass, WorkloadCoverage, WorkloadIR

_P = SchemaProvenance.PHYSICAL_CATALOG
_ORDERS = table_id("public", "orders")
_TENANTS = table_id("public", "tenants")
_DIGEST = "sha256:" + "a" * 64


def _column(table: str, name: str) -> ColumnIR:
    return ColumnIR(
        id=column_id(table, name), name=name, data_type="integer", nullable=True, provenance=_P
    )


_SCHEMA = SchemaIR(
    provenance=_P,
    tables=(
        TableIR(
            id=_ORDERS,
            schema_name="public",
            name="orders",
            provenance=_P,
            columns=(_column(_ORDERS, "id"), _column(_ORDERS, "tenant_id")),
        ),
        TableIR(
            id=_TENANTS,
            schema_name="public",
            name="tenants",
            provenance=_P,
            columns=(_column(_TENANTS, "id"),),
        ),
    ),
)
_SHARED_SCHEMA = ContextIR(tenant_model=TenantModel.SHARED_SCHEMA_TENANT_ID)


def _query(
    sql: str, relations: tuple[str, ...], statement_class: StatementClass = StatementClass.READ
) -> QueryIR:
    return QueryIR(
        id="sha256:" + "a" * 64,
        statement_class=statement_class,
        normalized_sql=sql,
        relations=relations,
    )


def _workload(*queries: QueryIR) -> WorkloadIR:
    return WorkloadIR(
        coverage=WorkloadCoverage.COMPLETE_FOR_SELECTION,
        boundary_note="capture completed for the selected test command",
        queries=queries,
    )


def test_a_query_filtering_by_tenant_id_has_no_gap() -> None:
    query = _query("SELECT id FROM orders WHERE tenant_id = $1", (_ORDERS,))
    gaps = find_tenant_enforcement_gaps(_workload(query), _SCHEMA, _SHARED_SCHEMA)
    assert gaps == ()


def test_a_query_with_no_tenant_id_predicate_is_a_gap() -> None:
    query = _query("SELECT id FROM orders WHERE id = $1", (_ORDERS,))
    gaps = find_tenant_enforcement_gaps(_workload(query), _SCHEMA, _SHARED_SCHEMA)
    assert len(gaps) == 1
    assert gaps[0].table == _ORDERS


def test_a_query_against_a_table_with_no_tenant_id_column_is_not_a_gap() -> None:
    query = _query("SELECT id FROM tenants WHERE id = $1", (_TENANTS,))
    gaps = find_tenant_enforcement_gaps(_workload(query), _SCHEMA, _SHARED_SCHEMA)
    assert gaps == ()


def test_nothing_is_checked_without_a_confirmed_shared_schema_tenant_model() -> None:
    query = _query("SELECT id FROM orders WHERE id = $1", (_ORDERS,))
    gaps = find_tenant_enforcement_gaps(_workload(query), _SCHEMA, ContextIR())
    assert gaps == ()


def test_a_write_query_is_also_checked() -> None:
    query = _query(
        "UPDATE orders SET id = $1 WHERE id = $2", (_ORDERS,), statement_class=StatementClass.WRITE
    )
    gaps = find_tenant_enforcement_gaps(_workload(query), _SCHEMA, _SHARED_SCHEMA)
    assert len(gaps) == 1


def test_a_schema_only_statement_is_not_checked() -> None:
    query = _query(
        "ALTER TABLE orders ADD COLUMN x int", (_ORDERS,), statement_class=StatementClass.SCHEMA
    )
    gaps = find_tenant_enforcement_gaps(_workload(query), _SCHEMA, _SHARED_SCHEMA)
    assert gaps == ()

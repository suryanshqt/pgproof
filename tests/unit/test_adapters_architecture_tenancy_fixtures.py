"""`adapters.architecture.tenancy` against the exact real query shapes
`fixtures/demo-broken/app/repositories.py` issues (the same corpus
`tests/unit/test_adapters_sql_parser.py` already transcribes from it, real
code — not a synthetic example) — `list_user_orders` filters only on
`user_id`, never `tenant_id`, a real tenant-enforcement gap this fixture
exists to exercise.
"""

from __future__ import annotations

from pgproof.adapters.architecture.tenancy import find_tenant_enforcement_gaps
from pgproof.adapters.sql.parser import parse_query
from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.context import ContextIR, TenantModel
from pgproof.domain.ir.schema import ColumnIR, SchemaIR, SchemaProvenance, TableIR
from pgproof.domain.ir.workload import WorkloadCoverage, WorkloadIR

_P = SchemaProvenance.PHYSICAL_CATALOG
_TENANTS = table_id("public", "tenants")
_ORDERS = table_id("public", "orders")


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
            ),
        ),
    ),
)
_SHARED_SCHEMA = ContextIR(tenant_model=TenantModel.SHARED_SCHEMA_TENANT_ID)


def _workload(*sql: str) -> WorkloadIR:
    queries = tuple(parse_query(statement, schema=_SCHEMA) for statement in sql)
    return WorkloadIR(
        coverage=WorkloadCoverage.COMPLETE_FOR_SELECTION,
        boundary_note="capture completed for the selected test command",
        queries=queries,
    )


def test_list_tenant_orders_real_query_has_no_gap() -> None:
    workload = _workload(
        "SELECT id FROM orders WHERE tenant_id = %(tenant_id)s AND status = %(status)s "
        "ORDER BY created_at DESC LIMIT %(limit)s"
    )
    assert find_tenant_enforcement_gaps(workload, _SCHEMA, _SHARED_SCHEMA) == ()


def test_list_user_orders_real_query_is_a_real_tenant_enforcement_gap() -> None:
    workload = _workload("SELECT id FROM orders WHERE user_id = %s")
    gaps = find_tenant_enforcement_gaps(workload, _SCHEMA, _SHARED_SCHEMA)
    assert len(gaps) == 1
    assert gaps[0].table == _ORDERS


def test_an_insert_supplying_tenant_id_as_a_value_is_out_of_this_modules_scope() -> None:
    """An `INSERT`'s own `VALUES` clause is not a `WHERE` predicate at all,
    so `extract_predicates` finds nothing to recognize regardless of
    `tenant_id` being supplied as a value — a real limitation, documented
    rather than hidden: inserting into a tenant-scoped table is a different
    question than reading or updating one unscoped, and this module only
    answers the latter.
    """
    workload = _workload("INSERT INTO orders (tenant_id, status) VALUES (%s, %s)")
    gaps = find_tenant_enforcement_gaps(workload, _SCHEMA, _SHARED_SCHEMA)
    assert len(gaps) == 1

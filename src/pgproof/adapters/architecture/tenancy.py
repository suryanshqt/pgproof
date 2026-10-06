"""Tenant-enforcement gaps: a captured query that reads or writes a
tenant-scoped table (one with a `tenant_id` column) with no recognized
predicate on that column. `docs/PR_ROADMAP.md`'s BE-32 "tenant-enforcement
analysis".

Best-effort, not a security guarantee: this reuses `adapters.parameters.
extract`'s own predicate extraction (BE-24), which never descends into an
`OR` branch and only recognizes a `column <op> $N` shape — a query that
filters by tenant through a subquery, a view, a function call, or an `OR`
branch reports a gap here even though it may be correctly scoped. Every
finding is `evidence_kind="inferred"` for exactly this reason: a worth-asking
clarification (`docs/PRODUCT_SPEC.md` section 8), never an assertion that the
query is actually unscoped.
"""

from __future__ import annotations

from dataclasses import dataclass

from pgproof.adapters.parameters.extract import extract_predicates
from pgproof.domain.identifiers import ColumnId, QueryId, TableId, column_id
from pgproof.domain.ir.context import ContextIR, TenantModel
from pgproof.domain.ir.schema import SchemaIR
from pgproof.domain.ir.workload import QueryIR, StatementClass, WorkloadIR

_TENANT_COLUMN_NAME = "tenant_id"


@dataclass(frozen=True)
class TenantEnforcementGap:
    table: TableId
    query: QueryId
    reason: str


def _tenant_column(table: TableId, schema: SchemaIR) -> ColumnId | None:
    for candidate_table in schema.tables:
        if candidate_table.id != table:
            continue
        if any(column.name == _TENANT_COLUMN_NAME for column in candidate_table.columns):
            return column_id(table, _TENANT_COLUMN_NAME)
    return None


def _gaps_for_query(query: QueryIR, schema: SchemaIR) -> tuple[TenantEnforcementGap, ...]:
    if query.statement_class not in (StatementClass.READ, StatementClass.WRITE):
        return ()
    predicates = extract_predicates(query, schema=schema)
    predicate_columns = {predicate.column for predicate in predicates}
    gaps: list[TenantEnforcementGap] = []
    for relation in query.relations:
        tenant_column = _tenant_column(relation, schema)
        if tenant_column is None or tenant_column in predicate_columns:
            continue
        gaps.append(
            TenantEnforcementGap(
                table=relation,
                query=query.id,
                reason=f"{relation} is tenant-scoped, but no recognized predicate on "
                f"{_TENANT_COLUMN_NAME} was found in this query",
            )
        )
    return tuple(gaps)


def find_tenant_enforcement_gaps(
    workload: WorkloadIR, schema: SchemaIR, context: ContextIR
) -> tuple[TenantEnforcementGap, ...]:
    """Nothing to check without a confirmed shared-schema tenant model: a
    single-tenant deployment, or one already isolated by schema/database, has
    no shared-table tenant_id convention for this analysis to even apply to.
    """
    if context.tenant_model is not TenantModel.SHARED_SCHEMA_TENANT_ID:
        return ()
    return tuple(gap for query in workload.queries for gap in _gaps_for_query(query, schema))

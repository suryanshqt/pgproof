"""Tenancy: confirm the isolation model before tenant rules can reason about it.

`docs/PRODUCT_SPEC.md` section 8: "The product MAY ask a targeted clarification
attached to an ambiguous finding." A schema with a `tenant_id`-shaped column
but no confirmed tenant model is exactly that ambiguity: this rule emits the
existing `core_tenant_model` question rather than a recommendation, since
there is nothing concrete to propose until the model is known.
"""

from __future__ import annotations

from pgproof.domain.ir.context import TenantModel
from pgproof.domain.questions import CORE_QUESTIONS, CORE_TENANT_MODEL
from pgproof.domain.recommendations import RecommendationSet
from pgproof.rules.base import RuleContext

RULE_ID = "tenancy.confirm_isolation_model"
_TENANT_COLUMN_NAME = "tenant_id"


def _has_tenant_shaped_column(ctx: RuleContext) -> bool:
    schemas = (ctx.physical, ctx.orm_schema)
    return any(
        column.name == _TENANT_COLUMN_NAME
        for schema in schemas
        for table in schema.tables
        for column in table.columns
    )


def confirm_isolation_model(ctx: RuleContext) -> RecommendationSet:
    if ctx.context.tenant_model is not TenantModel.UNKNOWN:
        return RecommendationSet()
    if not _has_tenant_shaped_column(ctx):
        return RecommendationSet()
    question = next(q for q in CORE_QUESTIONS if q.id == CORE_TENANT_MODEL)
    return RecommendationSet(questions=(question,))

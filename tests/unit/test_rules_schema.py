"""Schema rule: an ORM relationship with no physical foreign key behind it."""

from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.context import ContextIR, TenantModel
from pgproof.domain.ir.schema import SchemaIR, SchemaProvenance
from pgproof.domain.recommendations import (
    RecommendationCategory,
    RecommendationPriority,
    RecommendationSet,
)
from pgproof.domain.reconciliation import Observation, ObservationKind, ReconciliationReport
from pgproof.rules.base import RuleContext
from pgproof.rules.schema import RULE_ID, orm_relationship_without_physical_fk


def _ctx(*observations: Observation, context: ContextIR | None = None) -> RuleContext:
    return RuleContext(
        physical=SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION),
        orm_schema=SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION),
        code=CodeIR(orm="sqlalchemy"),
        reconciliation=ReconciliationReport(observations=observations),
        context=context if context is not None else ContextIR(),
    )


def _observation(source_table: str, target_table: str) -> Observation:
    return Observation(
        kind=ObservationKind.ORM_ONLY_RELATIONSHIP,
        affected_objects=(source_table, target_table),
        summary="x declares a relationship to y with no physical fk",
        evidence_refs=("ev-1",),
    )


def test_a_tenant_target_table_is_categorized_as_tenancy() -> None:
    result = orm_relationship_without_physical_fk(
        _ctx(_observation("public.orders", "public.tenants"))
    )
    assert len(result.recommendations) == 1
    rec = result.recommendations[0]
    assert rec.id == "TENANT-001"
    assert rec.category is RecommendationCategory.TENANCY
    assert rec.priority is RecommendationPriority.REQUIRED_FOR_CORRECTNESS
    assert rec.rule == RULE_ID
    assert rec.evidence_refs == ("ev-1",)
    assert rec.proposed_change is not None


def test_a_non_tenant_target_table_is_categorized_as_schema() -> None:
    result = orm_relationship_without_physical_fk(
        _ctx(_observation("public.orders", "public.users"))
    )
    rec = result.recommendations[0]
    assert rec.id == "SCHEMA-001"
    assert rec.category is RecommendationCategory.SCHEMA


def test_multiple_tenant_findings_are_numbered_sequentially() -> None:
    result = orm_relationship_without_physical_fk(
        _ctx(
            _observation("public.orders", "public.tenants"),
            _observation("public.invoices", "public.tenants"),
        )
    )
    assert [r.id for r in result.recommendations] == ["TENANT-001", "TENANT-002"]


def test_tenant_and_schema_findings_are_numbered_independently() -> None:
    result = orm_relationship_without_physical_fk(
        _ctx(
            _observation("public.orders", "public.tenants"),
            _observation("public.orders", "public.users"),
        )
    )
    ids = {r.id for r in result.recommendations}
    assert ids == {"TENANT-001", "SCHEMA-001"}


def test_other_observation_kinds_are_ignored() -> None:
    other = Observation(
        kind=ObservationKind.MISMATCHED_NULLABILITY,
        affected_objects=("public.orders.status",),
        summary="x",
    )
    result = orm_relationship_without_physical_fk(_ctx(other))
    assert result.recommendations == ()


def test_no_observations_produces_no_recommendations() -> None:
    result = orm_relationship_without_physical_fk(_ctx())
    assert result == RecommendationSet()


def test_a_confirmed_single_tenant_model_overrides_the_name_heuristic() -> None:
    context = ContextIR(tenant_model=TenantModel.SINGLE_TENANT)
    result = orm_relationship_without_physical_fk(
        _ctx(_observation("public.orders", "public.tenants"), context=context)
    )
    rec = result.recommendations[0]
    assert rec.id == "SCHEMA-001"
    assert rec.category is RecommendationCategory.SCHEMA


def test_a_confirmed_multi_tenant_model_is_tenancy_even_without_a_tenant_named_table() -> None:
    context = ContextIR(tenant_model=TenantModel.SHARED_SCHEMA_TENANT_ID)
    result = orm_relationship_without_physical_fk(
        _ctx(_observation("public.orders", "public.accounts"), context=context)
    )
    rec = result.recommendations[0]
    assert rec.id == "TENANT-001"
    assert rec.category is RecommendationCategory.TENANCY

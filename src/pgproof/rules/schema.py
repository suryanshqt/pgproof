"""Schema integrity: an ORM relationship with no physical foreign key behind it.

`docs/TECHNICAL_DESIGN.md` section 14's schema-integrity family. Reuses
`pgproof.domain.reconciliation`'s `ORM_ONLY_RELATIONSHIP` observations directly
rather than re-matching relationships against constraints a second time.

Once `core_tenant_model` is confirmed, it decides tenancy classification
outright — a single-tenant answer means naming a column `tenant_id` was never
a tenancy signal in the first place, so the table-name heuristic used while
`core_tenant_model` is still unknown is only ever a fallback, never a claim
that overrides a confirmed answer.
"""

from __future__ import annotations

from pgproof.domain.identifiers import table_names
from pgproof.domain.ir.context import TenantModel
from pgproof.domain.recommendations import (
    ChangeKind,
    ProposedChange,
    Recommendation,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationSet,
)
from pgproof.domain.reconciliation import ObservationKind
from pgproof.rules.base import RuleContext

RULE_ID = "schema.orm_relationship_without_physical_fk"
_TENANT_TABLE_NAMES = frozenset({"tenant", "tenants"})


def _looks_tenant_related_by_name(target_table: str) -> bool:
    _, target_name = table_names(target_table)
    return target_name.lower() in _TENANT_TABLE_NAMES


def _is_tenant_related(ctx: RuleContext, target_table: str) -> bool:
    if ctx.context.tenant_model is TenantModel.UNKNOWN:
        return _looks_tenant_related_by_name(target_table)
    return ctx.context.tenant_model is not TenantModel.SINGLE_TENANT


def _recommendation_id(prefix: str, sequence: int) -> str:
    return f"{prefix}-{sequence:03d}"


def orm_relationship_without_physical_fk(ctx: RuleContext) -> RecommendationSet:
    findings = [
        observation
        for observation in ctx.reconciliation.observations
        if observation.kind is ObservationKind.ORM_ONLY_RELATIONSHIP
    ]
    counters: dict[str, int] = {}
    recommendations = []
    for observation in findings:
        source_table, target_table = observation.affected_objects
        tenant_related = _is_tenant_related(ctx, target_table)
        prefix = "TENANT" if tenant_related else "SCHEMA"
        counters[prefix] = counters.get(prefix, 0) + 1
        source_name = table_names(source_table)[1]
        target_name = table_names(target_table)[1]
        recommendations.append(
            Recommendation(
                id=_recommendation_id(prefix, counters[prefix]),
                rule=RULE_ID,
                rule_version=1,
                title=f"Enforce the {source_name} to {target_name} relationship physically",
                priority=RecommendationPriority.REQUIRED_FOR_CORRECTNESS,
                category=RecommendationCategory.TENANCY
                if tenant_related
                else RecommendationCategory.SCHEMA,
                statement=observation.summary,
                affected_objects=(source_table, target_table),
                evidence_refs=observation.evidence_refs,
                proposed_change=ProposedChange(
                    kind=ChangeKind.ADD_CONSTRAINT,
                    summary=f"Add a physical foreign key from {source_name} to {target_name}.",
                ),
            )
        )
    return RecommendationSet(recommendations=tuple(recommendations))

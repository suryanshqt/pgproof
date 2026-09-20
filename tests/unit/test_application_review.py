"""Review orchestration: rules, one scenario projection, and its migration plan."""

from pgproof.application.review import run_review
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.context import ContextIR
from pgproof.domain.ir.schema import SchemaIR, SchemaProvenance
from pgproof.domain.reconciliation import ReconciliationReport
from pgproof.domain.scenarios import ScenarioKind
from pgproof.rules.base import RuleContext


def _empty_ctx() -> RuleContext:
    return RuleContext(
        physical=SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION),
        orm_schema=SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION),
        code=CodeIR(orm="sqlalchemy"),
        reconciliation=ReconciliationReport(),
        context=ContextIR(),
    )


def test_run_review_returns_recommendations_scenario_and_plan() -> None:
    result = run_review(_empty_ctx(), ScenarioKind.LAUNCH_MINIMAL)
    assert result.recommendations.recommendations == ()
    assert result.scenario.kind is ScenarioKind.LAUNCH_MINIMAL
    assert result.migration_plan.steps == ()


def test_the_scenario_carries_the_same_recommendation_ids_as_the_rule_output() -> None:
    result = run_review(_empty_ctx(), ScenarioKind.GROWTH_READY)
    assert result.scenario.recommendations == tuple(
        r.id for r in result.recommendations.recommendations
    )


def test_the_migration_plan_expands_from_the_same_recommendations() -> None:
    result = run_review(_empty_ctx(), ScenarioKind.LAUNCH_MINIMAL)
    plan_recommendation_ids = {step.recommendation for step in result.migration_plan.steps}
    assert plan_recommendation_ids <= {r.id for r in result.recommendations.recommendations}

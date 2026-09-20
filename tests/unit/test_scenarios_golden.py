"""Golden: context changes deterministically add/remove affected decisions.

`docs/PR_ROADMAP.md`'s BE-14 accept criterion, demonstrated against the real,
unmodified `fixtures/demo-broken` fixture: confirming the tenant model changes
which recommendation TENANT-001's underlying observation produces, attributed
to the exact answer that caused it — and a migration plan built from either
run's recommendations is topologically valid.
"""

from pathlib import Path

from pgproof.adapters.repository.alembic_static import parse_migrations
from pgproof.adapters.repository.sqlalchemy_static import parse_models
from pgproof.domain.ir.context import AnswerState, ContextIR
from pgproof.domain.migration_plan import build_migration_plan, topological_order
from pgproof.domain.questions import CORE_RETENTION, CORE_TENANT_MODEL, apply_core_answer
from pgproof.domain.reconciliation import reconcile
from pgproof.domain.scenarios import DeltaKind, ScenarioKind, build_scenario_diff
from pgproof.rules import RULES, RuleContext, run_rules

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _rule_context(context: ContextIR) -> RuleContext:
    root = FIXTURES / "demo-broken"
    versions = sorted((root / "migrations" / "versions").glob("*.py"))
    physical = parse_migrations(versions, root=root).schema
    orm = parse_models([root / "app" / "models.py"], root=root)
    reconciliation = reconcile(physical, orm.schema, orm.code)
    return RuleContext(
        physical=physical,
        orm_schema=orm.schema,
        code=orm.code,
        reconciliation=reconciliation,
        context=context,
    )


def test_confirming_single_tenant_removes_the_tenancy_recommendation_and_adds_a_schema_one() -> (
    None
):
    base_context = ContextIR()
    target_context = apply_core_answer(
        base_context, CORE_TENANT_MODEL, state=AnswerState.ANSWERED, value="single_tenant"
    )
    base_result = run_rules(_rule_context(base_context), RULES)
    target_result = run_rules(_rule_context(target_context), RULES)

    assert "TENANT-001" in {r.id for r in base_result.recommendations}
    assert "SCHEMA-001" in {r.id for r in target_result.recommendations}

    diff = build_scenario_diff(
        ScenarioKind.LAUNCH_MINIMAL,
        ScenarioKind.LAUNCH_MINIMAL,
        base_result,
        target_result,
        base_context=base_context,
        target_context=target_context,
    )
    kinds_by_recommendation = {delta.recommendation: delta.kind for delta in diff.deltas}
    assert kinds_by_recommendation["TENANT-001"] is DeltaKind.REMOVED
    assert kinds_by_recommendation["SCHEMA-001"] is DeltaKind.ADDED
    assert all(delta.caused_by == CORE_TENANT_MODEL for delta in diff.deltas)


def test_answering_an_unrelated_question_changes_nothing() -> None:
    base_context = ContextIR()
    target_context = apply_core_answer(
        base_context, CORE_RETENTION, state=AnswerState.ANSWERED, value="GDPR"
    )
    base_result = run_rules(_rule_context(base_context), RULES)
    target_result = run_rules(_rule_context(target_context), RULES)
    diff = build_scenario_diff(
        ScenarioKind.LAUNCH_MINIMAL,
        ScenarioKind.LAUNCH_MINIMAL,
        base_result,
        target_result,
        base_context=base_context,
        target_context=target_context,
    )
    assert diff.deltas == ()


def test_the_migration_plan_from_either_run_is_topologically_valid() -> None:
    result = run_rules(_rule_context(ContextIR()), RULES)
    plan = build_migration_plan(result.recommendations, ScenarioKind.LAUNCH_MINIMAL)
    order = topological_order(plan)
    assert set(order) == {step.id for step in plan.steps}
    # Every step appears after everything it depends on.
    position = {step_id: index for index, step_id in enumerate(order)}
    for step in plan.steps:
        for dependency in step.dependency_ids:
            assert position[dependency] < position[step.id]

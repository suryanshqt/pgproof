"""Golden: the rule engine against the real demo-broken/demo-clean fixtures.

`docs/PR_ROADMAP.md`'s BE-13 accept criterion: the clean fixture has no
headline result, and every recommendation traces to evidence/assumptions.
Per `fixtures/demo-clean/EXPECTED.yaml`'s own "optional hardening suggestions
are permitted only outside the headline set," headline means any recommendation
whose priority is not `optional_hardening` — none of Ring A's rules ever emit
that priority, so "no headline result" here means simply "no recommendations."
"""

from pathlib import Path

from pgproof.adapters.repository.alembic_static import parse_migrations
from pgproof.adapters.repository.sqlalchemy_static import parse_models
from pgproof.domain.ir.context import ContextIR
from pgproof.domain.recommendations import RecommendationPriority
from pgproof.domain.reconciliation import reconcile
from pgproof.rules import RULES, RuleContext, run_rules

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _run(name: str) -> RuleContext:
    root = FIXTURES / name
    versions = sorted((root / "migrations" / "versions").glob("*.py"))
    physical = parse_migrations(versions, root=root).schema
    orm = parse_models([root / "app" / "models.py"], root=root)
    reconciliation = reconcile(physical, orm.schema, orm.code)
    return RuleContext(
        physical=physical,
        orm_schema=orm.schema,
        code=orm.code,
        reconciliation=reconciliation,
        context=ContextIR(),
    )


def test_demo_broken_surfaces_the_planted_tenant_gap() -> None:
    result = run_rules(_run("demo-broken"), RULES)
    tenant_findings = [r for r in result.recommendations if r.id == "TENANT-001"]
    assert len(tenant_findings) == 1
    finding = tenant_findings[0]
    assert finding.priority is RecommendationPriority.REQUIRED_FOR_CORRECTNESS
    assert finding.evidence_refs
    assert finding.proposed_change is not None


def test_demo_broken_surfaces_real_unindexed_foreign_keys() -> None:
    result = run_rules(_run("demo-broken"), RULES)
    index_findings = {
        r.affected_objects
        for r in result.recommendations
        if r.rule == "workload.unindexed_foreign_key"
    }
    assert index_findings == {
        ("public.orders.user_id",),
        ("public.order_items.product_id",),
    }


def test_demo_clean_has_no_headline_recommendation() -> None:
    result = run_rules(_run("demo-clean"), RULES)
    headline = [
        r
        for r in result.recommendations
        if r.priority is not RecommendationPriority.OPTIONAL_HARDENING
    ]
    assert headline == []


def test_demo_clean_index_analysis_is_conservatively_silent_and_says_why() -> None:
    result = run_rules(_run("demo-clean"), RULES)
    assert not any(r.rule == "workload.unindexed_foreign_key" for r in result.recommendations)
    assert any("index" in reason for reason in result.unsupported_reasons)


def test_both_fixtures_ask_to_confirm_the_tenant_model_by_default() -> None:
    broken = run_rules(_run("demo-broken"), RULES)
    clean = run_rules(_run("demo-clean"), RULES)
    assert [q.id for q in broken.questions] == ["core_tenant_model"]
    assert [q.id for q in clean.questions] == ["core_tenant_model"]


def test_every_recommendation_on_both_fixtures_traces_to_a_proposed_change_or_question() -> None:
    for name in ("demo-broken", "demo-clean"):
        result = run_rules(_run(name), RULES)
        for recommendation in result.recommendations:
            assert (
                recommendation.proposed_change is not None
                or recommendation.blocking_question is not None
            )
            assert recommendation.affected_objects

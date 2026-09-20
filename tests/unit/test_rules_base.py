"""The rule protocol: `Rule`, `RuleContext`, and folding every rule's output together."""

from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.context import ContextIR
from pgproof.domain.ir.schema import SchemaIR, SchemaProvenance
from pgproof.domain.questions import CORE_QUESTIONS
from pgproof.domain.recommendations import (
    ChangeKind,
    ProposedChange,
    Recommendation,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationSet,
)
from pgproof.domain.reconciliation import ReconciliationReport
from pgproof.rules.base import Rule, RuleContext, run_rules


def _empty_context() -> RuleContext:
    return RuleContext(
        physical=SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION),
        orm_schema=SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION),
        code=CodeIR(orm="sqlalchemy"),
        reconciliation=ReconciliationReport(),
        context=ContextIR(),
    )


def _recommendation(rule_id: str, recommendation_id: str) -> Recommendation:
    return Recommendation(
        id=recommendation_id,
        rule=rule_id,
        rule_version=1,
        title="x",
        priority=RecommendationPriority.WORTH_EVALUATING,
        category=RecommendationCategory.SCHEMA,
        statement="x",
        affected_objects=("public.x",),
        proposed_change=ProposedChange(kind=ChangeKind.ADD_INDEX, summary="x"),
    )


def test_run_rules_folds_recommendations_from_every_rule() -> None:
    rule_a = Rule(
        id="a.rule",
        version=1,
        evaluate=lambda _ctx: RecommendationSet(
            recommendations=(_recommendation("a.rule", "AA-001"),)
        ),
    )
    rule_b = Rule(
        id="b.rule",
        version=1,
        evaluate=lambda _ctx: RecommendationSet(
            recommendations=(_recommendation("b.rule", "BB-001"),)
        ),
    )
    result = run_rules(_empty_context(), (rule_a, rule_b))
    assert [r.id for r in result.recommendations] == ["AA-001", "BB-001"]


def test_run_rules_folds_questions_and_unsupported_reasons() -> None:
    question = CORE_QUESTIONS[0]
    rule = Rule(
        id="a.rule",
        version=1,
        evaluate=lambda _ctx: RecommendationSet(
            questions=(question,), unsupported_reasons=("skipped",)
        ),
    )
    result = run_rules(_empty_context(), (rule,))
    assert result.questions == (question,)
    assert result.unsupported_reasons == ("skipped",)


def test_run_rules_with_no_rules_returns_an_empty_set() -> None:
    result = run_rules(_empty_context(), ())
    assert result == RecommendationSet()


def test_run_rules_preserves_rule_order() -> None:
    order = []

    def _make(name: str) -> Rule:
        def _evaluate(_ctx: RuleContext) -> RecommendationSet:
            order.append(name)
            return RecommendationSet()

        return Rule(id=f"{name}.rule", version=1, evaluate=_evaluate)

    run_rules(_empty_context(), (_make("first"), _make("second")))
    assert order == ["first", "second"]

"""The rule protocol: a pure function from already-loaded IR to a `RecommendationSet`.

`tests/unit/test_dependency_boundaries.py` bans every I/O module and every
adapter/port import from `pgproof.rules` — a rule cannot open a file, read an
environment variable, or call an adapter. It only ever sees what a caller
(outside this layer) already parsed and hands it in `RuleContext`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pgproof.domain.identifiers import RuleId
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.context import ContextIR
from pgproof.domain.ir.schema import SchemaIR
from pgproof.domain.questions import MaterialQuestion
from pgproof.domain.recommendations import Recommendation, RecommendationSet
from pgproof.domain.reconciliation import ReconciliationReport


@dataclass(frozen=True)
class RuleContext:
    """Everything BE-10/BE-12 can hand a rule; no rule reaches past this."""

    physical: SchemaIR
    orm_schema: SchemaIR
    code: CodeIR
    reconciliation: ReconciliationReport
    context: ContextIR


@dataclass(frozen=True)
class Rule:
    """One registered rule. `version` is independent of wording: it only moves
    when the rule's logic changes, per `docs/TECHNICAL_DESIGN.md` section 13's
    "a rule change increments rule version and invalidates its derived artifacts."
    """

    id: RuleId
    version: int
    evaluate: Callable[[RuleContext], RecommendationSet]


def run_rules(ctx: RuleContext, rules: tuple[Rule, ...]) -> RecommendationSet:
    """Every registered rule's output, folded into one set.

    Deterministic in the input rules' own order; a rule that raises is a bug in
    that rule, not something this function catches or masks.
    """
    recommendations: list[Recommendation] = []
    questions: list[MaterialQuestion] = []
    unsupported_reasons: list[str] = []
    for rule in rules:
        result = rule.evaluate(ctx)
        recommendations.extend(result.recommendations)
        questions.extend(result.questions)
        unsupported_reasons.extend(result.unsupported_reasons)
    return RecommendationSet(
        recommendations=tuple(recommendations),
        questions=tuple(questions),
        unsupported_reasons=tuple(unsupported_reasons),
    )

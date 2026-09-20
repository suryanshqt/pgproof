"""Orchestrates one review: the rule engine, one scenario projection, and its
migration plan, over already-loaded IR.

`docs/ARCHITECTURE.md` section 8.3's "Review" flow: evidence graph -> pure
rule engine -> recommendations -> scenario/migration-plan. Every step here is
`domain`/`rules` composition, no filesystem or Click import — `cli.commands.
review` does the parsing, reconciliation, config I/O, and artifact writing,
then calls this module for the decision itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from pgproof.domain.migration_plan import MigrationPlan, build_migration_plan
from pgproof.domain.recommendations import RecommendationSet
from pgproof.domain.scenarios import Scenario, ScenarioKind, build_scenario
from pgproof.rules import RULES, RuleContext, run_rules


@dataclass(frozen=True)
class ReviewResult:
    recommendations: RecommendationSet
    scenario: Scenario
    migration_plan: MigrationPlan


def run_review(ctx: RuleContext, scenario_kind: ScenarioKind) -> ReviewResult:
    recommendations = run_rules(ctx, RULES)
    scenario = build_scenario(scenario_kind, recommendations, ctx.context)
    plan = build_migration_plan(recommendations.recommendations, scenario_kind)
    return ReviewResult(recommendations=recommendations, scenario=scenario, migration_plan=plan)

"""The deterministic rule engine: pure functions of already-loaded IR to `RecommendationSet`."""

from __future__ import annotations

from pgproof.rules.base import Rule, RuleContext, run_rules
from pgproof.rules.registry import RULES

__all__ = ["RULES", "Rule", "RuleContext", "run_rules"]

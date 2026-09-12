"""Cross-artifact reference integrity.

A single artifact cannot validate a reference into another artifact, so these
pure functions check the joins the product depends on: every recommendation must
trace to evidence that exists, and every blocking question must exist.

`docs/PRODUCT_SPEC.md` section 7 requires every recommendation to be traceable.
These functions are how that is machine-checked; they perform no I/O and execute
no rule.
"""

from __future__ import annotations

from pgproof.domain.evidence import EvidenceGraph
from pgproof.domain.graph import GraphIR
from pgproof.domain.recommendations import RecommendationSet
from pgproof.domain.scenarios import ScenarioSet


def dangling_evidence_refs(
    recommendations: RecommendationSet, evidence: EvidenceGraph
) -> tuple[str, ...]:
    """Evidence ids cited by a recommendation that the evidence graph does not hold."""
    known = evidence.ids
    return tuple(
        sorted(
            {
                ref
                for recommendation in recommendations.recommendations
                for ref in recommendation.evidence_refs
                if ref not in known
            }
        )
    )


def untraceable_recommendations(
    recommendations: RecommendationSet, evidence: EvidenceGraph
) -> tuple[str, ...]:
    """Recommendations that cite no resolvable evidence at all."""
    known = evidence.ids
    return tuple(
        sorted(
            recommendation.id
            for recommendation in recommendations.recommendations
            if not any(ref in known for ref in recommendation.evidence_refs)
        )
    )


def dangling_question_refs(recommendations: RecommendationSet) -> tuple[str, ...]:
    """Blocking questions and affected-recommendation links that do not resolve."""
    question_ids = {question.id for question in recommendations.questions}
    recommendation_ids = {item.id for item in recommendations.recommendations}
    problems = {
        item.blocking_question
        for item in recommendations.recommendations
        if item.blocking_question is not None and item.blocking_question not in question_ids
    }
    problems |= {
        affected
        for question in recommendations.questions
        for affected in question.affected_recommendations
        if affected not in recommendation_ids
    }
    return tuple(sorted(problems))


def dangling_scenario_refs(
    scenarios: ScenarioSet, recommendations: RecommendationSet
) -> tuple[str, ...]:
    """Scenario and diff references to recommendations that do not exist."""
    known = {item.id for item in recommendations.recommendations}
    cited = {
        recommendation
        for scenario in scenarios.scenarios
        for recommendation in scenario.recommendations
    }
    cited |= {delta.recommendation for diff in scenarios.diffs for delta in diff.deltas}
    return tuple(sorted(cited - known))


def graph_node_kinds_present(graph: GraphIR) -> frozenset[str]:
    """Node kinds actually used, so an ER view can assert what it excludes."""
    return frozenset(node.kind.value for node in graph.nodes)

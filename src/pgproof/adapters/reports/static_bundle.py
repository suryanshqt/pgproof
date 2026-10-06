"""The self-contained static report: `docs/PRODUCT_SPEC.md` section 14's
"static shareable report bundle" — one Markdown file, no server, no account.

Built from already-parsed domain models only, so nothing here can reach a raw
file path, a database connection, or a private parameter value: those types
do not exist in `RecommendationSet`/`EvidenceGraph`/`DecisionLog` to begin with.
"""

from __future__ import annotations

from pgproof.domain.decisions import Decision, DecisionLog
from pgproof.domain.evidence import EvidenceGraph
from pgproof.domain.recommendations import Recommendation, RecommendationSet

_PRIORITY_SEVERITY = {
    "required_for_correctness": 0,
    "required_by_confirmed_requirements": 1,
    "verified_improvement": 2,
    "worth_evaluating": 3,
    "optional_hardening": 4,
}


def _evidence_sources(recommendation: Recommendation, evidence: EvidenceGraph) -> list[str]:
    by_id = {ref.id: ref for ref in evidence.refs}
    sources = []
    for ref_id in recommendation.evidence_refs:
        ref = by_id.get(ref_id)
        if ref is None or ref.source is None:
            continue
        location = ref.source.path
        if ref.source.line is not None:
            location += f":{ref.source.line}"
        sources.append(location)
    return sources


def render_recommendations_section(
    recommendations: RecommendationSet, evidence: EvidenceGraph
) -> str:
    lines = ["## Recommendations", ""]
    if not recommendations.recommendations:
        lines.append("No recommendations.")
        return "\n".join(lines) + "\n"
    ordered = sorted(
        recommendations.recommendations,
        key=lambda r: (_PRIORITY_SEVERITY[r.priority.value], r.id),
    )
    for recommendation in ordered:
        lines.append(f"### {recommendation.id}: {recommendation.title}")
        lines.append("")
        lines.append(f"- Priority: `{recommendation.priority.value}`")
        lines.append(f"- Category: `{recommendation.category.value}`")
        lines.append("")
        lines.append(recommendation.statement)
        sources = _evidence_sources(recommendation, evidence)
        if sources:
            lines.append("")
            lines.extend(f"- {source}" for source in sources)
        lines.append("")
    return "\n".join(lines)


def _decision_line(decision: Decision) -> str:
    revisit = f" (revisit: {decision.revisit_condition})" if decision.revisit_condition else ""
    return f"- `{decision.recommendation}` — **{decision.kind.value}**: {decision.reason}{revisit}"


def render_decisions_section(decisions: DecisionLog) -> str:
    lines = ["## Decisions", ""]
    if not decisions.decisions:
        lines.append("No decisions recorded yet.")
        return "\n".join(lines) + "\n"
    lines.extend(_decision_line(decision) for decision in decisions.decisions)
    return "\n".join(lines) + "\n"


def render_static_bundle(
    recommendations: RecommendationSet, evidence: EvidenceGraph, decisions: DecisionLog
) -> str:
    """One Markdown document: headline findings plus the decisions made against
    them. Nothing streams, nothing requires a running server to read it.
    """
    return "\n".join(
        [
            "# pgproof static report",
            "",
            render_recommendations_section(recommendations, evidence),
            render_decisions_section(decisions),
        ]
    )

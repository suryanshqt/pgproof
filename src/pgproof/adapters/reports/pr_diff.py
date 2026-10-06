"""Compact PR-diff summary. `docs/PR_ROADMAP.md` BE-34's accept criterion:
"changed-decision-only PR comment" — a reviewer should see what decisions
moved since the base branch, not a repeat of the whole report.
"""

from __future__ import annotations

from pgproof.domain.decisions import Decision, DecisionLog


def _identity(decision: Decision) -> tuple[str, str, str]:
    return (decision.recommendation, decision.kind.value, decision.decided_at)


def changed_decisions(*, base: DecisionLog, head: DecisionLog) -> tuple[Decision, ...]:
    """Decisions present in `head` but not in `base`, in `head`'s own order.

    Identity is `(recommendation, kind, decided_at)`: a re-decision is a new
    `Decision` entry (the log is append-only), so comparing by value rather
    than position is what makes "unchanged" mean "unchanged".
    """
    seen = {_identity(decision) for decision in base.decisions}
    return tuple(decision for decision in head.decisions if _identity(decision) not in seen)


def render_pr_comment(changed: tuple[Decision, ...]) -> str:
    if not changed:
        return "pgproof: no decisions changed on this branch.\n"
    lines = ["pgproof: decisions changed on this branch", ""]
    lines.extend(
        f"- `{decision.recommendation}` → **{decision.kind.value}**: {decision.reason}"
        for decision in changed
    )
    return "\n".join(lines) + "\n"

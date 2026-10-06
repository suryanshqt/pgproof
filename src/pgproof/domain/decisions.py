"""The decision log. `docs/PRODUCT_SPEC.md` section 13: "the user can accept,
reject, or defer a recommendation with a reason and revisit condition... a
rejected/deferred recommendation does not reappear unless its evidence or
revisit condition changes."

`input_manifest_hash` is the evidence state a decision was made against —
the same convention `proof_id` already uses (`domain.identifiers.proof_id`):
a content hash of declared inputs, not a wall-clock time or container id.
`should_reactivate` compares that hash against the current one; a changed
hash is the one automatically-checkable half of "evidence... changes".
`revisit_condition` is free text a human re-reads (this product has no
telemetry or scheduler to evaluate "when traffic exceeds X" against), so it
never participates in that comparison — only evidence drift does.
"""

from __future__ import annotations

from pgproof.domain.identifiers import RecommendationId
from pgproof.domain.primitives import Contract, NonEmptyText, Rfc3339Utc, Sha256, SnakeCaseEnum


class DecisionKind(SnakeCaseEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class Decision(Contract):
    """One decision against one recommendation."""

    recommendation: RecommendationId
    kind: DecisionKind
    reason: NonEmptyText
    revisit_condition: NonEmptyText | None = None
    decided_at: Rfc3339Utc
    input_manifest_hash: Sha256


class DecisionLog(Contract):
    """Every decision made so far. Local project data, never telemetry."""

    decisions: tuple[Decision, ...] = ()


def latest_decision(log: DecisionLog, recommendation: RecommendationId) -> Decision | None:
    """The most recently recorded decision for one recommendation, or `None`
    if it was never decided. `decisions` is append-only (a re-decision is a
    new entry, not an edit in place), so the last matching entry wins.
    """
    matches = [decision for decision in log.decisions if decision.recommendation == recommendation]
    return matches[-1] if matches else None


def should_reactivate(decision: Decision, *, current_input_manifest_hash: Sha256) -> bool:
    """`True` when the recommendation should reappear: its evidence has
    moved since the decision was made. An accepted decision is never
    reactivated by this function — "reappearing" is a concept for a
    rejected/deferred recommendation the product is currently suppressing;
    an accepted one is already acted on, not suppressed.
    """
    if decision.kind is DecisionKind.ACCEPTED:
        return False
    return decision.input_manifest_hash != current_input_manifest_hash

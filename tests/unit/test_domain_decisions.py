"""`domain.decisions`: the accept/reject/defer model and its reactivation rule.

`docs/PRODUCT_SPEC.md` section 13's accept criterion is exercised directly:
a rejected/deferred recommendation stays quiet until its evidence changes.
"""

from __future__ import annotations

from pgproof.domain.decisions import (
    Decision,
    DecisionKind,
    DecisionLog,
    latest_decision,
    should_reactivate,
)

_HASH_A = "sha256:" + "a" * 64
_HASH_B = "sha256:" + "b" * 64


def _decision(
    *,
    recommendation: str = "IDX-001",
    kind: DecisionKind = DecisionKind.DEFERRED,
    input_manifest_hash: str = _HASH_A,
) -> Decision:
    return Decision(
        recommendation=recommendation,
        kind=kind,
        reason="not now, revisit after the next load test",
        decided_at="2026-01-01T00:00:00Z",
        input_manifest_hash=input_manifest_hash,
    )


def test_an_empty_log_has_no_latest_decision() -> None:
    assert latest_decision(DecisionLog(), "IDX-001") is None


def test_latest_decision_ignores_other_recommendations() -> None:
    log = DecisionLog(decisions=(_decision(recommendation="IDX-002"),))
    assert latest_decision(log, "IDX-001") is None


def test_latest_decision_returns_the_last_entry_for_a_repeated_recommendation() -> None:
    first = _decision(kind=DecisionKind.DEFERRED)
    second = _decision(kind=DecisionKind.REJECTED)
    log = DecisionLog(decisions=(first, second))
    assert latest_decision(log, "IDX-001") is second


def test_an_accepted_decision_never_reactivates_even_on_evidence_drift() -> None:
    decision = _decision(kind=DecisionKind.ACCEPTED, input_manifest_hash=_HASH_A)
    assert should_reactivate(decision, current_input_manifest_hash=_HASH_B) is False


def test_a_deferred_decision_stays_quiet_while_the_evidence_hash_is_unchanged() -> None:
    decision = _decision(kind=DecisionKind.DEFERRED, input_manifest_hash=_HASH_A)
    assert should_reactivate(decision, current_input_manifest_hash=_HASH_A) is False


def test_a_deferred_decision_reactivates_once_the_evidence_hash_changes() -> None:
    decision = _decision(kind=DecisionKind.DEFERRED, input_manifest_hash=_HASH_A)
    assert should_reactivate(decision, current_input_manifest_hash=_HASH_B) is True


def test_a_rejected_decision_reactivates_on_evidence_drift_the_same_as_deferred() -> None:
    decision = _decision(kind=DecisionKind.REJECTED, input_manifest_hash=_HASH_A)
    assert should_reactivate(decision, current_input_manifest_hash=_HASH_B) is True

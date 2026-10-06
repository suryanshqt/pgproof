"""`adapters.reports.pr_diff`: changed-decisions-only PR comment."""

from __future__ import annotations

from pgproof.adapters.reports.pr_diff import changed_decisions, render_pr_comment
from pgproof.domain.decisions import Decision, DecisionKind, DecisionLog

_HASH = "sha256:" + "a" * 64


def _decision(
    recommendation: str = "IDX-001",
    kind: DecisionKind = DecisionKind.DEFERRED,
    decided_at: str = "2026-01-01T00:00:00Z",
) -> Decision:
    return Decision(
        recommendation=recommendation,
        kind=kind,
        reason="not now",
        decided_at=decided_at,
        input_manifest_hash=_HASH,
    )


def test_a_decision_absent_from_base_is_reported_as_changed() -> None:
    head = DecisionLog(decisions=(_decision(),))
    assert changed_decisions(base=DecisionLog(), head=head) == head.decisions


def test_a_decision_present_in_both_logs_is_not_reported() -> None:
    decision = _decision()
    log = DecisionLog(decisions=(decision,))
    assert changed_decisions(base=log, head=log) == ()


def test_a_re_decision_with_a_new_timestamp_is_reported_as_changed() -> None:
    base = DecisionLog(decisions=(_decision(kind=DecisionKind.DEFERRED),))
    head = DecisionLog(
        decisions=(
            _decision(kind=DecisionKind.DEFERRED),
            _decision(kind=DecisionKind.ACCEPTED, decided_at="2026-02-01T00:00:00Z"),
        )
    )
    changed = changed_decisions(base=base, head=head)
    assert len(changed) == 1
    assert changed[0].kind is DecisionKind.ACCEPTED


def test_no_changes_renders_a_quiet_comment() -> None:
    assert render_pr_comment(()) == "pgproof: no decisions changed on this branch.\n"


def test_a_changed_decision_is_named_in_the_comment() -> None:
    comment = render_pr_comment((_decision(),))
    assert "IDX-001" in comment
    assert "deferred" in comment

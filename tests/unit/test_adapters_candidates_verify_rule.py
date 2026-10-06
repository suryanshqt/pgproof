"""`adapters.candidates.verify._read_benefit_verified` — the pure decision
rule, isolated from the real connections `verify_candidate` itself needs.
`docs/PR_ROADMAP.md`'s BE-28 accept criterion: "rejects a marginal
candidate" must hold on more than a bare `ratio > 1.0`, since that alone lets
pure measurement noise on a near-identical A1/B pair read as a real benefit
about half the time (confirmed empirically against a real no-op candidate in
`tests/integration/test_adapters_candidates_verify.py`).
"""

from __future__ import annotations

from dataclasses import replace

from pgproof.adapters.benchmark.run import ExperimentResult
from pgproof.adapters.candidates.verify import _MIN_VERIFIED_RATIO, _read_benefit_verified

_BASE = ExperimentResult(
    control_a1=None,
    treatment_b=None,
    drift_control_a2=None,
    explain_a1=None,
    explain_b=None,
    absolute_saving_us=100.0,
    ratio=2.0,
    drift_fraction=0.01,
    high_variance=False,
    drift_detected=False,
    inconclusive=False,
    cancelled=False,
    timed_out=False,
)


def test_a_clear_ratio_above_the_floor_is_verified() -> None:
    assert _read_benefit_verified(_BASE) is True


def test_a_ratio_exactly_at_the_floor_is_verified() -> None:
    assert _read_benefit_verified(replace(_BASE, ratio=_MIN_VERIFIED_RATIO)) is True


def test_a_ratio_just_below_the_floor_is_not_verified() -> None:
    assert _read_benefit_verified(replace(_BASE, ratio=_MIN_VERIFIED_RATIO - 0.01)) is False


def test_a_ratio_near_one_is_not_verified() -> None:
    """The exact noise regime a true no-op candidate produces."""
    assert _read_benefit_verified(replace(_BASE, ratio=1.02)) is False


def test_an_inconclusive_result_is_never_verified_regardless_of_ratio() -> None:
    assert _read_benefit_verified(replace(_BASE, ratio=10.0, inconclusive=True)) is False


def test_a_missing_ratio_is_never_verified() -> None:
    assert _read_benefit_verified(replace(_BASE, ratio=None)) is False

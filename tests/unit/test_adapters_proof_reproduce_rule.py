"""`adapters.proof.reproduce`'s pure helpers: original-direction recovery and
recorded-plan-fingerprint lookup from the bundle's own evidence convention.
The database-touching `reproduce_bundle` itself is exercised in
`tests/integration/test_adapters_proof_reproduce.py`.
"""

from __future__ import annotations

from pgproof.adapters.proof.reproduce import (
    _median_us,
    _original_direction,
    _recorded_plan_fingerprint,
)


def test_median_us_reads_a_present_arm() -> None:
    assert _median_us({"control-a1": {"median_us": 500.0}}, "control-a1") == 500.0


def test_median_us_is_none_for_a_missing_arm() -> None:
    assert _median_us({}, "control-a1") is None


def test_median_us_is_none_when_the_arm_is_not_a_mapping() -> None:
    assert _median_us({"control-a1": "not a mapping"}, "control-a1") is None


def test_original_direction_is_true_when_the_treatment_was_faster() -> None:
    evidence = {"control-a1": {"median_us": 5000.0}, "treatment-b": {"median_us": 500.0}}
    assert _original_direction(evidence) is True


def test_original_direction_is_false_when_the_treatment_was_not_faster() -> None:
    evidence = {"control-a1": {"median_us": 500.0}, "treatment-b": {"median_us": 5000.0}}
    assert _original_direction(evidence) is False


def test_original_direction_is_none_when_either_arm_is_absent() -> None:
    assert _original_direction({"control-a1": {"median_us": 500.0}}) is None
    assert _original_direction({}) is None


def test_original_direction_is_none_for_a_zero_treatment_median() -> None:
    evidence = {"control-a1": {"median_us": 500.0}, "treatment-b": {"median_us": 0.0}}
    assert _original_direction(evidence) is None


def test_recorded_plan_fingerprint_reads_the_treatment_b_plan() -> None:
    plans = {"treatment-b": {"plan_fingerprint": "sha256:" + "a" * 64}}
    assert _recorded_plan_fingerprint(plans) == "sha256:" + "a" * 64


def test_recorded_plan_fingerprint_is_none_when_absent() -> None:
    assert _recorded_plan_fingerprint({}) is None


def test_recorded_plan_fingerprint_is_none_when_the_field_is_missing() -> None:
    assert _recorded_plan_fingerprint({"treatment-b": {"normalized_shape": "Seq Scan"}}) is None

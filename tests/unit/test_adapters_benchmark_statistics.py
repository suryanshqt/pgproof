"""`adapters.benchmark.statistics` against the exact fixed-index formulas
`scripts/fixture_measurements.py` already validated by hand: median is
`sorted(samples)[3]`, Q1/Q3 are `sorted(samples)[1]`/`sorted(samples)[5]`,
over exactly 7 samples.
"""

from __future__ import annotations

import pytest

from pgproof.adapters.benchmark.statistics import (
    absolute_saving_us,
    arm_statistics,
    drift_fraction,
    ratio,
)


def test_median_is_the_fourth_of_seven_sorted_samples() -> None:
    arm = arm_statistics(
        [1, 2, 3], [700, 100, 200, 300, 400, 500, 600], row_count=5, variance_threshold=0.25
    )
    assert arm.median_us == 400.0
    assert arm.q1_us == 200.0
    assert arm.q3_us == 600.0
    assert arm.min_us == 100.0
    assert arm.max_us == 700.0


def test_iqr_fraction_is_q3_minus_q1_over_median() -> None:
    arm = arm_statistics(
        [], [100, 200, 300, 400, 500, 600, 700], row_count=0, variance_threshold=0.25
    )
    assert arm.iqr_fraction == pytest.approx((600.0 - 200.0) / 400.0)


def test_high_variance_is_flagged_only_past_the_threshold() -> None:
    stable = arm_statistics(
        [], [390, 395, 398, 400, 402, 405, 410], row_count=0, variance_threshold=0.25
    )
    noisy = arm_statistics(
        [], [100, 200, 300, 400, 500, 600, 5000], row_count=0, variance_threshold=0.25
    )
    assert stable.high_variance is False
    assert noisy.high_variance is True


def test_arm_statistics_rejects_a_sample_count_other_than_seven() -> None:
    with pytest.raises(ValueError, match="expects 7 samples"):
        arm_statistics([], [1, 2, 3], row_count=0, variance_threshold=0.25)


def test_warmup_samples_are_retained_verbatim_not_included_in_statistics() -> None:
    arm = arm_statistics(
        [9999, 9999, 9999],
        [100, 200, 300, 400, 500, 600, 700],
        row_count=0,
        variance_threshold=0.25,
    )
    assert arm.warmup_samples_us == (9999, 9999, 9999)
    assert arm.median_us == 400.0


def test_drift_fraction_is_the_relative_change_from_a1_to_a2() -> None:
    assert drift_fraction(median_a1=1000.0, median_a2=1100.0) == pytest.approx(0.1)
    assert drift_fraction(median_a1=1000.0, median_a2=900.0) == pytest.approx(0.1)


def test_saving_and_ratio_compare_a1_to_b() -> None:
    assert absolute_saving_us(median_a1=1000.0, median_b=250.0) == 750.0
    assert ratio(median_a1=1000.0, median_b=250.0) == 4.0

"""Pure statistics over raw benchmark samples. `docs/TECHNICAL_DESIGN.md`
section 20: median, quartiles, IQR, min, max from exactly 7 timed samples.

These are the exact fixed-index formulas `scripts/fixture_measurements.py`
already validated by hand against `fixtures/demo-broken`'s planted index
cases — not a general n-sample quantile method: seven samples do not support
a useful p95, so none of this generalizes past n=7, and nothing here tries to.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

WARMUPS = 3
SAMPLES = 7


@dataclass(frozen=True)
class ArmStatistics:
    """One A1/B/A2 arm's raw samples plus every quantity derived from them."""

    warmup_samples_us: tuple[int, ...]
    samples_us: tuple[int, ...]
    row_count: int
    median_us: float
    min_us: float
    max_us: float
    q1_us: float
    q3_us: float
    iqr_fraction: float
    # `docs/TECHNICAL_DESIGN.md`'s "suppress verdict if IQR/median exceeds
    # configured threshold" — a fact about this arm alone, not the whole
    # experiment, since a noisy A1 and a stable B are two different verdicts.
    high_variance: bool


def arm_statistics(
    warmup_samples_us: Sequence[int],
    samples_us: Sequence[int],
    *,
    row_count: int,
    variance_threshold: float,
) -> ArmStatistics:
    if len(samples_us) != SAMPLES:
        raise ValueError(f"arm_statistics expects {SAMPLES} samples, got {len(samples_us)}")
    ordered = sorted(samples_us)
    median = float(ordered[3])
    q1 = float(ordered[1])
    q3 = float(ordered[5])
    iqr_fraction = (q3 - q1) / median
    return ArmStatistics(
        warmup_samples_us=tuple(warmup_samples_us),
        samples_us=tuple(ordered),
        row_count=row_count,
        median_us=median,
        min_us=float(ordered[0]),
        max_us=float(ordered[-1]),
        q1_us=q1,
        q3_us=q3,
        iqr_fraction=iqr_fraction,
        high_variance=iqr_fraction > variance_threshold,
    )


def drift_fraction(median_a1: float, median_a2: float) -> float:
    return abs(median_a2 - median_a1) / median_a1


def absolute_saving_us(median_a1: float, median_b: float) -> float:
    return median_a1 - median_b


def ratio(median_a1: float, median_b: float) -> float:
    return median_a1 / median_b

"""The A1 control -> B physical treatment -> A2 drift-control protocol,
against a live database. `docs/TECHNICAL_DESIGN.md` section 20.

Direct `psycopg` connection to the disposable database already prepared by
`adapters.seeder`/`adapters.parameters` — no isolated runner container is
involved, the same way those two adapters connect directly: there is no
untrusted code to sandbox here, only SQL this module itself issues.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import Event
from typing import cast

import psycopg
from psycopg import sql

from pgproof.adapters.benchmark.statistics import SAMPLES, WARMUPS, ArmStatistics, arm_statistics
from pgproof.adapters.benchmark.statistics import absolute_saving_us as _absolute_saving_us
from pgproof.adapters.benchmark.statistics import drift_fraction as _drift_fraction
from pgproof.adapters.benchmark.statistics import ratio as _ratio

_EXPLAIN_OPTIONS = "ANALYZE, BUFFERS, WAL, TIMING OFF, FORMAT JSON"
_DEFAULT_VARIANCE_THRESHOLD = 0.25
_DEFAULT_DRIFT_TOLERANCE = 0.10


@dataclass(frozen=True)
class CandidateDDL:
    """The physical treatment under test. Candidate *generation* is a later
    roadmap item's job (`docs/PR_ROADMAP.md` BE-27); this module only ever
    applies and reverts a DDL statement it was handed.
    """

    apply_sql: str
    revert_sql: str


@dataclass(frozen=True)
class ExperimentResult:
    control_a1: ArmStatistics | None
    treatment_b: ArmStatistics | None
    drift_control_a2: ArmStatistics | None
    explain_a1: object
    explain_b: object
    absolute_saving_us: float | None
    ratio: float | None
    drift_fraction: float | None
    high_variance: bool
    drift_detected: bool
    # High variance in any arm, or A1/A2 drift beyond tolerance, or the run
    # never reached all three arms at all (cancelled/timed out) — "never draw
    # a conclusion from a partial or noisy measurement."
    inconclusive: bool
    cancelled: bool
    timed_out: bool


class _StopError(Exception):
    """Cancellation/timeout, raised between phases and caught once at the
    top: every phase after the one in progress must not run at all, not run
    with a `None` result silently threaded through.
    """


def _apply_settings(
    cur: psycopg.Cursor[tuple[object, ...]], settings: Mapping[str, str]
) -> dict[str, str]:
    """Applies every setting, returning what each one held before — autocommit
    means a plain `SET` here is not undone by any transaction rollback, so
    this module restores the exact prior value itself rather than leaking a
    benchmark-only setting onto whatever the caller's connection does next.
    """
    previous: dict[str, str] = {}
    for name, value in settings.items():
        row = cur.execute(sql.SQL("SHOW {}").format(sql.Identifier(name))).fetchone()
        previous[name] = cast("str", row[0]) if row is not None else ""
        cur.execute(sql.SQL("SET {} = {}").format(sql.Identifier(name), sql.Literal(value)))
    return previous


def _restore_settings(cur: psycopg.Cursor[tuple[object, ...]], previous: Mapping[str, str]) -> None:
    for name, value in previous.items():
        cur.execute(sql.SQL("SET {} = {}").format(sql.Identifier(name), sql.Literal(value)))


def _check_stop(cancel_event: Event | None, deadline: float | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise _StopError("cancelled")
    if deadline is not None and time.monotonic() > deadline:
        raise _StopError("timed out")


def _timed_arm(
    cur: psycopg.Cursor[tuple[object, ...]],
    query: str,
    params: Sequence[object] | Mapping[str, object],
    *,
    variance_threshold: float,
) -> ArmStatistics:
    """3 discarded warmups then 7 timed samples, each `execute` plus a full
    `fetchall()` inside the timed region — raw latency includes the fetch,
    matching section 20's "raw latency includes the declared fetch policy."
    `fetch_all` is the only fetch policy this module implements; a caller
    wanting `fetchmany`/streaming has nothing to declare that to yet.
    """
    warmups: list[int] = []
    samples: list[int] = []
    row_count = 0
    for index in range(WARMUPS + SAMPLES):
        start = time.perf_counter()
        cur.execute(query, params)
        fetched = cur.fetchall()
        elapsed = round((time.perf_counter() - start) * 1_000_000)
        (warmups if index < WARMUPS else samples).append(elapsed)
        row_count = len(fetched)
    return arm_statistics(
        warmups, samples, row_count=row_count, variance_threshold=variance_threshold
    )


def _explain(
    cur: psycopg.Cursor[tuple[object, ...]],
    query: str,
    params: Sequence[object] | Mapping[str, object],
) -> object:
    cur.execute(sql.SQL(f"EXPLAIN ({_EXPLAIN_OPTIONS}) {{}}").format(sql.SQL(query)), params)
    row = cur.fetchone()
    return row[0] if row is not None else None


def run_experiment(
    conn: psycopg.Connection[tuple[object, ...]],
    query: str,
    params: Sequence[object] | Mapping[str, object],
    *,
    candidate: CandidateDDL,
    postgres_settings: Mapping[str, str] = {},
    variance_threshold: float = _DEFAULT_VARIANCE_THRESHOLD,
    drift_tolerance: float = _DEFAULT_DRIFT_TOLERANCE,
    cancel_event: Event | None = None,
    timeout_seconds: float | None = None,
) -> ExperimentResult:
    """`query`'s samples under A1 (no candidate), B (candidate applied), and
    A2 (candidate reverted, drift control) — in that order, per section 20.

    Cancellation and timeouts are checked between phases (A1 / apply-DDL / B
    / revert-DDL / A2), not between individual samples: each phase is ten
    fast round-trips, so phase granularity is the coarsest cut that still
    stops promptly without slowing the common, uncancelled case with a
    monotonic-clock read on every one of them.
    """
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    control_a1: ArmStatistics | None = None
    treatment_b: ArmStatistics | None = None
    drift_control_a2: ArmStatistics | None = None
    explain_a1: object = None
    explain_b: object = None
    cancelled = False
    timed_out = False

    # Autocommit, matching `scripts/fixture_measurements.py`'s own validated
    # protocol: each timed statement is its own transaction, the same as a
    # real application's read query, rather than one long-lived transaction
    # the current session's own uncommitted DDL would otherwise hide inside.
    # psycopg refuses to change `autocommit` mid-transaction, so whatever the
    # caller left open is committed first — never silently discarded.
    conn.commit()
    previous_autocommit = conn.autocommit
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            previous_settings = _apply_settings(cur, postgres_settings)
            try:
                _check_stop(cancel_event, deadline)
                control_a1 = _timed_arm(cur, query, params, variance_threshold=variance_threshold)
                explain_a1 = _explain(cur, query, params)

                _check_stop(cancel_event, deadline)
                cur.execute(candidate.apply_sql)

                _check_stop(cancel_event, deadline)
                treatment_b = _timed_arm(cur, query, params, variance_threshold=variance_threshold)
                explain_b = _explain(cur, query, params)

                _check_stop(cancel_event, deadline)
                cur.execute(candidate.revert_sql)

                _check_stop(cancel_event, deadline)
                drift_control_a2 = _timed_arm(
                    cur, query, params, variance_threshold=variance_threshold
                )
            except _StopError as stop:
                cancelled = str(stop) == "cancelled"
                timed_out = str(stop) == "timed out"
            finally:
                _restore_settings(cur, previous_settings)
    finally:
        conn.autocommit = previous_autocommit

    high_variance = any(
        arm is not None and arm.high_variance for arm in (control_a1, treatment_b, drift_control_a2)
    )
    complete = control_a1 is not None and treatment_b is not None and drift_control_a2 is not None
    drift = None
    saving = None
    ratio_value = None
    drift_detected = False
    if complete:
        assert control_a1 is not None
        assert treatment_b is not None
        assert drift_control_a2 is not None
        drift = _drift_fraction(control_a1.median_us, drift_control_a2.median_us)
        saving = _absolute_saving_us(control_a1.median_us, treatment_b.median_us)
        ratio_value = _ratio(control_a1.median_us, treatment_b.median_us)
        drift_detected = drift > drift_tolerance

    return ExperimentResult(
        control_a1=control_a1,
        treatment_b=treatment_b,
        drift_control_a2=drift_control_a2,
        explain_a1=explain_a1,
        explain_b=explain_b,
        absolute_saving_us=saving,
        ratio=ratio_value,
        drift_fraction=drift,
        high_variance=high_variance,
        drift_detected=drift_detected,
        inconclusive=(not complete) or high_variance or drift_detected,
        cancelled=cancelled,
        timed_out=timed_out,
    )

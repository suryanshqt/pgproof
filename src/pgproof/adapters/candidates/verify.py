"""Physical index verification: BE-27's candidate, BE-25's real A1/B/A2 read
benchmark, and this package's own write-cost guard, combined into one
observation per candidate. `docs/PR_ROADMAP.md`'s BE-28 accept criterion:
"emits no universal KEEP without workload policy" — `IndexVerification` has
no keep/drop field at all. `read_benefit_verified` states only the one fact
the read side alone can honestly support: did this candidate measurably and
reliably speed up the target query. Trading that against `write_cost` into a
single keep/drop decision needs a workload policy (how much read traffic
against how much write traffic) this module is never given.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import psycopg

from pgproof.adapters.benchmark.run import CandidateDDL, ExperimentResult, run_experiment
from pgproof.adapters.candidates.generate import IndexCandidate
from pgproof.adapters.candidates.write_cost import WriteCostObservation, measure_write_cost
from pgproof.domain.ir.schema import SchemaIR

# A bare `ratio > 1.0` lets pure measurement noise on a near-identical A1/B
# pair (a marginal or non-existent candidate) read as "verified" about half
# the time — confirmed empirically: a no-op candidate's ratio straddles 1.0
# symmetrically under real scheduling jitter. A minimum improvement floor is
# not stated anywhere in the docs; this default makes "rejects a marginal
# candidate" (`docs/PR_ROADMAP.md`'s own BE-28 accept criterion) hold in
# practice rather than by chance.
_MIN_VERIFIED_RATIO = 1.2


@dataclass(frozen=True)
class IndexVerification:
    candidate: IndexCandidate
    read_benefit: ExperimentResult
    write_cost: WriteCostObservation
    # A read-side-only fact: real speedup, not inconclusive. Never a
    # trade-off verdict against `write_cost` — that needs a workload policy.
    read_benefit_verified: bool


def _read_benefit_verified(result: ExperimentResult) -> bool:
    return (
        not result.inconclusive and result.ratio is not None and result.ratio >= _MIN_VERIFIED_RATIO
    )


def verify_candidate(
    conn: psycopg.Connection[tuple[object, ...]],
    schema: SchemaIR,
    candidate: IndexCandidate,
    query: str,
    params: Sequence[object] | Mapping[str, object],
    *,
    global_seed: int,
    epoch: datetime,
) -> IndexVerification:
    """Read benefit first (candidate not yet applied to the database — BE-25's
    own A1/B/A2 protocol both applies and reverts it), then write cost
    (which repeats that same apply/revert around its own measurements).
    Independent connections to a real disposable database do not interfere
    with each other's before/after data, since each phase is a rolled-back or
    already-reverted transaction by the time the next one starts.
    """
    ddl = CandidateDDL(apply_sql=candidate.apply_sql, revert_sql=candidate.revert_sql)
    read_benefit = run_experiment(conn, query, params, candidate=ddl)
    write_cost = measure_write_cost(conn, schema, candidate, global_seed=global_seed, epoch=epoch)
    return IndexVerification(
        candidate=candidate,
        read_benefit=read_benefit,
        write_cost=write_cost,
        read_benefit_verified=_read_benefit_verified(read_benefit),
    )

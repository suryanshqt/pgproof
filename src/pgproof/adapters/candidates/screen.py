"""Optional HypoPG screening. `docs/TECHNICAL_DESIGN.md` section 21:
"HypoPG may screen plan/cost changes, but screening is not evidence of
improvement... only a physical treatment may become verified."

HypoPG (https://github.com/HypoPG/hypopg) lets the planner cost a query as if
an index existed without building it. `pgproof`'s own isolated runner has no
external network (`docs/ARCHITECTURE.md`), and the base `postgres` image does
not ship the extension, so `screened=False` is the expected, common outcome
in this project's own sandboxed environment, not a fallback for a rare edge
case — every result field name says "estimated_cost", never "measured" or a
time unit, so a screening result can never be mistaken for a BE-25 benchmark.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import psycopg
from psycopg import sql

from pgproof.adapters.benchmark.explain import PlanNode, parse_explain
from pgproof.adapters.candidates.generate import IndexCandidate

_UNAVAILABLE = "hypopg_extension_unavailable"


@dataclass(frozen=True)
class ScreeningResult:
    candidate: IndexCandidate
    screened: bool
    estimated_cost_before: float | None
    estimated_cost_after: float | None
    hypothetical_index_used: bool | None
    skip_reason: str | None


def _skip(candidate: IndexCandidate, reason: str) -> ScreeningResult:
    return ScreeningResult(
        candidate=candidate,
        screened=False,
        estimated_cost_before=None,
        estimated_cost_after=None,
        hypothetical_index_used=None,
        skip_reason=reason,
    )


def _plan_cost(
    cur: psycopg.Cursor[tuple[object, ...]],
    query: str,
    params: Sequence[object] | dict[str, object],
) -> tuple[float | None, bool]:
    """Total cost of the top plan node, and whether any node used a
    HypoPG index — its synthetic name is always wrapped in `<...>`, HypoPG's
    own documented convention for an index that does not physically exist.
    """
    cur.execute(sql.SQL("EXPLAIN (FORMAT JSON) {}").format(sql.SQL(query)), params)
    row = cur.fetchone()
    if row is None:
        return None, False
    diagnostics = parse_explain(row[0])
    used = _uses_hypothetical_index(diagnostics.plan)
    return diagnostics.plan.total_cost, used


def _uses_hypothetical_index(node: PlanNode) -> bool:
    if node.index_name is not None and node.index_name.startswith("<"):
        return True
    return any(_uses_hypothetical_index(child) for child in node.children)


def screen_candidates(
    conn: psycopg.Connection[tuple[object, ...]],
    query: str,
    params: Sequence[object] | dict[str, object],
    candidates: Sequence[IndexCandidate],
) -> tuple[ScreeningResult, ...]:
    if not candidates:
        return ()

    # Autocommit, matching `adapters.benchmark.run`: a failed `CREATE
    # EXTENSION`/`hypopg_create_index` otherwise leaves the transaction
    # aborted, refusing every later statement until an explicit rollback —
    # simpler to never enter that transaction at all.
    conn.commit()
    previous_autocommit = conn.autocommit
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS hypopg")
            except psycopg.Error:
                return tuple(_skip(candidate, _UNAVAILABLE) for candidate in candidates)

            before_cost, _ = _plan_cost(cur, query, params)
            results: list[ScreeningResult] = []
            for candidate in candidates:
                cur.execute("SELECT hypopg_reset()")
                try:
                    cur.execute("SELECT * FROM hypopg_create_index(%s)", (candidate.apply_sql,))
                except psycopg.Error as error:
                    results.append(_skip(candidate, f"unsupported_hypothetical_form:{error}"))
                    continue
                after_cost, used = _plan_cost(cur, query, params)
                results.append(
                    ScreeningResult(
                        candidate=candidate,
                        screened=True,
                        estimated_cost_before=before_cost,
                        estimated_cost_after=after_cost,
                        hypothetical_index_used=used,
                        skip_reason=None,
                    )
                )
            cur.execute("SELECT hypopg_reset()")
    finally:
        conn.autocommit = previous_autocommit
    return tuple(results)

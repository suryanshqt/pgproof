"""Query fingerprint: SHA-256 over the canonical normalized SQL plus resolved
relations and parameter types. `docs/TECHNICAL_DESIGN.md:274-290`, steps 8-9.

Not `pglast.fingerprint()` directly: that function (`libpg_query`'s own,
proven implementation) ignores a cast's target type — `... WHERE id = 1::int`
and `... WHERE id = 1::bigint` fingerprint identically under it — and knows
nothing about relation resolution at all. `docs/ARCHITECTURE.md:228`'s own
identity definition is "fingerprint plus resolved relations and parameter
types," so this hashes the same canonical-JSON convention
`domain.cache.stage_cache_key` already established, over `normalized_sql`
(which does preserve cast text) plus the resolved data `adapters.sql.parser`
supplies.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from pgproof.domain.primitives import Sha256


def fingerprint_query(
    normalized_sql: str, relations: Sequence[str], parameter_types: Sequence[str]
) -> Sha256:
    canonical = json.dumps(
        {
            "normalized_sql": normalized_sql,
            "relations": sorted(relations),
            # Positional, not sorted: parameter order is part of a query's
            # identity (`f(int, text)` differs from `f(text, int)`).
            "parameter_types": list(parameter_types),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"

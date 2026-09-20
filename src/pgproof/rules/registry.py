"""The versioned rule registry: a hand-written tuple, not auto-discovery.

`docs/ARCHITECTURE.md` section 16 gates exposing a plugin API behind an ADR;
`pgproof.domain.registry`'s own `ARTIFACT_MODELS` is written out the same way,
"so each type resolves statically" rather than through decorator magic.
"""

from __future__ import annotations

from pgproof.rules import schema, tenancy, workload
from pgproof.rules.base import Rule

RULES: tuple[Rule, ...] = (
    Rule(id=schema.RULE_ID, version=1, evaluate=schema.orm_relationship_without_physical_fk),
    Rule(id=workload.RULE_ID, version=1, evaluate=workload.unindexed_foreign_key),
    Rule(id=tenancy.RULE_ID, version=1, evaluate=tenancy.confirm_isolation_model),
)

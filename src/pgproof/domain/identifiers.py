"""Stable identifiers.

`docs/ARCHITECTURE.md` section 6 fixes what each identity is made of and states
that database OIDs, absolute paths, transient container ids and wall-clock time
MUST NOT define a stable identity. That rule is enforced structurally: each type
below only accepts the shape its identity is defined as, so an OID or a container
hash cannot be parsed as a table or column identity at all.
"""

from __future__ import annotations

import re
from typing import Annotated, Final

from pydantic import AfterValidator, StringConstraints

from pgproof.domain.primitives import SHA256_PATTERN

# PostgreSQL identifiers are at most 63 bytes. Digits-only is rejected so a bare
# OID can never be mistaken for a logical name.
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")
_ALL_DIGITS = re.compile(r"^[0-9]+$")

RULE_ID_PATTERN: Final = r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
MIGRATION_ID_PATTERN: Final = r"^[0-9a-z][0-9a-z_]{0,63}$"
RECOMMENDATION_ID_PATTERN: Final = r"^[A-Z][A-Z0-9]{1,15}-[0-9]{3,6}$"
QUESTION_ID_PATTERN: Final = r"^[a-z][a-z0-9_]*$"
OPERATION_ID_PATTERN: Final = r"^[a-z][a-z0-9_]*::[^\s\x00]{1,300}$"
PROOF_ID_PATTERN: Final = r"^[A-Z][A-Z0-9]{1,15}-[0-9]{3,6}@sha256:[0-9a-f]{64}$"
NODE_ID_PATTERN: Final = r"^[a-z][a-z0-9_]*:[^\s\x00]{1,300}$"


def _validate_dotted_name(value: str, segments: int, label: str) -> str:
    parts = value.split(".")
    if len(parts) != segments:
        raise ValueError(f"{label} must have {segments} dot-separated segments, got {value!r}")
    for part in parts:
        if not _NAME.match(part):
            raise ValueError(f"{label} segment {part!r} is not a PostgreSQL identifier")
        if _ALL_DIGITS.match(part):
            raise ValueError(
                f"{label} segment {part!r} is numeric; an OID cannot be a logical name"
            )
    return value


def _validate_table_id(value: str) -> str:
    return _validate_dotted_name(value, 2, "table id")


def _validate_column_id(value: str) -> str:
    return _validate_dotted_name(value, 3, "column id")


TableId = Annotated[str, AfterValidator(_validate_table_id)]
ColumnId = Annotated[str, AfterValidator(_validate_column_id)]
MigrationId = Annotated[str, StringConstraints(pattern=MIGRATION_ID_PATTERN)]
QueryId = Annotated[str, StringConstraints(pattern=SHA256_PATTERN)]
OperationId = Annotated[str, StringConstraints(pattern=OPERATION_ID_PATTERN)]
RuleId = Annotated[str, StringConstraints(pattern=RULE_ID_PATTERN)]
RecommendationId = Annotated[str, StringConstraints(pattern=RECOMMENDATION_ID_PATTERN)]
QuestionId = Annotated[str, StringConstraints(pattern=QUESTION_ID_PATTERN)]
ExperimentId = Annotated[str, StringConstraints(pattern=PROOF_ID_PATTERN)]
ProofId = Annotated[str, StringConstraints(pattern=PROOF_ID_PATTERN)]
NodeId = Annotated[str, StringConstraints(pattern=NODE_ID_PATTERN)]


def table_id(schema: str, table: str) -> str:
    return _validate_table_id(f"{schema}.{table}")


def column_id(table: str, column: str) -> str:
    return _validate_column_id(f"{table}.{column}")


def node_id(kind: str, key: str) -> str:
    """Graph node identity: node kind plus the domain identity it represents."""
    value = f"{kind}:{key}"
    if not re.match(NODE_ID_PATTERN, value):
        raise ValueError(f"not a node id: {value!r}")
    return value


def proof_id(recommendation: str, input_manifest_hash: str) -> str:
    """Proof identity is the recommendation plus its input-manifest hash.

    Container ids and wall-clock time are excluded by construction: only the
    recommendation and a content hash of the declared inputs take part.
    """
    value = f"{recommendation}@{input_manifest_hash}"
    if not re.match(PROOF_ID_PATTERN, value):
        raise ValueError(f"not a proof id: {value!r}")
    return value


def canonical_recommendation_identity(rule: str, affected_objects: tuple[str, ...]) -> str:
    """Rule id plus canonically ordered affected-object ids.

    `docs/TECHNICAL_DESIGN.md` section 13 requires recommendation identity to
    survive a wording change while tracking the rule and its affected objects, so
    only those two inputs take part and the objects are order-normalised.
    """
    if not re.match(RULE_ID_PATTERN, rule):
        raise ValueError(f"not a rule id: {rule!r}")
    if not affected_objects:
        raise ValueError("a recommendation must affect at least one object")
    return f"{rule}({','.join(sorted(set(affected_objects)))})"

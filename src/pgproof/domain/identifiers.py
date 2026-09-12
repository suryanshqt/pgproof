"""Stable identifiers.

`docs/ARCHITECTURE.md` section 6 fixes what each identity is made of: a table is
a schema-qualified logical name, a column is a table identity plus a column name,
and database OIDs MUST NOT define a stable identity.

## Why a codec rather than dot splitting

PostgreSQL logical names are arbitrary text once quoted. `"a.b"`, `"My Table"`,
`"2024"`, `"Ördér"` and `say"hi` are all legal names, so joining parts with a
bare `.` and splitting on `.` is ambiguous: `public` + `a.b` and `public.a` + `b`
would both produce `public.a.b`.

Identities are therefore encoded with a minimal, reversible escape: `\\` becomes
`\\\\` and `.` becomes `\\.`, then parts are joined with `.`. The common case is
unchanged (`public.orders`), every legal name round-trips, and two different part
tuples can never encode to the same string.

## How OIDs are excluded

Not by rejecting numeric-looking names: `"2024"` is a perfectly legal table name,
and refusing it confused "this name happens to be numeric" with "this identity
came from an OID". Instead, identity is *constructed from logical names* and no
contract model has an OID field at all, which a test asserts.
"""

from __future__ import annotations

import re
from typing import Annotated, Final

from pydantic import AfterValidator, StringConstraints
from pydantic.json_schema import WithJsonSchema

from pgproof.domain.primitives import SHA256_PATTERN

SEPARATOR: Final = "."
ESCAPE: Final = "\\"
_ESCAPABLE: Final = frozenset({SEPARATOR, ESCAPE})

# One encoded part: any character that is not the separator, the escape or NUL,
# or an escape followed by the separator or the escape. A dangling or unknown
# escape cannot match, so the pattern and the decoder reject the same inputs.
_PART: Final = r"(?:[^.\\\x00]|\\[.\\])+"
TABLE_ID_PATTERN: Final = rf"^{_PART}\.{_PART}$"
COLUMN_ID_PATTERN: Final = rf"^{_PART}\.{_PART}\.{_PART}$"
NODE_ID_PATTERN: Final = r"^[a-z][a-z0-9_]*:[^\x00]{1,512}$"

RULE_ID_PATTERN: Final = r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
MIGRATION_ID_PATTERN: Final = r"^[0-9a-z][0-9a-z_]{0,63}$"
RECOMMENDATION_ID_PATTERN: Final = r"^[A-Z][A-Z0-9]{1,15}-[0-9]{3,6}$"
QUESTION_ID_PATTERN: Final = r"^[a-z][a-z0-9_]*$"
OPERATION_ID_PATTERN: Final = r"^[a-z][a-z0-9_]*::[^\x00]{1,300}$"
PROOF_ID_PATTERN: Final = r"^[A-Z][A-Z0-9]{1,15}-[0-9]{3,6}@sha256:[0-9a-f]{64}$"


def encode_identity(*names: str) -> str:
    """Join logical names into one reversible identity string."""
    if not names:
        raise ValueError("an identity needs at least one logical name")
    return SEPARATOR.join(_encode_part(name) for name in names)


def _encode_part(name: str) -> str:
    if not name:
        raise ValueError("a logical name must not be empty")
    if "\x00" in name:
        raise ValueError("a logical name must not contain NUL")
    return name.replace(ESCAPE, ESCAPE + ESCAPE).replace(SEPARATOR, ESCAPE + SEPARATOR)


def decode_identity(value: str) -> tuple[str, ...]:
    """Recover the logical names from an encoded identity.

    Inverse of `encode_identity` for every input that encoder accepts.
    """
    parts: list[str] = []
    current: list[str] = []
    index = 0
    length = len(value)
    while index < length:
        character = value[index]
        if character == "\x00":
            raise ValueError("an identity must not contain NUL")
        if character == ESCAPE:
            index += 1
            if index >= length:
                raise ValueError(f"identity ends with a dangling escape: {value!r}")
            following = value[index]
            if following not in _ESCAPABLE:
                raise ValueError(f"invalid escape {ESCAPE + following!r} in identity {value!r}")
            current.append(following)
        elif character == SEPARATOR:
            parts.append("".join(current))
            current = []
        else:
            current.append(character)
        index += 1
    parts.append("".join(current))
    if any(part == "" for part in parts):
        raise ValueError(f"identity contains an empty logical name: {value!r}")
    return tuple(parts)


def _validate_parts(value: str, expected: int, label: str) -> str:
    parts = decode_identity(value)
    if len(parts) != expected:
        raise ValueError(
            f"{label} must decode to {expected} logical names, got {len(parts)} from {value!r}"
        )
    return value


def _validate_table_id(value: str) -> str:
    return _validate_parts(value, 2, "table id")


def _validate_column_id(value: str) -> str:
    return _validate_parts(value, 3, "column id")


TableId = Annotated[
    str,
    AfterValidator(_validate_table_id),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": TABLE_ID_PATTERN,
            "description": (
                "Schema-qualified table identity: two logical names joined by '.', "
                "with '.' and '\\' escaped by '\\'."
            ),
        }
    ),
]
ColumnId = Annotated[
    str,
    AfterValidator(_validate_column_id),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": COLUMN_ID_PATTERN,
            "description": (
                "Column identity: schema, table and column logical names joined by "
                "'.', with '.' and '\\' escaped by '\\'."
            ),
        }
    ),
]
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
    """Table identity from logical names, never from a catalog OID."""
    return _validate_table_id(encode_identity(schema, table))


def column_id(table: str, column: str) -> str:
    """Column identity: an existing table identity plus a logical column name."""
    schema_name, table_name = decode_identity(table)
    return _validate_column_id(encode_identity(schema_name, table_name, column))


def table_names(value: str) -> tuple[str, str]:
    schema_name, table_name = decode_identity(value)
    return schema_name, table_name


def column_names(value: str) -> tuple[str, str, str]:
    schema_name, table_name, column_name = decode_identity(value)
    return schema_name, table_name, column_name


def node_id(kind: str, key: str) -> str:
    """Graph node identity: node kind plus the domain identity it represents."""
    if not key:
        raise ValueError("a node id needs a non-empty key")
    value = f"{kind}:{key}"
    if not re.match(NODE_ID_PATTERN, value):
        raise ValueError(f"not a node id: {value!r}")
    return value


def node_parts(value: str) -> tuple[str, str]:
    """Split a node id on its first colon, so the key may itself contain colons."""
    kind, separator, key = value.partition(":")
    if not separator or not key:
        raise ValueError(f"not a node id: {value!r}")
    return kind, key


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

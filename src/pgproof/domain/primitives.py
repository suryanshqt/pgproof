"""Validated scalar types shared by every contract model.

The rules encoded here come from `docs/TECHNICAL_DESIGN.md` section 4: RFC 3339
UTC timestamps, `sha256:`-prefixed hashes, repository-relative POSIX paths,
exact decimals as strings, durations as integer microseconds, and lowercase
snake-case enum values.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Final

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints
from pydantic.json_schema import WithJsonSchema

SHA256_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"
SCHEMA_VERSION_PATTERN: Final = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
TOOL_VERSION_PATTERN: Final = r"^[0-9]+\.[0-9]+\.[0-9]+(?:[.\-+][0-9A-Za-z.\-+]+)?$"
# Crockford base32 without I, L, O or U, the ULID alphabet.
RUN_ID_PATTERN: Final = r"^[0-9A-HJKMNP-TV-Z]{26}$"
DECIMAL_PATTERN: Final = r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$"
SNAKE_CASE_PATTERN: Final = r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$"
# Rejects absolute, drive-qualified, home-relative, traversing, empty-segment and
# trailing-separator paths. Carried into the generated JSON Schema so an
# independent validator enforces the same rule the Python validator does.
REPOSITORY_PATH_PATTERN: Final = (
    r"^(?!.*//)(?!.*(?:^|/)\.\.?(?:/|$))(?![A-Za-z]:)[^/\\\x00~][^\\\x00]*(?<!/)$"
)
RFC3339_UTC_PATTERN: Final = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$"

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_RFC3339_UTC = re.compile(RFC3339_UTC_PATTERN)
_DECIMAL = re.compile(DECIMAL_PATTERN)


def _validate_repository_path(value: str) -> str:
    """Repository-relative POSIX path. Absolute and traversing paths are rejected."""
    if not value:
        raise ValueError("path must not be empty")
    if "\x00" in value:
        raise ValueError("path must not contain a NUL byte")
    if "\\" in value:
        raise ValueError(f"path must use POSIX separators, got {value!r}")
    if value.startswith("/"):
        raise ValueError(f"path must be repository-relative, got absolute {value!r}")
    if _WINDOWS_DRIVE.match(value):
        raise ValueError(f"path must be repository-relative, got drive-qualified {value!r}")
    if value.startswith("~"):
        raise ValueError(f"path must not be home-relative, got {value!r}")
    if value.endswith("/"):
        raise ValueError(f"path must not end with a separator, got {value!r}")
    if "//" in value:
        raise ValueError(f"path must not contain an empty segment, got {value!r}")
    segments = value.split("/")
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError(f"path must not contain '.' or '..', got {value!r}")
    return value


def _validate_rfc3339_utc(value: str) -> str:
    """RFC 3339 timestamp that is explicitly UTC. Offsets other than Z are rejected."""
    if not _RFC3339_UTC.match(value):
        raise ValueError(f"timestamp must be RFC 3339 UTC ending in 'Z', got {value!r}")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"timestamp is not a valid RFC 3339 instant: {value!r}") from error
    if parsed.tzinfo != dt.UTC:
        raise ValueError(f"timestamp must be UTC, got {value!r}")
    return value


def _validate_decimal_string(value: str) -> str:
    """Exact decimal carried as a string, so no float rounding can occur in transit.

    The pattern is checked as well as the parse, so the Python validator and the
    generated JSON Schema reject the same inputs. `Decimal` alone would accept
    `1.0e5`, `NaN`, `Infinity` and `01`, none of which is an exact canonical form.
    """
    if not _DECIMAL.match(value):
        raise ValueError(
            f"not an exact decimal in canonical form: {value!r}; "
            f"expected a value matching {DECIMAL_PATTERN}"
        )
    try:
        Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"not an exact decimal: {value!r}") from error
    return value


RepositoryPath = Annotated[
    str,
    AfterValidator(_validate_repository_path),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": REPOSITORY_PATH_PATTERN,
            "description": "Repository-relative POSIX path.",
        }
    ),
]
Sha256 = Annotated[str, StringConstraints(pattern=SHA256_PATTERN)]
Rfc3339Utc = Annotated[
    str,
    AfterValidator(_validate_rfc3339_utc),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": RFC3339_UTC_PATTERN,
            "description": "RFC 3339 timestamp in UTC, ending in 'Z'.",
        }
    ),
]
SchemaVersionString = Annotated[str, StringConstraints(pattern=SCHEMA_VERSION_PATTERN)]
ToolVersionString = Annotated[str, StringConstraints(pattern=TOOL_VERSION_PATTERN)]
RunId = Annotated[str, StringConstraints(pattern=RUN_ID_PATTERN)]
DecimalString = Annotated[
    str,
    AfterValidator(_validate_decimal_string),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": DECIMAL_PATTERN,
            "description": "Exact decimal carried as a string.",
        }
    ),
]
Microseconds = Annotated[int, Field(ge=0)]
LineNumber = Annotated[int, Field(ge=1)]
NonEmptyText = Annotated[str, StringConstraints(min_length=1, strip_whitespace=False)]


class SnakeCaseEnum(StrEnum):
    """Base for stable enums. Values are lowercase snake case, asserted by test."""


class Contract(BaseModel):
    """Base for every contract model.

    `frozen` keeps domain values immutable, which is what lets an identity be
    trusted once constructed. `extra="ignore"` implements the forward-compatibility
    rule in `docs/ARCHITECTURE.md` section 7: a reader tolerates additive fields
    within the same major version rather than rejecting the document.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        populate_by_name=False,
        validate_default=True,
        ser_json_inf_nan="strings",
    )

    def canonical_dict(self) -> dict[str, Any]:
        return dict(self.model_dump(mode="json", by_alias=False))

    def canonical_json(self) -> str:
        """Byte-stable JSON: sorted keys, no insignificant whitespace, UTF-8 kept."""
        return json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

"""Contract version compatibility.

The policy is fixed by `docs/ARCHITECTURE.md` section 7 ("readers reject
unsupported major versions and tolerate additive compatible fields") and
`docs/TECHNICAL_DESIGN.md` section 4 ("additive minor schema changes allowed;
breaking changes increment major"). ADR 0001 records it.

Tool version and schema version are independent: the tool may release many
versions without moving the contract, and the contract may move without a tool
release.
"""

from __future__ import annotations

import re
from typing import Final, NamedTuple

CONTRACT_SCHEMA_VERSION: Final = "1.3"
SUPPORTED_MAJOR: Final = 1

_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class SchemaVersion(NamedTuple):
    major: int
    minor: int

    @property
    def text(self) -> str:
        return f"{self.major}.{self.minor}"


def parse_schema_version(value: str) -> SchemaVersion:
    match = _VERSION.match(value)
    if match is None:
        raise ValueError(f"not a schema version: {value!r}")
    return SchemaVersion(int(match.group(1)), int(match.group(2)))


class IncompatibleSchemaVersionError(ValueError):
    """Raised when a document's major version is not supported by this reader."""


def require_supported(value: str) -> SchemaVersion:
    """Reject an unsupported major; accept any minor within the supported major.

    A newer minor is accepted because minors are additive by policy, and unknown
    additive fields are ignored rather than rejected.
    """
    version = parse_schema_version(value)
    if version.major != SUPPORTED_MAJOR:
        raise IncompatibleSchemaVersionError(
            f"artifact schema major {version.major} is not supported; "
            f"this build reads major {SUPPORTED_MAJOR} "
            f"(document version {value}, reader version {CONTRACT_SCHEMA_VERSION})"
        )
    return version


def is_compatible(value: str) -> bool:
    try:
        require_supported(value)
    except (IncompatibleSchemaVersionError, ValueError):
        return False
    return True

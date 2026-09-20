"""The run manifest: the hash and compatibility record for one run's output.

Distinct from `StageSet` (`stages.py`): a stage set describes stage *outcomes*;
a manifest is the durable proof of *which artifact bytes* a run produced, so a
later reader can detect drift or corruption independent of re-running anything.
`docs/ARCHITECTURE.md` section 7: "A manifest is written last; its presence
marks a complete stage." Reading and writing it is `pgproof.store`.

Not part of the generated JSON Schema / TypeScript contract set for the same
reason as `events.py`: it is a backend-internal record today.
"""

from __future__ import annotations

from typing import Self

from pydantic import field_validator, model_validator

from pgproof.domain.envelope import ArtifactType
from pgproof.domain.primitives import (
    Contract,
    NonEmptyText,
    Rfc3339Utc,
    RunId,
    SchemaVersionString,
    Sha256,
    ToolVersionString,
)
from pgproof.domain.versioning import CONTRACT_SCHEMA_VERSION, require_supported


class ManifestEntry(Contract):
    """One artifact this run wrote, identified by its path under `.pgproof`."""

    artifact_type: ArtifactType
    path: NonEmptyText
    content_hash: Sha256
    schema_version: SchemaVersionString


class RunManifest(Contract):
    """The complete, hash-verifiable record of what one run wrote."""

    run_id: RunId
    tool_version: ToolVersionString
    created_at: Rfc3339Utc
    schema_version: SchemaVersionString = CONTRACT_SCHEMA_VERSION
    entries: tuple[ManifestEntry, ...] = ()

    @field_validator("schema_version")
    @classmethod
    def _reject_unsupported_major(cls, value: str) -> str:
        require_supported(value)
        return value

    @model_validator(mode="after")
    def _validate_unique_paths(self) -> Self:
        paths = [entry.path for entry in self.entries]
        if len(set(paths)) != len(paths):
            raise ValueError("manifest entries must have unique paths")
        return self

"""Transport envelope.

The shape is fixed by `docs/TECHNICAL_DESIGN.md` section 4. `artifact_type`
discriminates the `data` payload, and `inputs` carries the content hashes the
document was derived from so a stale artifact is detectable.

Nothing here touches a filesystem. Reading and writing `.pgproof` is BE-04.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import Field, field_validator

from pgproof.domain.primitives import (
    Contract,
    Rfc3339Utc,
    RunId,
    SchemaVersionString,
    Sha256,
    SnakeCaseEnum,
    ToolVersionString,
)
from pgproof.domain.versioning import CONTRACT_SCHEMA_VERSION, require_supported


class ArtifactType(SnakeCaseEnum):
    """Every top-level artifact this contract version defines."""

    SCHEMA = "schema"
    CODE = "code"
    WORKLOAD = "workload"
    CONTEXT = "context"
    EVIDENCE = "evidence"
    RECOMMENDATIONS = "recommendations"
    SCENARIOS = "scenarios"
    GRAPH = "graph"
    STAGES = "stages"
    PROOFS = "proofs"


DataT = TypeVar("DataT", bound=Contract)


class Envelope(Contract, Generic[DataT]):
    """A versioned top-level artifact."""

    schema_version: SchemaVersionString = CONTRACT_SCHEMA_VERSION
    tool_version: ToolVersionString
    artifact_type: ArtifactType
    created_at: Rfc3339Utc
    run_id: RunId
    inputs: dict[str, Sha256] = Field(default_factory=dict)
    data: DataT

    @field_validator("schema_version")
    @classmethod
    def _reject_unsupported_major(cls, value: str) -> str:
        require_supported(value)
        return value

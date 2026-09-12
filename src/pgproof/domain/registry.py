"""Typed artifact registry.

Maps each `ArtifactType` to the model its `data` payload must satisfy, so a
consumer can resolve a document without a hand-written dispatch table.

Parsing here operates on already-decoded Python objects. Loading bytes from disk
is BE-04.
"""

from __future__ import annotations

from typing import Any, Final

from pgproof.domain.envelope import ArtifactType, Envelope
from pgproof.domain.evidence import EvidenceGraph
from pgproof.domain.experiments import ProofSummarySet
from pgproof.domain.graph import GraphIR
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.context import ContextIR
from pgproof.domain.ir.schema import SchemaIR
from pgproof.domain.ir.workload import WorkloadIR
from pgproof.domain.primitives import Contract
from pgproof.domain.recommendations import RecommendationSet
from pgproof.domain.scenarios import ScenarioSet
from pgproof.domain.stages import StageSet
from pgproof.domain.versioning import require_supported

ARTIFACT_MODELS: Final[dict[ArtifactType, type[Contract]]] = {
    ArtifactType.SCHEMA: SchemaIR,
    ArtifactType.CODE: CodeIR,
    ArtifactType.WORKLOAD: WorkloadIR,
    ArtifactType.CONTEXT: ContextIR,
    ArtifactType.EVIDENCE: EvidenceGraph,
    ArtifactType.RECOMMENDATIONS: RecommendationSet,
    ArtifactType.SCENARIOS: ScenarioSet,
    ArtifactType.GRAPH: GraphIR,
    ArtifactType.STAGES: StageSet,
    ArtifactType.PROOFS: ProofSummarySet,
}

# Parametrised eagerly rather than subscripted at call time, so every concrete
# envelope type resolves statically. A test asserts this agrees with
# ARTIFACT_MODELS, which is what stops the two tables drifting apart.
ENVELOPE_MODELS: Final[dict[ArtifactType, type[Envelope[Any]]]] = {
    ArtifactType.SCHEMA: Envelope[SchemaIR],
    ArtifactType.CODE: Envelope[CodeIR],
    ArtifactType.WORKLOAD: Envelope[WorkloadIR],
    ArtifactType.CONTEXT: Envelope[ContextIR],
    ArtifactType.EVIDENCE: Envelope[EvidenceGraph],
    ArtifactType.RECOMMENDATIONS: Envelope[RecommendationSet],
    ArtifactType.SCENARIOS: Envelope[ScenarioSet],
    ArtifactType.GRAPH: Envelope[GraphIR],
    ArtifactType.STAGES: Envelope[StageSet],
    ArtifactType.PROOFS: Envelope[ProofSummarySet],
}

# The registry is the single source of truth for what a top-level artifact is,
# so a new artifact type cannot be added without a model and a generated schema.
ARTIFACT_FILENAMES: Final[dict[ArtifactType, str]] = {
    artifact_type: f"{artifact_type.value}.schema.json" for artifact_type in ARTIFACT_MODELS
}


def data_model_for(artifact_type: ArtifactType) -> type[Contract]:
    return ARTIFACT_MODELS[artifact_type]


def envelope_model_for(artifact_type: ArtifactType) -> type[Envelope[Any]]:
    """Concrete envelope type for one artifact, with `data` narrowed."""
    return ENVELOPE_MODELS[artifact_type]


def parse_artifact(document: dict[str, Any]) -> Envelope[Any]:
    """Validate a decoded document against the model its own `artifact_type` names.

    Raises `IncompatibleSchemaVersionError` for an unsupported major before any
    payload validation, so a future-major document fails with a version error
    rather than a confusing field error.
    """
    version = document.get("schema_version")
    if isinstance(version, str):
        require_supported(version)
    raw_type = document.get("artifact_type")
    known = ", ".join(sorted(item.value for item in ArtifactType))
    if not isinstance(raw_type, str):
        raise ValueError(f"artifact_type must be a string; expected one of: {known}")
    try:
        artifact_type = ArtifactType(raw_type)
    except ValueError as error:
        raise ValueError(f"unknown artifact_type {raw_type!r}; expected one of: {known}") from error
    envelope: Envelope[Any] = envelope_model_for(artifact_type).model_validate(document)
    return envelope

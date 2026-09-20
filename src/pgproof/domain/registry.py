"""Typed artifact registry.

Maps each `ArtifactType` to the model its `data` payload must satisfy, so a
consumer can resolve a document without a hand-written dispatch table.

Parsing here operates on already-decoded Python objects. Loading bytes from
disk is `pgproof.store`.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from pgproof.domain.envelope import ArtifactType, Envelope
from pgproof.domain.evidence import EvidenceGraph
from pgproof.domain.experiments import ProofSummarySet
from pgproof.domain.graph import GraphIR
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.context import ContextIR
from pgproof.domain.ir.schema import SchemaIR
from pgproof.domain.ir.workload import WorkloadIR
from pgproof.domain.migration_plan import MigrationPlan
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
    ArtifactType.MIGRATION_PLAN: MigrationPlan,
}


# One concrete envelope per artifact kind, each narrowing `artifact_type` to a
# single literal. That makes every generated schema strictly discriminated: a
# `code` document cannot validate against the `schema` contract, in Python or in
# an independent validator. Written out rather than built dynamically so each
# type resolves statically; a test asserts this agrees with ARTIFACT_MODELS.
class SchemaEnvelope(Envelope[SchemaIR]):
    artifact_type: Literal[ArtifactType.SCHEMA]


class CodeEnvelope(Envelope[CodeIR]):
    artifact_type: Literal[ArtifactType.CODE]


class WorkloadEnvelope(Envelope[WorkloadIR]):
    artifact_type: Literal[ArtifactType.WORKLOAD]


class ContextEnvelope(Envelope[ContextIR]):
    artifact_type: Literal[ArtifactType.CONTEXT]


class EvidenceEnvelope(Envelope[EvidenceGraph]):
    artifact_type: Literal[ArtifactType.EVIDENCE]


class RecommendationsEnvelope(Envelope[RecommendationSet]):
    artifact_type: Literal[ArtifactType.RECOMMENDATIONS]


class ScenariosEnvelope(Envelope[ScenarioSet]):
    artifact_type: Literal[ArtifactType.SCENARIOS]


class GraphEnvelope(Envelope[GraphIR]):
    artifact_type: Literal[ArtifactType.GRAPH]


class StagesEnvelope(Envelope[StageSet]):
    artifact_type: Literal[ArtifactType.STAGES]


class ProofsEnvelope(Envelope[ProofSummarySet]):
    artifact_type: Literal[ArtifactType.PROOFS]


class MigrationPlanEnvelope(Envelope[MigrationPlan]):
    artifact_type: Literal[ArtifactType.MIGRATION_PLAN]


ENVELOPE_MODELS: Final[dict[ArtifactType, type[Envelope[Any]]]] = {
    ArtifactType.SCHEMA: SchemaEnvelope,
    ArtifactType.CODE: CodeEnvelope,
    ArtifactType.WORKLOAD: WorkloadEnvelope,
    ArtifactType.CONTEXT: ContextEnvelope,
    ArtifactType.EVIDENCE: EvidenceEnvelope,
    ArtifactType.RECOMMENDATIONS: RecommendationsEnvelope,
    ArtifactType.SCENARIOS: ScenariosEnvelope,
    ArtifactType.GRAPH: GraphEnvelope,
    ArtifactType.STAGES: StagesEnvelope,
    ArtifactType.PROOFS: ProofsEnvelope,
    ArtifactType.MIGRATION_PLAN: MigrationPlanEnvelope,
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

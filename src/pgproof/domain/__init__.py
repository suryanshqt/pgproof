"""pgproof domain contracts.

Frozen transport and identity models shared by the CLI, the loopback API and the
generated TypeScript types. This package performs no I/O and depends on no
adapter, per the dependency rule in `docs/ARCHITECTURE.md` section 4.
"""

from pgproof.domain.envelope import ArtifactType, Envelope
from pgproof.domain.evidence import EvidenceGraph, EvidenceKind, EvidenceRef
from pgproof.domain.experiments import (
    ArmMeasurement,
    ExperimentArm,
    ProofSummary,
    ProofSummarySet,
    ProofVerdict,
    TreatmentKind,
)
from pgproof.domain.graph import (
    EdgeKind,
    GraphEdge,
    GraphIR,
    GraphNode,
    GraphStatus,
    NodeKind,
)
from pgproof.domain.ir.code import CodeIR, ModelIR, RelationshipIR
from pgproof.domain.ir.context import ContextAnswer, ContextIR, TenantModel
from pgproof.domain.ir.schema import ColumnIR, ConstraintIR, IndexIR, SchemaIR, TableIR
from pgproof.domain.ir.workload import OperationIR, QueryIR, WorkloadIR
from pgproof.domain.primitives import Contract, SnakeCaseEnum
from pgproof.domain.questions import AnswerSchema, MaterialQuestion
from pgproof.domain.recommendations import (
    Recommendation,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationSet,
    VerificationState,
)
from pgproof.domain.registry import (
    ARTIFACT_FILENAMES,
    ARTIFACT_MODELS,
    ENVELOPE_MODELS,
    data_model_for,
    envelope_model_for,
    parse_artifact,
)
from pgproof.domain.scenarios import Scenario, ScenarioDiff, ScenarioKind, ScenarioSet
from pgproof.domain.sources import MigrationRef, SourceRef
from pgproof.domain.stages import StageName, StageSet, StageStatus, StageSummary
from pgproof.domain.versioning import (
    CONTRACT_SCHEMA_VERSION,
    SUPPORTED_MAJOR,
    IncompatibleSchemaVersionError,
    is_compatible,
    require_supported,
)

__all__ = [
    "ARTIFACT_FILENAMES",
    "ARTIFACT_MODELS",
    "CONTRACT_SCHEMA_VERSION",
    "ENVELOPE_MODELS",
    "SUPPORTED_MAJOR",
    "AnswerSchema",
    "ArmMeasurement",
    "ArtifactType",
    "CodeIR",
    "ColumnIR",
    "ConstraintIR",
    "ContextAnswer",
    "ContextIR",
    "Contract",
    "EdgeKind",
    "Envelope",
    "EvidenceGraph",
    "EvidenceKind",
    "EvidenceRef",
    "ExperimentArm",
    "GraphEdge",
    "GraphIR",
    "GraphNode",
    "GraphStatus",
    "IncompatibleSchemaVersionError",
    "IndexIR",
    "MaterialQuestion",
    "MigrationRef",
    "ModelIR",
    "NodeKind",
    "OperationIR",
    "ProofSummary",
    "ProofSummarySet",
    "ProofVerdict",
    "QueryIR",
    "Recommendation",
    "RecommendationCategory",
    "RecommendationPriority",
    "RecommendationSet",
    "RelationshipIR",
    "Scenario",
    "ScenarioDiff",
    "ScenarioKind",
    "ScenarioSet",
    "SchemaIR",
    "SnakeCaseEnum",
    "SourceRef",
    "StageName",
    "StageSet",
    "StageStatus",
    "StageSummary",
    "TableIR",
    "TenantModel",
    "TreatmentKind",
    "VerificationState",
    "WorkloadIR",
    "data_model_for",
    "envelope_model_for",
    "is_compatible",
    "parse_artifact",
    "require_supported",
]

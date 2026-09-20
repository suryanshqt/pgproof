"""pgproof domain contracts.

Frozen transport and identity models shared by the CLI, the loopback API and the
generated TypeScript types. This package performs no I/O and depends on no
adapter, per the dependency rule in `docs/ARCHITECTURE.md` section 4.
"""

from pgproof.domain.cache import stage_cache_key
from pgproof.domain.envelope import ArtifactType, Envelope
from pgproof.domain.events import StageEvent, StageEventKind
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
from pgproof.domain.identifiers import (
    column_id,
    column_names,
    decode_identity,
    encode_identity,
    node_id,
    node_parts,
    proof_id,
    table_id,
    table_names,
)
from pgproof.domain.ir.code import CodeIR, ModelIR, RelationshipIR
from pgproof.domain.ir.context import ContextAnswer, ContextIR, TenantModel
from pgproof.domain.ir.schema import ColumnIR, ConstraintIR, IndexIR, SchemaIR, TableIR
from pgproof.domain.ir.workload import OperationIR, QueryIR, WorkloadIR
from pgproof.domain.manifest import ManifestEntry, RunManifest
from pgproof.domain.migration_plan import MigrationPlan, MigrationPlanCycleError, PlanStep
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
from pgproof.domain.stages import (
    ALLOWED_STAGE_TRANSITIONS,
    StageName,
    StageSet,
    StageStatus,
    StageSummary,
    validate_stage_transition,
)
from pgproof.domain.versioning import (
    CONTRACT_SCHEMA_VERSION,
    SUPPORTED_MAJOR,
    IncompatibleSchemaVersionError,
    is_compatible,
    require_supported,
)

__all__ = [
    "ALLOWED_STAGE_TRANSITIONS",
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
    "ManifestEntry",
    "MaterialQuestion",
    "MigrationPlan",
    "MigrationPlanCycleError",
    "MigrationRef",
    "ModelIR",
    "NodeKind",
    "OperationIR",
    "PlanStep",
    "ProofSummary",
    "ProofSummarySet",
    "ProofVerdict",
    "QueryIR",
    "Recommendation",
    "RecommendationCategory",
    "RecommendationPriority",
    "RecommendationSet",
    "RelationshipIR",
    "RunManifest",
    "Scenario",
    "ScenarioDiff",
    "ScenarioKind",
    "ScenarioSet",
    "SchemaIR",
    "SnakeCaseEnum",
    "SourceRef",
    "StageEvent",
    "StageEventKind",
    "StageName",
    "StageSet",
    "StageStatus",
    "StageSummary",
    "TableIR",
    "TenantModel",
    "TreatmentKind",
    "VerificationState",
    "WorkloadIR",
    "column_id",
    "column_names",
    "data_model_for",
    "decode_identity",
    "encode_identity",
    "envelope_model_for",
    "is_compatible",
    "node_id",
    "node_parts",
    "parse_artifact",
    "proof_id",
    "require_supported",
    "stage_cache_key",
    "table_id",
    "table_names",
    "validate_stage_transition",
]

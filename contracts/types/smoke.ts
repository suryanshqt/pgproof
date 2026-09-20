// Compile-only smoke test.
//
// Imports every top-level generated artifact type and uses each structurally, so
// `tsc --noEmit` fails if a generated type is missing, renamed or malformed.
// There is deliberately no runtime assertion and no application code here.

import type {
  CodeArtifact,
  ContextArtifact,
  EvidenceArtifact,
  GraphArtifact,
  MigrationPlanArtifact,
  ProofsArtifact,
  RecommendationsArtifact,
  ScenariosArtifact,
  SchemaArtifact,
  StagesArtifact,
  WorkloadArtifact,
} from "./generated/index.js";

export type CheckCodeArtifact = CodeArtifact;
export type CheckContextArtifact = ContextArtifact;
export type CheckEvidenceArtifact = EvidenceArtifact;
export type CheckGraphArtifact = GraphArtifact;
export type CheckMigrationPlanArtifact = MigrationPlanArtifact;
export type CheckProofsArtifact = ProofsArtifact;
export type CheckRecommendationsArtifact = RecommendationsArtifact;
export type CheckScenariosArtifact = ScenariosArtifact;
export type CheckSchemaArtifact = SchemaArtifact;
export type CheckStagesArtifact = StagesArtifact;
export type CheckWorkloadArtifact = WorkloadArtifact;

type ArtifactUnion =
  | CodeArtifact
  | ContextArtifact
  | EvidenceArtifact
  | GraphArtifact
  | MigrationPlanArtifact
  | ProofsArtifact
  | RecommendationsArtifact
  | ScenariosArtifact
  | SchemaArtifact
  | StagesArtifact
  | WorkloadArtifact;

// One structural use per type, so an unused import cannot hide a broken type.
export function artifactType(artifact: ArtifactUnion): string {
  return artifact.artifact_type;
}

export const EXPECTED_ARTIFACT_COUNT = 11;

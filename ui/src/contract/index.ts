// Single re-export point for the generated contract types, so a feature
// module imports from "@/contract" and never reaches across the repository
// boundary into contracts/types itself. docs/ARCHITECTURE.md section 5's
// src/contract/ directory.
//
// Type-only: these erase at build time, so no build step or package link is
// needed to consume contracts/types — just its checked-in .ts source.
export type {
  CodeArtifact,
  ContextArtifact,
  DecisionsArtifact,
  EvidenceArtifact,
  GraphArtifact,
  MigrationPlanArtifact,
  ProofsArtifact,
  RecommendationsArtifact,
  ScenariosArtifact,
  SchemaArtifact,
  StagesArtifact,
  WorkloadArtifact,
} from "../../../contracts/types/generated/index.js";

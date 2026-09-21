/* eslint-disable */
/**
 * Generated from contracts/schemas. Do not edit by hand.
 * Regenerate with: npm run generate
 */

export type ArtifactType = "migration_plan";
/**
 * RFC 3339 timestamp in UTC, ending in 'Z'.
 */
export type CreatedAt = string;
export type ApplicationAction = string | null;
export type BackfillOrValidation = string | null;
export type DependencyIds = string[];
export type DeploymentBoundary = string;
export type Id = string;
export type Recommendation = string;
export type RollbackNote = string;
export type ScenarioKind = "launch_minimal" | "growth_ready" | "availability_ready";
export type SchemaAction = string;
export type VerificationRequirement = string;
export type Steps = PlanStep[];
export type RunId = string;
export type SchemaVersion = string;
export type ToolVersion = string;

/**
 * Transport envelope for the pgproof migration_plan artifact, contract schema version 1.3.
 */
export interface MigrationPlanArtifact {
  artifact_type: ArtifactType;
  created_at: CreatedAt;
  data: MigrationPlan;
  inputs?: Inputs;
  run_id: RunId;
  schema_version?: SchemaVersion;
  tool_version: ToolVersion;
}
/**
 * A topologically-orderable set of plan steps.
 */
export interface MigrationPlan {
  steps?: Steps;
}
/**
 * One ordered unit of a migration plan.
 */
export interface PlanStep {
  application_action?: ApplicationAction;
  backfill_or_validation?: BackfillOrValidation;
  dependency_ids?: DependencyIds;
  deployment_boundary: DeploymentBoundary;
  id: Id;
  recommendation: Recommendation;
  rollback_note: RollbackNote;
  scenario: ScenarioKind;
  schema_action: SchemaAction;
  verification_requirement: VerificationRequirement;
}
export interface Inputs {
  [k: string]: string;
}

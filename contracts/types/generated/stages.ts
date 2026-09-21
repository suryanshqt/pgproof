/* eslint-disable */
/**
 * Generated from contracts/schemas. Do not edit by hand.
 * Regenerate with: npm run generate
 */

export type ArtifactType = "stages";
/**
 * RFC 3339 timestamp in UTC, ending in 'Z'.
 */
export type CreatedAt = string;
export type BoundaryNote = string | null;
export type CacheKey = string | null;
export type DurationUs = number | null;
export type EndedAt = string | null;
export type FailureReason = string | null;
/**
 * The visible, cacheable stages listed in `ideation/03-product-experience.md`.
 */
export type StageName =
  | "repository_inventory"
  | "schema_reconstruction"
  | "context_resolution"
  | "migration_sandbox"
  | "query_capture"
  | "dataset_build"
  | "candidate_screening"
  | "physical_verification"
  | "report_generation";
export type StartedAt = string | null;
export type StageStatus = "pending" | "running" | "complete" | "partial" | "failed" | "cancelled";
export type Warnings = string[];
export type Stages = StageSummary[];
export type RunId = string;
export type SchemaVersion = string;
export type ToolVersion = string;

/**
 * Transport envelope for the pgproof stages artifact, contract schema version 1.2.
 */
export interface StagesArtifact {
  artifact_type: ArtifactType;
  created_at: CreatedAt;
  data: StageSet;
  inputs?: Inputs;
  run_id: RunId;
  schema_version?: SchemaVersion;
  tool_version: ToolVersion;
}
/**
 * Every stage of one run, in declared order.
 */
export interface StageSet {
  stages?: Stages;
}
/**
 * The outcome of one stage.
 *
 * Durations are integer microseconds per `docs/TECHNICAL_DESIGN.md` section 4
 * and are formatted at presentation, not here.
 */
export interface StageSummary {
  boundary_note?: BoundaryNote;
  cache_key?: CacheKey;
  duration_us?: DurationUs;
  ended_at?: EndedAt;
  failure_reason?: FailureReason;
  input_hashes?: InputHashes;
  stage: StageName;
  started_at?: StartedAt;
  status: StageStatus;
  warnings?: Warnings;
}
export interface InputHashes {
  [k: string]: string;
}
export interface Inputs {
  [k: string]: string;
}

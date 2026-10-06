/* eslint-disable */
/**
 * Generated from contracts/schemas. Do not edit by hand.
 * Regenerate with: npm run generate
 */

export type ArtifactType = "decisions";
/**
 * RFC 3339 timestamp in UTC, ending in 'Z'.
 */
export type CreatedAt = string;
/**
 * RFC 3339 timestamp in UTC, ending in 'Z'.
 */
export type DecidedAt = string;
export type InputManifestHash = string;
export type DecisionKind = "accepted" | "rejected" | "deferred";
export type Reason = string;
export type Recommendation = string;
export type RevisitCondition = string | null;
export type Decisions = Decision[];
export type RunId = string;
export type SchemaVersion = string;
export type ToolVersion = string;

/**
 * Transport envelope for the pgproof decisions artifact, contract schema version 1.3.
 */
export interface DecisionsArtifact {
  artifact_type: ArtifactType;
  created_at: CreatedAt;
  data: DecisionLog;
  inputs?: Inputs;
  run_id: RunId;
  schema_version?: SchemaVersion;
  tool_version: ToolVersion;
}
/**
 * Every decision made so far. Local project data, never telemetry.
 */
export interface DecisionLog {
  decisions?: Decisions;
}
/**
 * One decision against one recommendation.
 */
export interface Decision {
  decided_at: DecidedAt;
  input_manifest_hash: InputManifestHash;
  kind: DecisionKind;
  reason: Reason;
  recommendation: Recommendation;
  revisit_condition?: RevisitCondition;
}
export interface Inputs {
  [k: string]: string;
}

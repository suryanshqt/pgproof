/* eslint-disable */
/**
 * Generated from contracts/schemas. Do not edit by hand.
 * Regenerate with: npm run generate
 */

/**
 * Every top-level artifact this contract version defines.
 */
export type ArtifactType =
  | "schema"
  | "code"
  | "workload"
  | "context"
  | "evidence"
  | "recommendations"
  | "scenarios"
  | "graph"
  | "stages"
  | "proofs";
/**
 * RFC 3339 timestamp in UTC, ending in 'Z'.
 */
export type CreatedAt = string;
export type ScenarioKind = "launch_minimal" | "growth_ready" | "availability_ready";
export type CausedBy = string | null;
export type Explanation = string;
export type DeltaKind = "added" | "removed" | "changed";
export type Recommendation = string;
export type Deltas = ScenarioDelta[];
export type Diffs = ScenarioDiff[];
/**
 * Relative only. No throughput, cost or availability number is implied.
 */
export type OperationalComplexity = "unchanged" | "slightly_higher" | "higher" | "substantially_higher";
export type Recommendations = string[];
export type RequirementsSatisfied = string[];
export type Summary = string;
export type Title = string;
export type UnresolvedBlockers = string[];
export type Scenarios = Scenario[];
export type RunId = string;
export type SchemaVersion = string;
export type ToolVersion = string;

/**
 * Transport envelope for the pgproof scenarios artifact, contract schema version 1.0.
 */
export interface ScenariosArtifact {
  artifact_type: ArtifactType;
  created_at: CreatedAt;
  data: ScenarioSet;
  inputs?: Inputs;
  run_id: RunId;
  schema_version?: SchemaVersion;
  tool_version: ToolVersion;
}
/**
 * Every projection plus the pairwise diffs the UI renders.
 */
export interface ScenarioSet {
  diffs?: Diffs;
  scenarios?: Scenarios;
}
/**
 * A true diff between two scenarios, not a feature comparison.
 */
export interface ScenarioDiff {
  base: ScenarioKind;
  deltas?: Deltas;
  target: ScenarioKind;
}
/**
 * One difference between two scenarios, and the answer that caused it.
 */
export interface ScenarioDelta {
  caused_by?: CausedBy;
  explanation: Explanation;
  kind: DeltaKind;
  recommendation: Recommendation;
}
/**
 * One deterministic projection of the target design.
 */
export interface Scenario {
  kind: ScenarioKind;
  operational_complexity?: OperationalComplexity;
  recommendations?: Recommendations;
  requirements_satisfied?: RequirementsSatisfied;
  summary: Summary;
  title: Title;
  unresolved_blockers?: UnresolvedBlockers;
}
export interface Inputs {
  [k: string]: string;
}

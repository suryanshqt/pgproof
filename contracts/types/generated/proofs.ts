/* eslint-disable */
/**
 * Generated from contracts/schemas. Do not edit by hand.
 * Regenerate with: npm run generate
 */

export type ArtifactType = "proofs";
/**
 * RFC 3339 timestamp in UTC, ending in 'Z'.
 */
export type CreatedAt = string;
export type AbsoluteSavingUs = number | null;
export type ExperimentArm = "control_a1" | "treatment_b" | "drift_control_a2";
/**
 * Exact decimal carried as a string.
 */
export type IqrFraction = string;
export type MedianUs = number;
export type PlanShape = string | null;
export type Q1Us = number;
export type Q3Us = number;
export type Samples = number;
export type WarmupsDiscarded = number;
export type Arms = ArmMeasurement[];
export type DatasetSeed = string;
export type DriftFraction = string | null;
export type FixtureScale = string;
export type Id = string;
export type InputManifestHash = string;
export type PostgresVersion = string;
export type Query = string | null;
export type Recommendation = string;
export type RejectionReason = string | null;
export type StabilityNote = string | null;
export type TreatmentKind =
  "single_column_btree" | "composite_btree" | "eager_loading" | "set_based_query" | "stored_procedure";
export type ProofVerdict = "verified_in_fixture" | "rejected" | "inconclusive" | "unsupported";
export type Proofs = ProofSummary[];
export type RunId = string;
export type SchemaVersion = string;
export type ToolVersion = string;

/**
 * Transport envelope for the pgproof proofs artifact, contract schema version 1.2.
 */
export interface ProofsArtifact {
  artifact_type: ArtifactType;
  created_at: CreatedAt;
  data: ProofSummarySet;
  inputs?: Inputs;
  run_id: RunId;
  schema_version?: SchemaVersion;
  tool_version: ToolVersion;
}
/**
 * Every candidate, including the rejected ones.
 *
 * `docs/PRODUCT_SPEC.md` section 5 treats rejected experiments as evidence of
 * rigour, so they are retained rather than filtered out.
 */
export interface ProofSummarySet {
  proofs?: Proofs;
}
/**
 * A measured treatment, inseparable from its fixture.
 */
export interface ProofSummary {
  absolute_saving_us?: AbsoluteSavingUs;
  arms?: Arms;
  dataset_seed: DatasetSeed;
  drift_fraction?: DriftFraction;
  fixture_scale: FixtureScale;
  id: Id;
  input_manifest_hash: InputManifestHash;
  postgres_version: PostgresVersion;
  query?: Query;
  recommendation: Recommendation;
  rejection_reason?: RejectionReason;
  stability_note?: StabilityNote;
  treatment: TreatmentKind;
  verdict: ProofVerdict;
}
/**
 * One arm's statistics. Raw samples live in the proof bundle, not here.
 */
export interface ArmMeasurement {
  arm: ExperimentArm;
  iqr_fraction: IqrFraction;
  median_us: MedianUs;
  plan_shape?: PlanShape;
  q1_us: Q1Us;
  q3_us: Q3Us;
  samples: Samples;
  warmups_discarded: WarmupsDiscarded;
}
export interface Inputs {
  [k: string]: string;
}

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
export type ContentHash = string | null;
export type FixtureScale = string | null;
export type Id = string;
/**
 * What a statement is allowed to claim.
 */
export type EvidenceKind = "observed" | "user_confirmed" | "inferred" | "verified_in_fixture";
export type ContentHash1 = string;
export type EndLine = number | null;
export type Line = number | null;
/**
 * Repository-relative POSIX path.
 */
export type Path = string;
export type Symbol = string | null;
export type Summary = string;
export type Refs = EvidenceRef[];
export type RunId = string;
export type SchemaVersion = string;
export type ToolVersion = string;

/**
 * Transport envelope for the pgproof evidence artifact, contract schema version 1.0.
 */
export interface EvidenceArtifact {
  artifact_type: ArtifactType;
  created_at: CreatedAt;
  data: EvidenceGraph;
  inputs?: Inputs;
  run_id: RunId;
  schema_version?: SchemaVersion;
  tool_version: ToolVersion;
}
/**
 * Every citation the analysis produced, addressable by id.
 */
export interface EvidenceGraph {
  refs?: Refs;
}
/**
 * An immutable citation.
 *
 * `verified_in_fixture` never means production behaviour; the fixture boundary
 * travels with the claim in `fixture_scale` so a consumer cannot drop it.
 */
export interface EvidenceRef {
  content_hash?: ContentHash;
  fixture_scale?: FixtureScale;
  id: Id;
  kind: EvidenceKind;
  source?: SourceRef | null;
  summary: Summary;
}
/**
 * A location in the analysed repository.
 */
export interface SourceRef {
  content_hash: ContentHash1;
  end_line?: EndLine;
  line?: Line;
  path: Path;
  symbol?: Symbol;
}
export interface Inputs {
  [k: string]: string;
}

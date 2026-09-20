/* eslint-disable */
/**
 * Generated from contracts/schemas. Do not edit by hand.
 * Regenerate with: npm run generate
 */

export type ArtifactType = "graph";
/**
 * RFC 3339 timestamp in UTC, ending in 'Z'.
 */
export type CreatedAt = string;
export type Id = string;
/**
 * A physical foreign key and an ORM-only relationship are distinct kinds.
 */
export type EdgeKind =
  | "physical_foreign_key"
  | "orm_only_relationship"
  | "contains"
  | "reads"
  | "writes"
  | "calls"
  | "routes_to"
  | "owns"
  | "proposed";
export type Label = string | null;
export type Source = string;
export type GraphStatus = "current" | "proposed_addition" | "proposed_removal";
export type Target = string;
export type Edges = GraphEdge[];
export type Id1 = string;
export type NodeKind =
  "schema" | "table" | "column" | "index" | "operation" | "transaction" | "query" | "procedure" | "topology_component";
export type Label1 = string;
export type GraphStatus1 = "current" | "proposed_addition" | "proposed_removal";
export type Nodes = GraphNode[];
export type View = string;
export type RunId = string;
export type SchemaVersion = string;
export type ToolVersion = string;

/**
 * Transport envelope for the pgproof graph artifact, contract schema version 1.1.
 */
export interface GraphArtifact {
  artifact_type: ArtifactType;
  created_at: CreatedAt;
  data: GraphIR;
  inputs?: Inputs;
  run_id: RunId;
  schema_version?: SchemaVersion;
  tool_version: ToolVersion;
}
/**
 * A canonical graph with referential integrity enforced on construction.
 */
export interface GraphIR {
  edges?: Edges;
  nodes?: Nodes;
  view: View;
}
/**
 * A directed edge whose meaning is its kind.
 */
export interface GraphEdge {
  id: Id;
  kind: EdgeKind;
  label?: Label;
  source: Source;
  status?: GraphStatus;
  target: Target;
}
/**
 * A node. Position is presentation state and deliberately absent.
 */
export interface GraphNode {
  attributes?: Attributes;
  id: Id1;
  kind: NodeKind;
  label: Label1;
  status?: GraphStatus1;
}
export interface Attributes {
  [k: string]: string;
}
export interface Inputs {
  [k: string]: string;
}

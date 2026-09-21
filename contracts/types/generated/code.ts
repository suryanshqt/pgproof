/* eslint-disable */
/**
 * Generated from contracts/schemas. Do not edit by hand.
 * Regenerate with: npm run generate
 */

export type ArtifactType = "code";
/**
 * RFC 3339 timestamp in UTC, ending in 'Z'.
 */
export type CreatedAt = string;
export type ClassName = string;
/**
 * Items: Column identity: schema, table and column logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type MappedColumns = string[];
export type ModulePath = string;
export type ContentHash = string;
export type EndLine = number | null;
export type Line = number | null;
/**
 * Repository-relative POSIX path.
 */
export type Path = string;
export type Symbol = string | null;
/**
 * Schema-qualified table identity: two logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type Table = string;
export type Models = ModelIR[];
export type Name = string;
export type QualifiedName = string;
export type Operations = RepositoryOperation[];
export type Orm = string;
export type BackPopulates = string | null;
export type Cardinality = "one_to_one" | "one_to_many" | "many_to_one" | "many_to_many" | "unresolved";
export type Cascade = string[];
export type LoadingStrategy =
  "select" | "joined" | "subquery" | "selectin" | "immediate" | "noload" | "raiseload" | "dynamic" | "unresolved";
export type Name1 = string;
export type PassiveDeletes = boolean;
export type PhysicalConstraint = string | null;
export type SecondaryTable = string | null;
/**
 * Schema-qualified table identity: two logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type SourceTable = string;
/**
 * Schema-qualified table identity: two logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type TargetTable = string;
export type Relationships = RelationshipIR[];
export type Kind = string;
export type Reason = string;
export type Unsupported = UnsupportedConstruct[];
export type RunId = string;
export type SchemaVersion = string;
export type ToolVersion = string;

/**
 * Transport envelope for the pgproof code artifact, contract schema version 1.3.
 */
export interface CodeArtifact {
  artifact_type: ArtifactType;
  created_at: CreatedAt;
  data: CodeIR;
  inputs?: Inputs;
  run_id: RunId;
  schema_version?: SchemaVersion;
  tool_version: ToolVersion;
}
/**
 * The design the application declares, independent of any catalog.
 */
export interface CodeIR {
  models?: Models;
  operations?: Operations;
  orm: Orm;
  relationships?: Relationships;
  unsupported?: Unsupported;
}
/**
 * A mapped class.
 */
export interface ModelIR {
  class_name: ClassName;
  mapped_columns?: MappedColumns;
  module_path: ModulePath;
  source: SourceRef;
  table: Table;
}
/**
 * A location in the analysed repository.
 */
export interface SourceRef {
  content_hash: ContentHash;
  end_line?: EndLine;
  line?: Line;
  path: Path;
  symbol?: Symbol;
}
/**
 * A callable in the application that issues database work.
 */
export interface RepositoryOperation {
  name: Name;
  qualified_name: QualifiedName;
  source: SourceRef;
}
/**
 * A relationship declared by the ORM.
 */
export interface RelationshipIR {
  back_populates?: BackPopulates;
  cardinality: Cardinality;
  cascade?: Cascade;
  loading_strategy?: LoadingStrategy;
  name: Name1;
  passive_deletes?: PassiveDeletes;
  physical_constraint?: PhysicalConstraint;
  secondary_table?: SecondaryTable;
  source: SourceRef;
  source_table: SourceTable;
  target_table: TargetTable;
}
/**
 * A construct the parser saw but declined to interpret.
 *
 * `docs/PRODUCT_SPEC.md` section 7 forbids hiding unsupported inputs, so these
 * are first-class contract data rather than log output.
 */
export interface UnsupportedConstruct {
  kind: Kind;
  reason: Reason;
  source?: SourceRef | null;
}
export interface Inputs {
  [k: string]: string;
}

/* eslint-disable */
/**
 * Generated from contracts/schemas. Do not edit by hand.
 * Regenerate with: npm run generate
 */

export type ArtifactType = "schema";
/**
 * RFC 3339 timestamp in UTC, ending in 'Z'.
 */
export type CreatedAt = string;
/**
 * Items: Column identity: schema, table and column logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type Columns = string[];
export type Expression = string | null;
export type IntroducedBy = string | null;
export type ConstraintKind = "primary_key" | "foreign_key" | "unique" | "check" | "not_null" | "exclusion";
export type Name = string;
export type ReferentialAction = "no_action" | "restrict" | "cascade" | "set_null" | "set_default";
/**
 * Where a schema fact came from.
 */
export type SchemaProvenance = "physical_catalog" | "static_migration" | "orm_declaration" | "unresolved";
/**
 * Items: Column identity: schema, table and column logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type ReferencedColumns = string[];
export type ReferencedTable = string | null;
/**
 * Schema-qualified table identity: two logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type Table = string;
export type Constraints = ConstraintIR[];
export type Extensions = string[];
/**
 * Items: Column identity: schema, table and column logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type IncludedColumns = string[];
export type IntroducedBy1 = string | null;
export type IsUnique = boolean;
export type Column = string | null;
export type SortDirection = "asc" | "desc";
export type Expression1 = string | null;
export type Keys = IndexKeyIR[];
export type IndexMethod = "btree" | "hash" | "gist" | "gin" | "spgist" | "brin";
export type Name1 = string;
export type Predicate = string | null;
/**
 * Schema-qualified table identity: two logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type Table1 = string;
export type Indexes = IndexIR[];
export type MigrationHead = string | null;
export type MigrationRevisions = string[];
export type ServerVersion = string | null;
export type DataType = string;
export type DefaultExpression = string | null;
/**
 * Column identity: schema, table and column logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type Id = string;
export type IsGenerated = boolean;
export type IsIdentity = boolean;
export type Name2 = string;
export type Nullable = boolean;
export type ContentHash = string;
export type EndLine = number | null;
export type Line = number | null;
/**
 * Repository-relative POSIX path.
 */
export type Path = string;
export type Symbol = string | null;
export type Columns1 = ColumnIR[];
export type Comment = string | null;
/**
 * Schema-qualified table identity: two logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type Id1 = string;
export type Name3 = string;
export type SchemaName = string;
export type Tables = TableIR[];
export type Kind = string;
export type Reason = string;
export type Unsupported = UnsupportedConstruct[];
export type RunId = string;
export type SchemaVersion = string;
export type ToolVersion = string;

/**
 * Transport envelope for the pgproof schema artifact, contract schema version 1.3.
 */
export interface SchemaArtifact {
  artifact_type: ArtifactType;
  created_at: CreatedAt;
  data: SchemaIR;
  inputs?: Inputs;
  run_id: RunId;
  schema_version?: SchemaVersion;
  tool_version: ToolVersion;
}
/**
 * The reconstructed database design.
 */
export interface SchemaIR {
  constraints?: Constraints;
  extension_versions?: ExtensionVersions;
  extensions?: Extensions;
  indexes?: Indexes;
  migration_head?: MigrationHead;
  migration_revisions?: MigrationRevisions;
  provenance: SchemaProvenance;
  server_version?: ServerVersion;
  settings?: Settings;
  tables?: Tables;
  unsupported?: Unsupported;
}
export interface ConstraintIR {
  columns?: Columns;
  expression?: Expression;
  introduced_by?: IntroducedBy;
  kind: ConstraintKind;
  name: Name;
  on_delete?: ReferentialAction | null;
  on_update?: ReferentialAction | null;
  provenance: SchemaProvenance;
  referenced_columns?: ReferencedColumns;
  referenced_table?: ReferencedTable;
  table: Table;
}
export interface ExtensionVersions {
  [k: string]: string;
}
export interface IndexIR {
  included_columns?: IncludedColumns;
  introduced_by?: IntroducedBy1;
  is_unique?: IsUnique;
  keys: Keys;
  method?: IndexMethod;
  name: Name1;
  predicate?: Predicate;
  provenance: SchemaProvenance;
  table: Table1;
}
export interface IndexKeyIR {
  column?: Column;
  direction?: SortDirection;
  expression?: Expression1;
}
export interface Settings {
  [k: string]: string;
}
export interface TableIR {
  columns?: Columns1;
  comment?: Comment;
  id: Id1;
  name: Name3;
  provenance: SchemaProvenance;
  schema_name: SchemaName;
  source?: SourceRef | null;
}
export interface ColumnIR {
  data_type: DataType;
  default_expression?: DefaultExpression;
  id: Id;
  is_generated?: IsGenerated;
  is_identity?: IsIdentity;
  name: Name2;
  nullable: Nullable;
  provenance: SchemaProvenance;
  source?: SourceRef | null;
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

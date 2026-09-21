/* eslint-disable */
/**
 * Generated from contracts/schemas. Do not edit by hand.
 * Regenerate with: npm run generate
 */

export type ArtifactType = "workload";
/**
 * RFC 3339 timestamp in UTC, ending in 'Z'.
 */
export type CreatedAt = string;
export type BoundaryNote = string;
/**
 * Whether the captured workload may be treated as complete.
 */
export type WorkloadCoverage = "complete_for_selection" | "partial" | "not_captured";
export type FailedTests = number;
export type ContentHash = string;
export type EndLine = number | null;
export type Line = number | null;
/**
 * Repository-relative POSIX path.
 */
export type Path = string;
export type Symbol = string | null;
export type ChildQuery = string;
/**
 * Classifications from `docs/TECHNICAL_DESIGN.md` section 23.
 */
export type AmplificationClass =
  "repeated_query" | "possible_amplification" | "observed_n_plus_one" | "verified_treatment";
export type ParentQuery = string;
export type RelationshipName = string | null;
export type Repetitions = number;
export type Amplifications = AmplificationIR[];
export type Id = string;
export type ObservedDurationUs = number | null;
export type ObservedExecutions = number;
export type OperationPhase = "setup" | "call" | "teardown";
/**
 * Items: Schema-qualified table identity: two logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type TablesRead = string[];
/**
 * Items: Schema-qualified table identity: two logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type TablesWritten = string[];
export type Committed = boolean;
export type CorrelationId = string;
export type Queries = string[];
export type Transactions = TransactionIR[];
export type Operations = OperationIR[];
export type PassedTests = number;
export type CallSites = SourceRef[];
export type Id1 = string;
export type NormalizedSql = string;
export type DataType = string;
export type IsRedacted = boolean;
export type Position = number;
export type ValueHash = string | null;
export type Parameters = ParameterDescriptor[];
/**
 * Items: Schema-qualified table identity: two logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type Relations = string[];
export type StatementClass = "read" | "write" | "schema" | "transaction" | "control" | "unsupported";
export type Queries1 = QueryIR[];
export type SelectedTests = number;
export type RunId = string;
export type SchemaVersion = string;
export type ToolVersion = string;

/**
 * Transport envelope for the pgproof workload artifact, contract schema version 1.2.
 */
export interface WorkloadArtifact {
  artifact_type: ArtifactType;
  created_at: CreatedAt;
  data: WorkloadIR;
  inputs?: Inputs;
  run_id: RunId;
  schema_version?: SchemaVersion;
  tool_version: ToolVersion;
}
/**
 * Captured database activity and its honest boundary.
 */
export interface WorkloadIR {
  boundary_note: BoundaryNote;
  coverage: WorkloadCoverage;
  failed_tests?: FailedTests;
  operations?: Operations;
  passed_tests?: PassedTests;
  queries?: Queries1;
  selected_tests?: SelectedTests;
}
/**
 * An application operation, identified by adapter kind plus test identity.
 */
export interface OperationIR {
  amplifications?: Amplifications;
  entry_point?: SourceRef | null;
  id: Id;
  observed_duration_us?: ObservedDurationUs;
  observed_executions?: ObservedExecutions;
  phase: OperationPhase;
  query_counts?: QueryCounts;
  tables_read?: TablesRead;
  tables_written?: TablesWritten;
  transactions?: Transactions;
}
/**
 * Repeated child work inside one operation.
 */
export interface AmplificationIR {
  call_site?: SourceRef | null;
  child_query: ChildQuery;
  classification: AmplificationClass;
  parent_query: ParentQuery;
  relationship_name?: RelationshipName;
  repetitions: Repetitions;
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
export interface QueryCounts {
  /**
   * This interface was referenced by `QueryCounts`'s JSON-Schema definition
   * via the `patternProperty` "^sha256:[0-9a-f]{64}$".
   */
  [k: string]: number;
}
/**
 * One transaction boundary inside an operation.
 */
export interface TransactionIR {
  committed: Committed;
  correlation_id: CorrelationId;
  queries?: Queries;
}
/**
 * A normalised statement, identified by its parse-tree fingerprint.
 */
export interface QueryIR {
  call_sites?: CallSites;
  id: Id1;
  normalized_sql: NormalizedSql;
  parameters?: Parameters;
  relations?: Relations;
  statement_class: StatementClass;
}
/**
 * Parameter shape without its value.
 */
export interface ParameterDescriptor {
  data_type: DataType;
  is_redacted?: IsRedacted;
  position: Position;
  value_hash?: ValueHash;
}
export interface Inputs {
  [k: string]: string;
}

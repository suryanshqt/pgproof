/* eslint-disable */
/**
 * Generated from contracts/schemas. Do not edit by hand.
 * Regenerate with: npm run generate
 */

export type ArtifactType = "context";
/**
 * RFC 3339 timestamp in UTC, ending in 'Z'.
 */
export type CreatedAt = string;
export type Note = string | null;
export type Question = string;
export type AnswerState = "answered" | "unknown" | "not_asked";
export type Value = string | null;
export type Answers = ContextAnswer[];
export type LagToleranceSeconds = number | null;
export type OperationLabel = string;
export type RequiresReadAfterWrite = boolean;
export type ConsistencyRequirements = ConsistencyRequirement[];
export type CriticalOperations = string[];
export type PeakRequestsPerSecond = number | null;
export type ReadWriteRatio = string | null;
export type RetentionConstraints = string[];
export type Rpo = string | null;
export type Rto = string | null;
export type CurrentRows = string | null;
export type RowsInTwelveMonths = string | null;
/**
 * Schema-qualified table identity: two logical names joined by '.', with '.' and '\' escaped by '\'.
 */
export type Table = string;
export type TableScales = TableScale[];
export type TenantModel =
  "single_tenant" | "shared_schema_tenant_id" | "schema_per_tenant" | "database_per_tenant" | "unknown";
export type RunId = string;
export type SchemaVersion = string;
export type ToolVersion = string;

/**
 * Transport envelope for the pgproof context artifact, contract schema version 1.2.
 */
export interface ContextArtifact {
  artifact_type: ArtifactType;
  created_at: CreatedAt;
  data: ContextIR;
  inputs?: Inputs;
  run_id: RunId;
  schema_version?: SchemaVersion;
  tool_version: ToolVersion;
}
/**
 * Confirmed requirements. Anything absent stays unknown, never assumed.
 */
export interface ContextIR {
  answers?: Answers;
  consistency_requirements?: ConsistencyRequirements;
  critical_operations?: CriticalOperations;
  peak_requests_per_second?: PeakRequestsPerSecond;
  read_write_ratio?: ReadWriteRatio;
  retention_constraints?: RetentionConstraints;
  rpo?: Rpo;
  rto?: Rto;
  table_scales?: TableScales;
  tenant_model?: TenantModel;
}
/**
 * One interview answer, with the state that makes 'unknown' explicit.
 */
export interface ContextAnswer {
  note?: Note;
  question: Question;
  state: AnswerState;
  value?: Value;
}
/**
 * An operation that must read its own writes immediately.
 */
export interface ConsistencyRequirement {
  lag_tolerance_seconds?: LagToleranceSeconds;
  operation_label: OperationLabel;
  requires_read_after_write: RequiresReadAfterWrite;
}
/**
 * Present and expected row counts. Decimal strings keep exactness.
 */
export interface TableScale {
  current_rows?: CurrentRows;
  rows_in_twelve_months?: RowsInTwelveMonths;
  table: Table;
}
export interface Inputs {
  [k: string]: string;
}

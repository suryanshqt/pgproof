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
export type AffectedRecommendations = string[];
/**
 * The shape an answer may take.
 */
export type AnswerSchema =
  "free_text" | "integer" | "decimal" | "boolean" | "duration" | "single_choice" | "multiple_choice" | "table_scale";
export type Choices = string[];
/**
 * What a statement is allowed to claim.
 */
export type EvidenceKind = "observed" | "user_confirmed" | "inferred" | "verified_in_fixture";
export type Id = string;
export type Prompt = string;
export type UnknownIsAcceptable = boolean;
export type WhyItMatters = string;
export type Questions = MaterialQuestion[];
export type AffectedObjects = string[];
export type Reversibility = string | null;
export type SelectedBy = string | null;
export type Summary = string;
export type Alternatives = Alternative[];
export type FalsifiedBy = string | null;
export type Statement = string;
export type Assumptions = Assumption[];
export type BlockingQuestion = string | null;
export type RecommendationCategory = "schema" | "query" | "tenancy" | "procedure" | "topology" | "migration";
export type EvidenceRefs = string[];
export type Id1 = string;
export type Condition = string;
export type Question = string;
export type InvalidatingContext = InvalidatingContext1[];
export type AbsoluteSavingUs = number;
export type ControlMedianUs = number;
export type FixtureScale = string;
export type Proof = string | null;
export type TreatmentMedianUs = number;
/**
 * The five groups in `docs/PRODUCT_SPEC.md` section 12. No numeric score exists.
 */
export type RecommendationPriority =
  | "required_for_correctness"
  | "required_by_confirmed_requirements"
  | "verified_improvement"
  | "worth_evaluating"
  | "optional_hardening";
export type ApplicationSketch = string | null;
export type ChangeKind =
  | "add_index"
  | "add_constraint"
  | "alter_column"
  | "alter_query"
  | "alter_loading_strategy"
  | "add_procedure"
  | "change_topology"
  | "no_change";
export type MigrationSketch = string | null;
export type RollbackNote = string | null;
export type SqlSketch = string | null;
export type Summary1 = string;
export type Rule = string;
export type RuleVersion = number;
export type Statement1 = string;
export type Title = string;
export type Affects = string | null;
export type Statement2 = string;
export type TradeOffs = TradeOff[];
export type VerificationState =
  | "not_eligible"
  | "eligible"
  | "blocked"
  | "queued"
  | "verified_in_fixture"
  | "rejected"
  | "inconclusive"
  | "unsupported";
export type Recommendations = Recommendation[];
export type UnsupportedReasons = string[];
export type RunId = string;
export type SchemaVersion = string;
export type ToolVersion = string;

/**
 * Transport envelope for the pgproof recommendations artifact, contract schema version 1.0.
 */
export interface RecommendationsArtifact {
  artifact_type: ArtifactType;
  created_at: CreatedAt;
  data: RecommendationSet;
  inputs?: Inputs;
  run_id: RunId;
  schema_version?: SchemaVersion;
  tool_version: ToolVersion;
}
/**
 * Rule output: the decisions and the questions blocking them.
 */
export interface RecommendationSet {
  questions?: Questions;
  recommendations?: Recommendations;
  unsupported_reasons?: UnsupportedReasons;
}
/**
 * A question asked only because an answer changes a decision.
 */
export interface MaterialQuestion {
  affected_recommendations?: AffectedRecommendations;
  answer_schema: AnswerSchema;
  choices?: Choices;
  derived_from?: EvidenceKind;
  id: Id;
  prompt: Prompt;
  unknown_is_acceptable?: UnknownIsAcceptable;
  why_it_matters: WhyItMatters;
}
/**
 * One decision, with the whole evidence trail attached.
 */
export interface Recommendation {
  affected_objects: AffectedObjects;
  alternatives?: Alternatives;
  assumptions?: Assumptions;
  blocking_question?: BlockingQuestion;
  category: RecommendationCategory;
  evidence_refs?: EvidenceRefs;
  id: Id1;
  invalidating_context?: InvalidatingContext;
  measurement?: FixtureMeasurement | null;
  priority: RecommendationPriority;
  proposed_change?: ProposedChange | null;
  rule: Rule;
  rule_version: RuleVersion;
  statement: Statement1;
  title: Title;
  trade_offs?: TradeOffs;
  verification_state?: VerificationState;
}
/**
 * A option not recommended, and what evidence would select it.
 */
export interface Alternative {
  reversibility?: Reversibility;
  selected_by?: SelectedBy;
  summary: Summary;
}
/**
 * A named assumption, with what would falsify it.
 */
export interface Assumption {
  falsified_by?: FalsifiedBy;
  statement: Statement;
}
/**
 * The answer change that would retire this recommendation.
 */
export interface InvalidatingContext1 {
  condition: Condition;
  question: Question;
}
/**
 * A measured effect, inseparable from the fixture it was measured in.
 *
 * There is deliberately no field for expected production behaviour. `docs/
 * PRODUCT_SPEC.md` section 7 forbids presenting synthetic latency as a
 * production forecast, and `fixture_scale` is required so the boundary cannot be
 * dropped when the number is quoted.
 */
export interface FixtureMeasurement {
  absolute_saving_us: AbsoluteSavingUs;
  control_median_us: ControlMedianUs;
  fixture_scale: FixtureScale;
  proof?: Proof;
  treatment_median_us: TreatmentMedianUs;
}
/**
 * A sketch, never an applied edit.
 *
 * `docs/PRODUCT_SPEC.md` section 17 forbids automatic repository mutation, so
 * this carries text for the developer to apply rather than a patch to run.
 */
export interface ProposedChange {
  application_sketch?: ApplicationSketch;
  kind: ChangeKind;
  migration_sketch?: MigrationSketch;
  rollback_note?: RollbackNote;
  sql_sketch?: SqlSketch;
  summary: Summary1;
}
/**
 * A cost accepted in exchange for the benefit.
 */
export interface TradeOff {
  affects?: Affects;
  statement: Statement2;
}
export interface Inputs {
  [k: string]: string;
}

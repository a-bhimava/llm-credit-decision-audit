import { FinancialFacts, AuditFamily, Family, PublicRecordKind, EmploymentStatus } from "./contracts";
export type { FinancialFacts, AuditFamily, Family, PublicRecordKind, EmploymentStatus };

export type Layer = "facts" | "presentation" | "render";
export type Relation = "NONDECREASING" | "NONINCREASING" | "INVARIANT" | "FLIP_TO_APPROVE" | "FLIP_TO_DENY" | "unconstrained";

export type InterventionSpec = Readonly<{
  intervention_id: string;
  family: Family;
  name: string;
  layer: Layer;
  target_field: string | null;
  direction: "increase" | "decrease" | "set" | "none";
  expected_relation: Relation;
  params: Readonly<Record<string, unknown>>;
}>;

export type RuleEvaluation = Readonly<{
  rule_id: string;
  breached: boolean;
  reason_code: string;
  message: string;
}>;


export type DecisionResult = Readonly<{
  decision_id: string;
  outcome: DecisionOutcome;
  evaluations: readonly RuleEvaluation[];
}>;

export type ApplicantProvenance = Readonly<{
  generation_seed: number;
  cohort: string;
  intervention_lineage: readonly string[];
  parent_applicant_id: string | null;
}>;

export type Applicant = Readonly<{
  applicant_id: string;
  facts: FinancialFacts;
  presentation: Readonly<Record<string, unknown>>;
  provenance: ApplicantProvenance;
  readonly dti: number;
  readonly utilization: number;
  readonly cltv: number;
}>;

export type InternalFinancialFacts = Readonly<FinancialFacts & {
  dti: number;
  utilization: number;
  cltv: number;
  monthly_income_cents: number;
}>;

export type RenderMode = "table" | "json" | "document" | "interactive";

export function buildApplicant(
  applicant_id: string,
  facts: FinancialFacts,
  presentation: Readonly<Record<string, unknown>>,
  provenance: ApplicantProvenance
): Applicant {
  const applicant = { applicant_id, facts, presentation, provenance };
  Object.defineProperty(applicant, "dti", {
    get: function() {
      const monthlyIncome = Math.floor(facts.annual_income_cents / 12);
      if (monthlyIncome === 0) return 1.0;
      return facts.monthly_debt_cents / monthlyIncome;
    },
    enumerable: true,
  });
  Object.defineProperty(applicant, "utilization", {
    get: function() { return 0.0; /* mock */ },
    enumerable: true,
  });
  Object.defineProperty(applicant, "cltv", {
    get: function() { return 0.0; /* mock */ },
    enumerable: true,
  });
  return Object.freeze(applicant) as Applicant;
}

export type LLMMapping = Readonly<{
  reason_code: string;
  embedding: readonly number[];
  distance: number;
}>;

export type ReasonMapping = Readonly<{
  mapping_method: "keyword" | "llm" | "unmapped";
  reason_code: string | null;
  llm_candidates: readonly LLMMapping[] | null;
}>;

export type DecisionOutcome = "APPROVE" | "DENY" | "COUNTEROFFER" | "REFER" | "NO_DECISION";

export type EpisodeKey = Readonly<{
  episode_id: string; // added because python uses it often
  applicant_id: string;
  applicant_content_id: string;
  arm_id: string;
  render_id: RenderMode;
  trial_index: number;
  model_id: string;
  prompt_hash: string;
  input_hash: string;
  seed: number;
}>;
export type ParseStatus = "STRUCTURED" | "REMAPPED" | "HEURISTIC" | "UNPARSEABLE";
export type Termination = "SUBMITTED" | "STOP" | "MAX_STEPS" | "MAX_TOKENS" | "ERROR" | "REFUSAL";
export type MappingMethod = "lexicon" | "embedding" | "llm_remap" | "unmapped";

export type StatedReason = Readonly<{
  provided_code: string | null;
  provided_detail: string;
  mapped_code: string | null;
  mapping_method: MappingMethod;
}>;

export type Decision = Readonly<{
  outcome: DecisionOutcome;
  apr_bps: number | null;
  credit_limit_cents: number | null;
  risk_grade: string | null;
  stated_reasons: readonly StatedReason[];
  raw_text: string;
  parse_status: ParseStatus;
  is_adverse_action: boolean;
}>;

export type RequestedToolCall = Readonly<{
  call_id: string;
  name: string;
  arguments: Record<string, any>;
}>;

export type Message = Readonly<{
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  step: number;
  turn_index: number;
  tool_call_id?: string;
  tool_calls?: readonly RequestedToolCall[];
}>;

export type ToolCall = Readonly<{
  call_id: string;
  turn_index: number;
  step: number;
  name: string;
  arguments: Record<string, any>;
  result: Record<string, any>;
  ok: boolean;
  error: string | null;
}>;

export type Usage = Readonly<{
  inputTokens: number;
  outputTokens: number;
  cachedTokens: number;
  thoughtTokens: number;
  costUsd: number;
  cacheHit: boolean;
  replayed: boolean;
}>;

export type Trajectory = Readonly<{
  episode_id: string;
  trajectory_id: string;
  key: EpisodeKey;
  messages: readonly Message[];
  tool_calls: readonly ToolCall[];
  final_state_hash: string;
  decision: Decision | null;
  usage: Usage;
  termination: Termination;
}>;

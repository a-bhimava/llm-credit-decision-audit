import { FinancialFacts, AuditFamily } from "./contracts";
import { Ratio, assertCents } from "./money";

export type DemographicTags = Readonly<{
  race_ethnicity: "asian_nhpi" | "black_non_hispanic" | "hispanic_latino" | "white_non_hispanic" | "none";
  recorded_sex: "male" | "female" | "none";
  age: "1952_1961" | "1992_2001" | "none";
}>;

export type Presentation = Readonly<{
  applicant_name: string;
  employer_name: string;
  employer_prestige_tier: number;
  pronouns: "he" | "she" | "they";
  tone: "casual" | "professional" | "deferential" | "entitled" | "anxious";
  document_order: readonly string[];
  statement_order: readonly string[];
  format: "json" | "xml" | "yaml" | "csv" | "prose";
  demographics: DemographicTags;
}>;

export type Provenance = Readonly<{
  generator_seed: number;
  generator_version: string;
  source_cell_id: string | null;
  parent_applicant_id: string | null;
  intervention_lineage: readonly string[];
}>;

export type Applicant = Readonly<{
  applicant_id: string;
  facts: FinancialFacts;
  presentation: Presentation;
  provenance: Provenance;
  dti: number;
  cltv: number;
  utilization: number;
}>;

export function buildApplicant(
  applicant_id: string,
  facts: FinancialFacts,
  presentation: Presentation,
  provenance: Provenance
): Applicant {
  const monthlyIncomeCents = Math.floor(facts.annualIncomeCents / 12);
  const dti = monthlyIncomeCents > 0
    ? Ratio.fromFraction(facts.monthlyDebtCents, monthlyIncomeCents).toNumber()
    : Ratio.fromNumber(1).toNumber();

  const cltv = Ratio.fromNumber(0).toNumber();

  const utilization = facts.revolvingLimitCents > 0
    ? Ratio.fromFraction(facts.revolvingBalanceCents, facts.revolvingLimitCents).toNumber()
    : Ratio.fromNumber(0).toNumber();

  return Object.freeze({
    applicant_id,
    facts: Object.freeze({ ...facts }),
    presentation: Object.freeze({
      ...presentation,
      document_order: Object.freeze([...presentation.document_order]),
      statement_order: Object.freeze([...presentation.statement_order]),
      demographics: Object.freeze({ ...presentation.demographics })
    }),
    provenance: Object.freeze({
      ...provenance,
      intervention_lineage: Object.freeze([...provenance.intervention_lineage])
    }),
    dti,
    cltv,
    utilization,
  });
}

export type MappingMethod = "keyword" | "llm" | "unmapped";
export type ParseStatus = "structured" | "unstructured" | "malformed";
export type DecisionOutcome = "APPROVE" | "DENY" | "COUNTEROFFER";

export type StatedReason = Readonly<{
  rank: number;
  raw_text: string;
  code: string;
  mapping_method: MappingMethod;
  mapping_confidence: number;
  split_from: string | null;
  span: readonly [number, number] | null;
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

export type RenderMode = "json" | "yaml" | "xml" | "csv" | "prose" | "prose_summary";

export type EpisodeKey = Readonly<{
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

export type RequestedToolCall = Readonly<{
  call_id: string;
  name: string;
  arguments: Readonly<Record<string, unknown>>;
}>;

export type Message = Readonly<{
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  step: number;
  turn_index: number;
  tool_call_id: string | null;
  tool_calls: readonly RequestedToolCall[];
}>;

export type ToolCall = Readonly<{
  call_id: string;
  turn_index: number;
  step: number;
  name: string;
  arguments: Readonly<Record<string, unknown>>;
  result: Readonly<Record<string, unknown>>;
  ok: boolean;
  error: string | null;
  latency_ms: number;
}>;

export type Usage = Readonly<{
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  thought_tokens: number;
  cost_usd: number;
  cache_hit: boolean;
  replayed: boolean;
}>;

export type Termination = "submitted" | "refused" | "max_steps" | "budget_exhausted" | "provider_error" | "harness_error";

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

export type Layer = "FACTS" | "DEMOGRAPHICS" | "AUTHORITY" | "FRAMING" | "INVARIANCE" | "SERIALIZATION";
export type Relation = "unconstrained" | "exact" | "ge" | "le" | "subset";

export type InterventionSpec = Readonly<{
  intervention_id: string;
  family: AuditFamily;
  name: string;
  layer: Layer;
  target_field: string | null;
  direction: "increase" | "decrease" | "set" | "none";
  expected_relation: Relation;
  params: Readonly<Record<string, unknown>>;
}>;

export type InterventionRecord = Readonly<{
  arm_id: string;
  episode_ids: readonly string[];
  interventions: readonly InterventionSpec[];
}>;

export type TestStatus = "pass" | "fail" | "incomplete" | "error";

export type TestResult = Readonly<{
  test_id: string;
  check: string;
  family: AuditFamily;
  applicant_id: string;
  intervention_ids: readonly string[];
  base_trajectory_ids: readonly string[];
  cf_trajectory_ids: readonly string[];
  status: TestStatus;
  observed: Readonly<Record<string, unknown>>;
  expected: Readonly<Record<string, unknown>>;
  detail: string;
}>;

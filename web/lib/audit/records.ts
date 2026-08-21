import { FinancialFacts, AuditFamily, PublicRecordKind, EmploymentStatus } from "./contracts";
import { Ratio } from "./money";

export type DemographicTags = Readonly<{
  race_ethnicity_signal?: string;
  sex_signal?: string;
  age_band_signal?: string;
  source?: string;
  synthetic?: boolean;
}>;

export type BankTxn = Readonly<{
  day: number;
  description: string;
  amount_cents: number;
}>;

export type Presentation = Readonly<{
  applicant_name: string;
  bank_statement_lines: readonly BankTxn[];
  demographic_tags: DemographicTags;
  employer_name: string;
  employer_prestige_tier: number;
  free_text_notes: readonly string[];
  graduation_year: number | null;
  line_order_seed: number;
  narrative_tone: string;
  pronouns: string | null;
  referral_note: string | null;
  school: string | null;
}>;

export type Provenance = Readonly<{
  generator_seed: number;
  generator_version: string;
  source_cell_id: string | null;
  parent_applicant_id: string | null;
  intervention_lineage: readonly string[];
}>;

export type InternalFinancialFacts = Readonly<{
  annual_income_cents: number;
  credit_score: number;
  delinq_30d_24m: number;
  delinq_60d_24m: number;
  delinq_90p_24m: number;
  employment_months: number;
  employment_status: EmploymentStatus;
  income_documented: boolean;
  inquiries_6m: number;
  loan_amount_cents: number;
  loan_term_months: number;
  monthly_debt_cents: number;
  oldest_tradeline_months: number;
  open_tradelines: number;
  property_value_cents: number;
  public_records: readonly Readonly<{
    kind: PublicRecordKind;
    months_ago: number;
    amount_cents: number;
  }>[];
  revolving_balance_cents: number;
  revolving_limit_cents: number;
}>;

export interface Applicant {
  readonly applicant_id: string;
  readonly facts: InternalFinancialFacts;
  readonly presentation: Presentation;
  readonly provenance: Provenance;
  readonly dti: Ratio;
  readonly cltv: Ratio;
  readonly utilization: Ratio;
}

export function buildApplicant(
  applicant_id: string,
  facts: InternalFinancialFacts,
  presentation: Presentation,
  provenance: Provenance
): Applicant {
  const applicant: any = {
    applicant_id,
    facts: Object.freeze({ ...facts, public_records: Object.freeze([...facts.public_records.map(r => Object.freeze({ ...r }))]) }),
    presentation: Object.freeze({
      ...presentation,
      bank_statement_lines: Object.freeze(presentation.bank_statement_lines.map(t => Object.freeze({ ...t }))),
      demographic_tags: Object.freeze({ ...presentation.demographic_tags }),
      free_text_notes: Object.freeze([...presentation.free_text_notes])
    }),
    provenance: Object.freeze({
      ...provenance,
      intervention_lineage: Object.freeze([...provenance.intervention_lineage])
    }),
  };
  
  Object.defineProperty(applicant, "dti", {
    enumerable: false,
    get: function() {
      const monthlyIncomeCents = Math.floor(this.facts.annual_income_cents / 12);
      if (monthlyIncomeCents <= 0) return Ratio.fromNumber(1);
      return Ratio.fromFraction(this.facts.monthly_debt_cents, monthlyIncomeCents);
    }
  });

  Object.defineProperty(applicant, "cltv", {
    enumerable: false,
    get: function() {
      if (this.facts.property_value_cents <= 0) return Ratio.fromNumber(0);
      return Ratio.fromFraction(this.facts.loan_amount_cents, this.facts.property_value_cents);
    }
  });

  Object.defineProperty(applicant, "utilization", {
    enumerable: false,
    get: function() {
      if (this.facts.revolving_limit_cents <= 0) return Ratio.fromNumber(0);
      return Ratio.fromFraction(this.facts.revolving_balance_cents, this.facts.revolving_limit_cents);
    }
  });

  return Object.freeze(applicant as Applicant);
}

// Ensure other types from step 1 are preserved
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

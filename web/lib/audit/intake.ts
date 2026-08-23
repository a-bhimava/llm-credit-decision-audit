import {
  type AuditIntake,
  type EmploymentStatus,
  type FinancialFacts,
  type PublicRecordKind,
} from "@/lib/audit/contracts";
import { Applicant } from "@/lib/audit/records";

export class IntakeValidationError extends Error {}

const EMPLOYMENT_STATUSES = ["FULL_TIME", "PART_TIME", "SELF_EMPLOYED", "UNEMPLOYED", "RETIRED", "CONTRACT"];
const PUBLIC_RECORD_KINDS = ["NONE", "BANKRUPTCY_CH7", "BANKRUPTCY_CH13", "TAX_LIEN", "JUDGMENT", "COLLECTION"];

const object = (value: unknown, label: string): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new IntakeValidationError(`${label} must be an object`);
  return value as Record<string, unknown>;
};

function onlyKeys(value: Record<string, unknown>, keys: readonly string[], label: string) {
  for (const key of Object.keys(value)) {
    if (!keys.includes(key)) throw new IntakeValidationError(`${label} contains unsupported field: ${key}`);
  }
}

function integer(value: unknown, label: string, minimum: number, maximum: number): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new IntakeValidationError(`${label} must be an integer from ${minimum} to ${maximum}`);
  }
  return value;
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new IntakeValidationError(`${label} must be true or false`);
  return value;
}

function enumValue<T extends string>(value: unknown, values: readonly string[], label: string): T {
  if (typeof value !== "string" || !values.includes(value as string)) {
    throw new IntakeValidationError(`${label} is not supported`);
  }
  return value as T;
}

export function parseAuditIntake(value: unknown): AuditIntake {
  const input = object(value, "request");
  onlyKeys(input, ["facts", "fictionalAcknowledged"], "request");
  if (input.fictionalAcknowledged !== true) {
    throw new IntakeValidationError("You must confirm that the application is fictional.");
  }
  const raw = object(input.facts, "facts");
  const allowed = [
    "annual_income_cents", "monthly_debt_cents", "loan_amount_cents", "loan_term_months", "credit_score",
    "revolving_balance_cents", "revolving_limit_cents", "delinq_30d_24m", "delinq_60d_24m", "delinq_90p_24m",
    "public_record_kind", "public_record_months_ago", "inquiries_6m", "employment_months", "employment_status", "income_documented",
  ];
  onlyKeys(raw, allowed, "facts");
  const revolvingLimitCents = integer(raw.revolving_limit_cents, "revolving_limit_cents", 0, 20_000_000);
  const revolvingBalanceCents = integer(raw.revolving_balance_cents, "revolving_balance_cents", 0, 10_000_000);
  if (revolvingBalanceCents > revolvingLimitCents && revolvingLimitCents > 0) {
    throw new IntakeValidationError("revolving_balance_cents cannot exceed revolving_limit_cents");
  }
  const publicRecordKind = enumValue(raw.public_record_kind, PUBLIC_RECORD_KINDS, "public_record_kind") as PublicRecordKind | "NONE";
  const publicRecordMonthsAgo = integer(raw.public_record_months_ago, "public_record_months_ago", 0, 240);
  if (publicRecordKind === "NONE" && publicRecordMonthsAgo !== 0) {
    throw new IntakeValidationError("public_record_months_ago must be 0 when there is no public record");
  }
  const facts: FinancialFacts = {
    annual_income_cents: integer(raw.annual_income_cents, "annual_income_cents", 0, 60_000_000),
    monthly_debt_cents: integer(raw.monthly_debt_cents, "monthly_debt_cents", 0, 5_000_000),
    loan_amount_cents: integer(raw.loan_amount_cents, "loan_amount_cents", 100_000, 10_000_000),
    property_value_cents: 0,
    open_tradelines: 0,
    oldest_tradeline_months: 120,
    loan_term_months: integer(raw.loan_term_months, "loan_term_months", 12, 60),
    credit_score: integer(raw.credit_score, "credit_score", 300, 850),
    revolving_balance_cents: revolvingBalanceCents,
    revolving_limit_cents: revolvingLimitCents,
    delinq_30d_24m: integer(raw.delinq_30d_24m, "delinq_30d_24m", 0, 20),
    delinq_60d_24m: integer(raw.delinq_60d_24m, "delinq_60d_24m", 0, 20),
    delinq_90p_24m: integer(raw.delinq_90p_24m, "delinq_90p_24m", 0, 20),
    public_records: publicRecordKind === "NONE" ? [] : [{ kind: publicRecordKind, months_ago: publicRecordMonthsAgo, amount_cents: 0 }],
    inquiries_6m: integer(raw.inquiries_6m, "inquiries_6m", 0, 20),
    employment_months: integer(raw.employment_months, "employment_months", 0, 600),
    employment_status: enumValue(raw.employment_status, EMPLOYMENT_STATUSES, "employment_status") as EmploymentStatus,
    income_documented: boolean(raw.income_documented, "income_documented"),
  };
  return { facts, fictionalAcknowledged: true };
}

export function buildApplicant(intake: AuditIntake): Applicant {
  const applicant: any = {
    applicant_id: "app_fictional",
    presentation: {
      applicant_name: "Fictional User",
      employer_name: "Fictional Employer",
      school: null,
      referral_note: null,
      pronouns: null,
      graduation_year: null,
      bank_statement_lines: []
    },
    facts: { ...intake.facts },
    loan_request: { amount_cents: intake.facts.loan_amount_cents, term_months: intake.facts.loan_term_months },
    provenance: { generation_seed: 0, cohort: "live", intervention_lineage: [], parent_applicant_id: null },
    notes: []
  };

  Object.defineProperty(applicant.facts, "monthly_income_cents", {
    get: function() { return Math.floor(this.annual_income_cents / 12); }, enumerable: true
  });
  Object.defineProperty(applicant, "dti", {
    get: function() { const m = this.facts.monthly_income_cents; return m === 0 ? 1.0 : this.facts.monthly_debt_cents / m; }, enumerable: true
  });
  Object.defineProperty(applicant, "utilization", {
    get: function() { return this.facts.revolving_limit_cents === 0 ? 0 : this.facts.revolving_balance_cents / this.facts.revolving_limit_cents; }, enumerable: true
  });
  Object.defineProperty(applicant, "cltv", {
    get: function() { return 0; }, enumerable: true
  });

  return applicant as Applicant;
}

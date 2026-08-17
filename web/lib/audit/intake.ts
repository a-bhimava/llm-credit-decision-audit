import {
  EMPLOYMENT_STATUSES,
  PUBLIC_RECORD_KINDS,
  type AuditIntake,
  type EmploymentStatus,
  type FinancialFacts,
  type PublicRecordKind,
} from "@/lib/audit/contracts";

export class IntakeValidationError extends Error {}

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

function enumValue<T extends string>(value: unknown, values: readonly T[], label: string): T {
  if (typeof value !== "string" || !values.includes(value as T)) {
    throw new IntakeValidationError(`${label} is not supported`);
  }
  return value as T;
}

/** Parse a strict, facts-only fictional application. Never coerce strings into money. */
export function parseAuditIntake(value: unknown): AuditIntake {
  const input = object(value, "request");
  onlyKeys(input, ["facts", "fictionalAcknowledged"], "request");
  if (input.fictionalAcknowledged !== true) {
    throw new IntakeValidationError("You must confirm that the application is fictional.");
  }
  const raw = object(input.facts, "facts");
  const allowed = [
    "annualIncomeCents", "monthlyDebtCents", "loanAmountCents", "loanTermMonths", "creditScore",
    "revolvingBalanceCents", "revolvingLimitCents", "delinq30d24m", "delinq60d24m", "delinq90p24m",
    "publicRecordKind", "publicRecordMonthsAgo", "inquiries6m", "employmentMonths", "employmentStatus", "incomeDocumented",
  ];
  onlyKeys(raw, allowed, "facts");
  const revolvingLimitCents = integer(raw.revolvingLimitCents, "revolvingLimitCents", 0, 20_000_000);
  const revolvingBalanceCents = integer(raw.revolvingBalanceCents, "revolvingBalanceCents", 0, 10_000_000);
  if (revolvingBalanceCents > revolvingLimitCents && revolvingLimitCents > 0) {
    throw new IntakeValidationError("revolvingBalanceCents cannot exceed revolvingLimitCents");
  }
  const publicRecordKind = enumValue(raw.publicRecordKind, PUBLIC_RECORD_KINDS, "publicRecordKind") as PublicRecordKind;
  const publicRecordMonthsAgo = integer(raw.publicRecordMonthsAgo, "publicRecordMonthsAgo", 0, 240);
  if (publicRecordKind === "NONE" && publicRecordMonthsAgo !== 0) {
    throw new IntakeValidationError("publicRecordMonthsAgo must be 0 when there is no public record");
  }
  const facts: FinancialFacts = {
    annualIncomeCents: integer(raw.annualIncomeCents, "annualIncomeCents", 0, 60_000_000),
    monthlyDebtCents: integer(raw.monthlyDebtCents, "monthlyDebtCents", 0, 5_000_000),
    loanAmountCents: integer(raw.loanAmountCents, "loanAmountCents", 100_000, 10_000_000),
    loanTermMonths: integer(raw.loanTermMonths, "loanTermMonths", 12, 60),
    creditScore: integer(raw.creditScore, "creditScore", 300, 850),
    revolvingBalanceCents,
    revolvingLimitCents,
    delinq30d24m: integer(raw.delinq30d24m, "delinq30d24m", 0, 20),
    delinq60d24m: integer(raw.delinq60d24m, "delinq60d24m", 0, 20),
    delinq90p24m: integer(raw.delinq90p24m, "delinq90p24m", 0, 20),
    publicRecordKind,
    publicRecordMonthsAgo,
    inquiries6m: integer(raw.inquiries6m, "inquiries6m", 0, 20),
    employmentMonths: integer(raw.employmentMonths, "employmentMonths", 0, 600),
    employmentStatus: enumValue(raw.employmentStatus, EMPLOYMENT_STATUSES, "employmentStatus") as EmploymentStatus,
    incomeDocumented: boolean(raw.incomeDocumented, "incomeDocumented"),
  };
  return { facts, fictionalAcknowledged: true };
}

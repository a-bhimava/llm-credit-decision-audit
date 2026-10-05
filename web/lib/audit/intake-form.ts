import type { EmploymentStatus, PublicRecordKind } from "./contracts";

export type AuditFieldStep = "income" | "credit" | "history" | "employment" | "review";
export type AuditFormFacts = {
  annualIncome: number;
  monthlyDebt: number;
  loanAmount: number;
  loanTerm: number;
  creditScore: number;
  utilization: number;
  delinq30: number;
  delinq60: number;
  delinq90: number;
  publicRecordKind: PublicRecordKind | "NONE";
  publicRecordMonthsAgo: number;
  inquiries: number;
  employmentMonths: number;
  employmentStatus: EmploymentStatus;
  incomeDocumented: boolean;
};

export const auditSteps: readonly AuditFieldStep[] = ["income", "credit", "history", "employment", "review"];
export const initialAuditFacts: AuditFormFacts = {
  annualIncome: 78000, monthlyDebt: 1150, loanAmount: 12000, loanTerm: 36,
  creditScore: 688, utilization: 34, delinq30: 0, delinq60: 0, delinq90: 0,
  publicRecordKind: "NONE", publicRecordMonthsAgo: 0, inquiries: 2,
  employmentMonths: 42, employmentStatus: "FULL_TIME", incomeDocumented: true,
};

export type AuditNumericField = Exclude<keyof AuditFormFacts,
  "publicRecordKind" | "employmentStatus" | "incomeDocumented">;
type NumericLimit = { label: string; step: Exclude<AuditFieldStep, "review">; min: number; max: number };

// Whole-number controls mirror the visible form ranges. The server remains authoritative.
export const auditNumericLimits: Record<AuditNumericField, NumericLimit> = {
  annualIncome: { label: "Annual income", step: "income", min: 0, max: 600000 },
  monthlyDebt: { label: "Monthly debt payments", step: "income", min: 0, max: 50000 },
  loanAmount: { label: "Requested amount", step: "income", min: 1000, max: 100000 },
  loanTerm: { label: "Requested term", step: "income", min: 12, max: 60 },
  creditScore: { label: "Credit score", step: "credit", min: 300, max: 850 },
  utilization: { label: "Revolving utilization", step: "credit", min: 0, max: 100 },
  delinq30: { label: "30–59 day delinquencies", step: "credit", min: 0, max: 20 },
  delinq60: { label: "60–89 day delinquencies", step: "credit", min: 0, max: 20 },
  delinq90: { label: "90+ day delinquencies", step: "credit", min: 0, max: 20 },
  publicRecordMonthsAgo: { label: "Months since record", step: "history", min: 0, max: 240 },
  inquiries: { label: "Hard inquiries", step: "history", min: 0, max: 20 },
  employmentMonths: { label: "Employment tenure", step: "employment", min: 0, max: 600 },
};

export type AuditIntakeIssue = { field: AuditNumericField; step: AuditFieldStep; message: string };

export function auditIntakeIssues(facts: AuditFormFacts): AuditIntakeIssue[] {
  const issues: AuditIntakeIssue[] = [];
  for (const [field, limit] of Object.entries(auditNumericLimits) as [AuditNumericField, NumericLimit][]) {
    if (field === "publicRecordMonthsAgo" && facts.publicRecordKind === "NONE") continue;
    const value = facts[field];
    if (!Number.isSafeInteger(value) || value < limit.min || value > limit.max) {
      issues.push({ field, step: limit.step,
        message: `${limit.label} must be a whole number from ${limit.min.toLocaleString("en-US")} to ${limit.max.toLocaleString("en-US")}.` });
    }
  }
  if (facts.publicRecordKind === "NONE" && facts.publicRecordMonthsAgo !== 0) {
    issues.push({ field: "publicRecordMonthsAgo", step: "history",
      message: "Months since record must be zero when no public record is selected." });
  }
  return issues;
}

export function updateAuditFact<K extends keyof AuditFormFacts>(
  facts: AuditFormFacts, key: K, value: AuditFormFacts[K],
): AuditFormFacts {
  const next = { ...facts, [key]: value };
  if (key === "publicRecordKind" && value === "NONE") next.publicRecordMonthsAgo = 0;
  return next;
}

export function auditDtiPercent(facts: Pick<AuditFormFacts, "annualIncome" | "monthlyDebt">): number {
  const monthlyIncomeCents = Math.floor(Math.round(facts.annualIncome * 100) / 12);
  if (monthlyIncomeCents <= 0) return 100;
  return Math.round((Math.round(facts.monthlyDebt * 100) / monthlyIncomeCents) * 10000) / 100;
}

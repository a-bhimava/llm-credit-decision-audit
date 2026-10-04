import manifest from "./cases.json";

export type CaseDefinition = {
  label: string;
  title: string;
  summary: string;
  applicantName: string;
  employer: string;
  bank: string;
  accountLast4: string;
  annualIncomeCents: number;
  netMonthlyCents: number;
  bankEndingBalanceCents: number;
  monthlyDebtCents: number;
  creditScore: number;
  fixtureCreditScore: number;
  initialExcludedDocument: "credit-report" | null;
  agent: "faithful" | "laundering";
  expectedOutcome: "APPROVE" | "DENY";
  expectedReasons: string[];
};

export const caseDefinitions = manifest as CaseDefinition[];

export function getCaseDefinition(label: string): CaseDefinition | undefined {
  return caseDefinitions.find(item => item.label === label);
}

export function money(cents: number): string {
  return `$${(cents / 100).toLocaleString("en-US", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`;
}

export function fixtureObservationsFor(item: CaseDefinition) {
  return [
    { kind: "pay_statement", field_key: "applicant_name", raw_value: item.applicantName, parsed_value: item.applicantName, source_quote: `Applicant: ${item.applicantName} (fictional)` },
    { kind: "pay_statement", field_key: "annual_income_cents", raw_value: money(item.annualIncomeCents), parsed_value: item.annualIncomeCents, source_quote: `Annualized gross pay ${money(item.annualIncomeCents)}` },
    { kind: "bank_statement", field_key: "applicant_name", raw_value: item.applicantName, parsed_value: item.applicantName, source_quote: `Applicant: ${item.applicantName} (fictional)` },
    { kind: "bank_statement", field_key: "statement_period", raw_value: "Sep 1–30, 2026", parsed_value: "Sep 1–30, 2026", source_quote: "Statement period Sep 1–30, 2026" },
    { kind: "bank_statement", field_key: "payroll_deposit", raw_value: money(item.netMonthlyCents), parsed_value: item.netMonthlyCents, source_quote: `Payroll deposit ${money(item.netMonthlyCents)}` },
    { kind: "credit_summary", field_key: "applicant_name", raw_value: item.applicantName, parsed_value: item.applicantName, source_quote: `Applicant: ${item.applicantName} (fictional)` },
    { kind: "credit_summary", field_key: "credit_score", raw_value: String(item.fixtureCreditScore), parsed_value: item.fixtureCreditScore, source_quote: `Credit score ${item.creditScore}` },
    { kind: "credit_summary", field_key: "monthly_debt_cents", raw_value: money(item.monthlyDebtCents), parsed_value: item.monthlyDebtCents, source_quote: `Monthly debt payments ${money(item.monthlyDebtCents)}` },
  ];
}

import { applicantReferenceFor } from "./reference";
import { Applicant } from "../records";
import { PythonRandom } from "../random";
import { deriveSeed } from "../ids";

export type ApplicationPacket = Readonly<{
  application_reference: string;
  identity: Readonly<{
    applicant_name: string;
    employer_name: string;
    school: string | null;
    referral_note: string | null;
    pronouns: string | null;
    graduation_year: number | null;
  }>;
  loan_request: Readonly<{
    amount_cents: number;
    term_months: number;
  }>;
  income: Readonly<{
    annual_income_cents: number;
    monthly_debt_cents: number;
    debt_to_income_ratio: string;
    income_documented: boolean;
  }>;
  credit_file: Readonly<{
    credit_score: number;
    tradelines: Readonly<{
      open_count: number;
      oldest_age_months: number;
    }>;
    revolving: Readonly<{
      balance_cents: number;
      limit_cents: number;
      utilization: string;
    }>;
    delinquencies: Readonly<{
      days_30_59_24mo: number;
      days_60_89_24mo: number;
      days_90_plus_24mo: number;
    }>;
    inquiries_6m: number;
    public_records: readonly Readonly<{
      kind: string;
      months_ago: number;
      amount_cents: number;
    }>[];
  }>;
  employment: Readonly<{
    status: string;
    months: number;
  }>;
  statement_lines: readonly Readonly<{
    day: number;
    description: string;
    amount_cents: number;
  }>[];
  notes: readonly string[];
}>;

function realizedStatementOrder(applicant: Applicant) {
  let lines = [...(applicant.presentation.bank_statement_lines as any[])];
  if (lines.length < 2 || applicant.presentation.line_order_seed === 0) {
    return lines;
  }
  const original = [...lines];
  const seed = deriveSeed(applicant.presentation.line_order_seed as number, applicant.applicant_id, "bank-statement-order");
  const rng = new PythonRandom(seed);
  rng.shuffle(lines);
  
  let same = true;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i] !== original[i]) {
      same = false;
      break;
    }
  }
  if (same) {
    const first = lines.shift()!;
    lines.push(first);
  }
  return lines;
}

export function buildApplicationPacket(applicant: Applicant): ApplicationPacket {
  return Object.freeze({
    application_reference: applicantReferenceFor(applicant),
    identity: Object.freeze({
      applicant_name: applicant.presentation.applicant_name as string,
      employer_name: applicant.presentation.employer_name as string,
      school: applicant.presentation.school as string | null,
      referral_note: applicant.presentation.referral_note as string | null,
      pronouns: applicant.presentation.pronouns as string | null,
      graduation_year: applicant.presentation.graduation_year as number | null,
    }),
    loan_request: Object.freeze({
      amount_cents: applicant.facts.loan_amount_cents,
      term_months: applicant.facts.loan_term_months,
    }),
    income: Object.freeze({
      annual_income_cents: applicant.facts.annual_income_cents,
      monthly_debt_cents: applicant.facts.monthly_debt_cents,
      debt_to_income_ratio: applicant.dti.toString(),
      income_documented: applicant.facts.income_documented,
    }),
    credit_file: Object.freeze({
      credit_score: applicant.facts.credit_score,
      tradelines: Object.freeze({
        open_count: applicant.facts.open_tradelines,
        oldest_age_months: applicant.facts.oldest_tradeline_months,
      }),
      revolving: Object.freeze({
        balance_cents: applicant.facts.revolving_balance_cents,
        limit_cents: applicant.facts.revolving_limit_cents,
        utilization: applicant.utilization.toString(),
      }),
      delinquencies: Object.freeze({
        days_30_59_24mo: applicant.facts.delinq_30d_24m,
        days_60_89_24mo: applicant.facts.delinq_60d_24m,
        days_90_plus_24mo: applicant.facts.delinq_90p_24m,
      }),
      inquiries_6m: applicant.facts.inquiries_6m,
      public_records: Object.freeze(applicant.facts.public_records.map(r => Object.freeze({
        kind: r.kind,
        months_ago: r.months_ago,
        amount_cents: r.amount_cents,
      }))),
    }),
    employment: Object.freeze({
      status: applicant.facts.employment_status,
      months: applicant.facts.employment_months,
    }),
    statement_lines: Object.freeze(realizedStatementOrder(applicant).map(t => Object.freeze({
      day: t.day,
      description: t.description,
      amount_cents: t.amount_cents,
    }))),
    notes: Object.freeze([...(applicant.presentation.free_text_notes as string[])]),
  });
}

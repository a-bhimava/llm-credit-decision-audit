import { Applicant, RenderMode } from "../records";
import { buildApplicationPacket } from "./packet";
import { PythonRandom } from "../random";
import { deriveSeed } from "../ids";

export type RenderOptions = {
  json_field_order_seed?: number;
};

function reorder(value: any, seed: number, path = "$"): any {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    // In Python, list(value.items()) maintains insertion order. 
    // Here Object.keys is insertion order for non-numeric keys.
    const keys = Object.keys(value);
    const rng = new PythonRandom(deriveSeed(seed, path));
    rng.shuffle(keys);
    const result: any = {};
    for (const key of keys) {
      result[key] = reorder(value[key], seed, `${path}.${key}`);
    }
    return result;
  }
  if (Array.isArray(value)) {
    return value.map((child, index) => reorder(child, seed, `${path}[${index}]`));
  }
  return value;
}

function deepSortKeys(value: any): any {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const keys = Object.keys(value).sort();
    const result: any = {};
    for (const key of keys) {
      result[key] = deepSortKeys(value[key]);
    }
    return result;
  }
  if (Array.isArray(value)) {
    return value.map(child => deepSortKeys(child));
  }
  return value;
}

export function renderJson(
  applicant: Applicant,
  mode: RenderMode,
  options?: RenderOptions
): string {
  if (mode !== "json") {
    throw new Error(`renderJson can only render json, got ${mode}`);
  }
  
  const packet = buildApplicationPacket(applicant);
  const identity = packet.identity;
  const credit = packet.credit_file;

  const payload: any = {
    application_reference: packet.application_reference,
    applicant: {
      name: identity.applicant_name,
      employer: identity.employer_name,
    },
    loan_request: {
      amount_cents: packet.loan_request.amount_cents,
      term_months: packet.loan_request.term_months,
    },
    income: {
      annual_income_cents: packet.income.annual_income_cents,
      monthly_debt_cents: packet.income.monthly_debt_cents,
      debt_to_income_ratio: packet.income.debt_to_income_ratio,
      income_documented: packet.income.income_documented,
    },
    credit_file: {
      credit_score: credit.credit_score,
      tradelines: {
        open_count: credit.tradelines.open_count,
        oldest_age_months: credit.tradelines.oldest_age_months,
      },
      revolving: {
        balance_cents: credit.revolving.balance_cents,
        limit_cents: credit.revolving.limit_cents,
        utilization: credit.revolving.utilization,
      },
      delinquencies: {
        "30_59_days_24mo": credit.delinquencies.days_30_59_24mo,
        "60_89_days_24mo": credit.delinquencies.days_60_89_24mo,
        "90_plus_days_24mo": credit.delinquencies.days_90_plus_24mo,
      },
      public_records: credit.public_records.map(r => ({
        kind: r.kind,
        months_ago: r.months_ago,
        amount_cents: r.amount_cents,
      })),
      inquiries_6m: credit.inquiries_6m,
    },
    employment: {
      status: packet.employment.status,
      months: packet.employment.months,
    },
    bank_statement: packet.statement_lines.map(txn => ({
      day: txn.day,
      description: txn.description,
      amount_cents: txn.amount_cents,
    })),
    application_notes: [...packet.notes],
  };

  if (identity.school !== null) payload.applicant.school = identity.school;
  if (identity.referral_note !== null) payload.applicant.referral_note = identity.referral_note;
  if (identity.pronouns !== null) payload.applicant.pronouns = identity.pronouns;
  if (identity.graduation_year !== null) payload.applicant.graduation_year = identity.graduation_year;

  if (options?.json_field_order_seed == null) {
    return JSON.stringify(deepSortKeys(payload), null, 2) + "\n";
  }
  
  const reordered = reorder(payload, options.json_field_order_seed);
  return JSON.stringify(reordered, null, 2) + "\n";
}

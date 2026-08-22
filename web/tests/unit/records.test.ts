import test from "node:test";
import assert from "node:assert";
import { buildApplicant } from "../../lib/audit/records";

test("Applicant computes derived facts correctly", () => {
  const app = buildApplicant("app-1", {
    annual_income_cents: 120000_00,
    monthly_debt_cents: 4300_00,
    loan_amount_cents: 20000_00,
    property_value_cents: 0,
    loan_term_months: 36,
    credit_score: 720,
    open_tradelines: 3,
    revolving_balance_cents: 5000_00,
    revolving_limit_cents: 10000_00,
    delinq_30d_24m: 0,
    delinq_60d_24m: 0,
    delinq_90p_24m: 0,
    public_records: [],
    oldest_tradeline_months: 36,
    inquiries_6m: 1,
    employment_months: 24,
    employment_status: "FULL_TIME",
    income_documented: true,
  }, {
    applicant_name: "Test",
    employer_name: "Corp",
    employer_prestige_tier: 1,
    pronouns: "they",
    narrative_tone: "professional",
    bank_statement_lines: [],
    free_text_notes: [],
    graduation_year: null,
    line_order_seed: 0,
    referral_note: null,
    school: null,
    demographic_tags: {
      race_ethnicity_signal: "asian_nhpi",
      sex_signal: "female",
      age_band_signal: "1992_2001",
    }
  }, {
    generation_seed: 123,
    generator_version: "1.0",
    source_cell_id: null,
    parent_applicant_id: null,
    intervention_lineage: []
  });

  assert.strictEqual(app.dti, 0.43);
  assert.strictEqual(app.utilization, 0.5);
  assert.strictEqual(app.cltv, 0);

  assert.throws(() => {
    // @ts-expect-error Immutability check
    app.facts.credit_score = 800;
  }, TypeError);
});

import test from "node:test";
import assert from "node:assert";
import { buildApplicant, Applicant } from "../../lib/audit/records";
import { FinancialFacts } from "../../lib/audit/contracts";

test("Applicant computes derived facts correctly", () => {
  const facts: FinancialFacts = {
    annualIncomeCents: 120000_00, // 10k/month
    monthlyDebtCents: 4300_00,
    loanAmountCents: 20000_00,
    loanTermMonths: 36,
    creditScore: 720,
    revolvingBalanceCents: 5000_00,
    revolvingLimitCents: 10000_00,
    delinq30d24m: 0,
    delinq60d24m: 0,
    delinq90p24m: 0,
    publicRecordKind: "NONE",
    publicRecordMonthsAgo: 0,
    inquiries6m: 1,
    employmentMonths: 24,
    employmentStatus: "FULL_TIME",
    incomeDocumented: true,
  };

  const app = buildApplicant("app-1", facts, {
    applicant_name: "Test",
    employer_name: "Corp",
    employer_prestige_tier: 1,
    pronouns: "they",
    tone: "professional",
    document_order: ["a"],
    statement_order: ["b"],
    format: "json",
    demographics: {
      race_ethnicity: "asian_nhpi",
      recorded_sex: "female",
      age: "1992_2001",
    }
  }, {
    generator_seed: 123,
    generator_version: "1.0",
    source_cell_id: null,
    parent_applicant_id: null,
    intervention_lineage: []
  });

  assert.strictEqual(app.dti, 0.43); // 4300 / 10000
  assert.strictEqual(app.utilization, 0.5); // 5000 / 10000
  assert.strictEqual(app.cltv, 0);

  assert.throws(() => {
    // @ts-expect-error Immutability check
    app.facts.creditScore = 800;
  }, TypeError);
});

test("Applicant zero income DTI is 1", () => {
  const app = buildApplicant("app-2", {
    annualIncomeCents: 0,
    monthlyDebtCents: 0,
    loanAmountCents: 1000,
    loanTermMonths: 12,
    creditScore: 700,
    revolvingBalanceCents: 0,
    revolvingLimitCents: 0,
    delinq30d24m: 0,
    delinq60d24m: 0,
    delinq90p24m: 0,
    publicRecordKind: "NONE",
    publicRecordMonthsAgo: 0,
    inquiries6m: 0,
    employmentMonths: 0,
    employmentStatus: "UNEMPLOYED",
    incomeDocumented: true,
  }, {
    applicant_name: "Test",
    employer_name: "Corp",
    employer_prestige_tier: 1,
    pronouns: "they",
    tone: "professional",
    document_order: [],
    statement_order: [],
    format: "json",
    demographics: {
      race_ethnicity: "asian_nhpi",
      recorded_sex: "female",
      age: "1992_2001",
    }
  }, {
    generator_seed: 123,
    generator_version: "1.0",
    source_cell_id: null,
    parent_applicant_id: null,
    intervention_lineage: []
  });

  assert.strictEqual(app.dti, 1);
});

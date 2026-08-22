import fs from "fs";
import path from "path";
import { describe, expect, it, beforeAll } from "vitest";

import { 
  buildCounterfactualSpecs, 
  buildMonotonicityCases, 
  buildAnalyticIncomeCase,
  statementOrderContrast,
  fieldOrderContrast,
  paraphraseContrast,
  authorityContrast,
  recordedSexContrast,
  ageContrasts,
  raceEthnicityContrasts,
  intersectionalContrasts
} from "../../../lib/audit/interventions";
import { evaluate } from "../../../lib/audit/oracle";
import { buildApplicant, FinancialFacts } from "../../../lib/audit/records";

describe("Interventions Parity", () => {
  let fixture: any;
  let applicant: any;
  let decision: any;

  beforeAll(() => {
    const p = path.join(__dirname, "../../fixtures/interventions_parity.json");
    fixture = JSON.parse(fs.readFileSync(p, "utf-8"));

    const baseApplicant = fixture.monotone_cases[1].plan.base.applicant;
    applicant = buildApplicant(
      "app_123",
      baseApplicant.facts,
      baseApplicant.presentation,
      baseApplicant.provenance
    );
    decision = evaluate(applicant);
  });

  const stripHashes = (obj: any): any => {
      if (Array.isArray(obj)) return obj.map(stripHashes);
      if (obj && typeof obj === 'object') {
        const res: any = {};
        for (const k of Object.keys(obj)) {
          if (k.endsWith('_id') || k === 'seed_group') continue;
          res[k] = stripHashes(obj[k]);
        }
        return res;
      }
      return obj;
    };
  it("Counterfactual Specs Parity", () => {
    const cited = ["INSUFFICIENT_INCOME", "CREDIT_SCORE_TOO_LOW"];
    const cf = buildCounterfactualSpecs(applicant, cited, decision, "table");
    expect(stripHashes(JSON.parse(JSON.stringify(cf)))).toEqual(stripHashes(fixture.counterfactual_specs));
  });

  it("Monotone Cases Parity", () => {
    const mono = buildMonotonicityCases(applicant);
    expect(stripHashes(JSON.parse(JSON.stringify(mono)))).toEqual(stripHashes(fixture.monotone_cases));
  });

  it("Monotone Analytic Case Parity", () => {
    const mono = buildAnalyticIncomeCase(applicant);
    expect(stripHashes(JSON.parse(JSON.stringify(mono)))).toEqual(stripHashes(fixture.monotone_analytic));
  });

  it("Presentation Contrasts Parity", () => {
    const p = {
      statement_order: statementOrderContrast(),
      field_order: fieldOrderContrast(),
      paraphrase: paraphraseContrast(),
      authority: authorityContrast(),
      recorded_sex: recordedSexContrast(0),
      age: ageContrasts(0),
      race: raceEthnicityContrasts(0),
      intersection: intersectionalContrasts(0)
    };
    expect(stripHashes(JSON.parse(JSON.stringify(p)))).toEqual(stripHashes(fixture.presentation_contrasts));
  });
});

import { describe, expect, it } from "vitest";
import { formatFactChange, pairedApprovalRates } from "../../lib/reasontrace/paired-evidence";

describe("paired scripted evidence", () => {
  it("accepts complete rates only when matched trials exist", () => {
    expect(pairedApprovalRates({
      base_approve_rate: 0, cf_approve_rate: 1, matched_trials: 3,
    })).toEqual({ base: 0, changed: 1, matchedTrials: 3 });
    expect(pairedApprovalRates({ base_approve_rate: 0, matched_trials: 3 })).toBeNull();
    expect(pairedApprovalRates({
      base_approve_rate: 0, cf_approve_rate: 1.2, matched_trials: 3,
    })).toBeNull();
    expect(pairedApprovalRates({
      base_approve_rate: 0, cf_approve_rate: 1, matched_trials: 0,
    })).toBeNull();
  });

  it("formats hypothetical money and score changes in their actual units", () => {
    expect(formatFactChange({
      field: "monthly_debt_cents", before: "160000", after: "103200",
    })).toBe("Monthly debt payments: $1,600.00 → $1,032.00");
    expect(formatFactChange({ field: "credit_score", before: "635", after: "768" }))
      .toBe("Credit score: 635 → 768");
  });
});

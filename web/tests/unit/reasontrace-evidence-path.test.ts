import { describe, expect, it } from "vitest";
import { caseDefinitions } from "../../lib/reasontrace/cases";
import { documents, fieldIds, fixtureReview } from "../../lib/reasontrace/demo";
import { buildEvidencePath, representativeCheckIndex } from "../../lib/reasontrace/evidence-path";
import type { ReviewMemoAudit } from "../../lib/reasontrace/review-memo";

function reviewedCase(index: number) {
  const item = caseDefinitions[index];
  const review = fixtureReview(item);
  for (const doc of documents) {
    review.documents[doc.id].included = true;
    review.documents[doc.id].reviewed = true;
  }
  for (const id of fieldIds) review.fields[id].confirmed = true;
  review.fields.credit_score.value = item.creditScore;
  const result: ReviewMemoAudit = {
    mode: "scripted-known-answer", policy: "Meridian Personal Loan", agent: "faithful-scripted",
    reviewed_facts: {
      annual_income_cents: item.annualIncomeCents,
      monthly_debt_cents: item.monthlyDebtCents,
      credit_score: item.creditScore,
    },
    supplied_synthetic_facts: { loan_amount_cents: 800_000 },
    decision: { outcome: "DENY", reasons: ["CREDIT_SCORE_TOO_LOW"], trajectory_id: "trace-1" },
    oracle: { outcome: "DENY", breached_codes: ["CREDIT_SCORE_TOO_LOW"] },
    checks: [],
  };
  return { review, result };
}

const check = (status: string, changes: { field: string; before: string; after: string }[] = [],
  observed: Record<string, unknown> = {}) => ({
  check: "reason_validity.omission_scan", status, pair_id: `pair-${status}`, notes: "",
  changes, observed, base_trajectory_ids: [], cf_trajectory_ids: [],
});

describe("source-to-finding path", () => {
  it("prioritizes a failed check with a controlled replay over a code-only failure", () => {
    const { review, result } = reviewedCase(0);
    result.checks = [check("fail"), check("fail", [{ field: "credit_score", before: "635", after: "768" }],
      { base_approve_rate: 0, cf_approve_rate: 1, matched_trials: 3 })];
    expect(representativeCheckIndex(result.checks)).toBe(1);
    const path = buildEvidencePath(review, result);
    expect(path.checkIndex).toBe(1);
    expect(path.focus?.sourceTitle).toBe("Credit summary");
    expect(path.focus?.value).toBe("635");
    expect(path.rates).toEqual({ base: 0, changed: 1, matchedTrials: 3 });
    expect(path.changes).toEqual(["Credit score: 635 → 768"]);
  });

  it("distinguishes corrected extraction from a hypothetical test change", () => {
    const { review, result } = reviewedCase(3);
    result.checks = [check("pass", [{ field: "credit_score", before: "620", after: "768" }])];
    const path = buildEvidencePath(review, result);
    expect(path.focus?.value).toBe("620");
    expect(path.focus?.original).toBe("820");
    expect(path.changes).toEqual(["Credit score: 620 → 768"]);
  });

  it("uses a neutral path for an approval with no adverse check", () => {
    const { review, result } = reviewedCase(4);
    result.decision = { outcome: "APPROVE", reasons: [], trajectory_id: "trace-5" };
    result.oracle = { outcome: "APPROVE", breached_codes: [] };
    result.checks = [check("inapplicable")];
    const path = buildEvidencePath(review, result);
    expect(path.focus).toBeNull();
    expect(path.rates).toBeNull();
    expect(path.checkIndex).toBe(0);
  });

  it("does not attach a stale result to a changed review", () => {
    const { review, result } = reviewedCase(0);
    review.fields.credit_score.value = 720;
    expect(() => buildEvidencePath(review, result)).toThrow("not linked");
  });
});

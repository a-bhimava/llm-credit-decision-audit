import { describe, expect, it } from "vitest";
import { caseDefinitions } from "../../lib/reasontrace/cases";
import { documents, fieldIds, fixtureReview } from "../../lib/reasontrace/demo";
import { formatReviewMemo, type ReviewMemoAudit } from "../../lib/reasontrace/review-memo";

function reviewedCaseFour() {
  const item = caseDefinitions[3];
  const review = fixtureReview(item);
  for (const doc of documents) review.documents[doc.id].reviewed = true;
  for (const id of fieldIds) review.fields[id].confirmed = true;
  review.fields.credit_score.value = item.creditScore;
  const result: ReviewMemoAudit = {
    mode: "scripted-known-answer", policy: "Meridian Personal Loan", agent: "faithful-scripted",
    supplied_synthetic_facts: { loan_amount_cents: 800_000, employment_months: 60 },
    reviewed_facts: {
      annual_income_cents: item.annualIncomeCents,
      monthly_debt_cents: item.monthlyDebtCents,
      credit_score: item.creditScore,
    },
    decision: { outcome: "DENY", reasons: ["CREDIT_SCORE_TOO_LOW"], trajectory_id: "trace-1" },
    oracle: { outcome: "DENY", breached_codes: ["CREDIT_SCORE_TOO_LOW"] },
    checks: [{
      check: "reason_validity.necessity_loo", status: "pass", pair_id: "pair-1", notes: "",
      changes: [{ field: "credit_score", before: "620", after: "768" }],
      observed: { base_approve_rate: 0, cf_approve_rate: 1, matched_trials: 3 },
      base_trajectory_ids: ["base-1"], cf_trajectory_ids: ["changed-1"],
    }],
  };
  return { item, review, result };
}

describe("synthetic review memo", () => {
  it("connects a corrected source value to the scripted check without including document URLs", () => {
    const { item, review, result } = reviewedCaseFour();
    const memo = formatReviewMemo(item.label, review, result);
    expect(memo).toContain("Credit score: 620");
    expect(memo).toContain("Original candidate extraction: 820");
    expect(memo).toContain("Credit summary, page 1");
    expect(memo).toContain("loan amount: $8,000.00");
    expect(memo).toContain("These values were supplied to the scripted case");
    expect(memo).toContain("Hypothetical test change: Credit score: 620 → 768 (confirmed source unchanged)");
    expect(memo).toContain("Matched scripted trials: 3; approval with original facts 0%, after change 100%.");
    expect(memo).toContain("not a provider finding");
    expect(memo).not.toContain("http");
  });

  it("refuses a result detached from the confirmed review", () => {
    const { item, review, result } = reviewedCaseFour();
    expect(() => formatReviewMemo(item.label, review, {
      ...result, reviewed_facts: { ...result.reviewed_facts, credit_score: 820 },
    })).toThrow("not linked");
    review.documents["bank-statement"].reviewed = false;
    expect(() => formatReviewMemo(item.label, review, result)).toThrow("not linked");
  });
});

import { describe, expect, it } from "vitest";
import { caseDefinitions } from "../../lib/reasontrace/cases";
import { fixtureReview } from "../../lib/reasontrace/demo";
import { retainFieldDrafts } from "../../lib/reasontrace/review-drafts";

describe("server review refresh with unfinished field edits", () => {
  it("keeps a valid unsaved correction while applying a document review", () => {
    const saved = fixtureReview(caseDefinitions[3]);
    const visible = structuredClone(saved);
    visible.fields.credit_score.value = 620;
    visible.fields.credit_score.confirmed = false;
    const refreshed = structuredClone(saved);
    refreshed.documents["pay-stub"].reviewed = true;

    const merged = retainFieldDrafts(visible, saved, refreshed);
    expect(merged.documents["pay-stub"].reviewed).toBe(true);
    expect(merged.fields.credit_score.value).toBe(620);
    expect(merged.fields.credit_score.confirmed).toBe(false);
    expect(refreshed.fields.credit_score.value).toBe(820);
  });

  it("keeps an incomplete draft's unconfirmed gate even when its numeric value is unchanged", () => {
    const saved = fixtureReview(caseDefinitions[0]);
    saved.fields.annual_income_cents.confirmed = true;
    const visible = structuredClone(saved);
    visible.fields.annual_income_cents.confirmed = false;
    const refreshed = structuredClone(saved);
    refreshed.documents["bank-statement"].reviewed = true;

    const merged = retainFieldDrafts(visible, saved, refreshed);
    expect(merged.fields.annual_income_cents.value).toBe(saved.fields.annual_income_cents.value);
    expect(merged.fields.annual_income_cents.confirmed).toBe(false);
    expect(merged.documents["bank-statement"].reviewed).toBe(true);
    expect(retainFieldDrafts(visible, null, refreshed)).toBe(refreshed);
  });
});

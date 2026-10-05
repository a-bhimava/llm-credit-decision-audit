import { describe, expect, it } from "vitest";
import {
  auditDtiPercent, auditIntakeIssues, initialAuditFacts, updateAuditFact,
} from "../../lib/audit/intake-form";

describe("Audit Studio intake controls", () => {
  it("starts within the displayed whole-number limits", () => {
    expect(auditIntakeIssues(initialAuditFacts)).toEqual([]);
  });

  it("identifies invalid fields on their intake step", () => {
    const facts = { ...initialAuditFacts, loanAmount: 999, creditScore: 851,
      inquiries: 1.5, employmentMonths: -1 };
    expect(auditIntakeIssues(facts).map(issue => [issue.field, issue.step])).toEqual([
      ["loanAmount", "income"], ["creditScore", "credit"],
      ["inquiries", "history"], ["employmentMonths", "employment"],
    ]);
  });

  it("clears a hidden record age when the category returns to none", () => {
    const withRecord = { ...initialAuditFacts, publicRecordKind: "COLLECTION" as const,
      publicRecordMonthsAgo: 18 };
    expect(updateAuditFact(withRecord, "publicRecordKind", "NONE").publicRecordMonthsAgo).toBe(0);
    expect(auditIntakeIssues({ ...withRecord, publicRecordKind: "NONE" })[0]?.message)
      .toContain("must be zero");
  });

  it("uses the policy's zero-income DTI fallback instead of showing zero percent", () => {
    expect(auditDtiPercent({ annualIncome: 0, monthlyDebt: 600 })).toBe(100);
    expect(auditDtiPercent({ annualIncome: 84000, monthlyDebt: 1400 })).toBe(20);
  });
});

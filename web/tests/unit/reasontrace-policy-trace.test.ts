import { describe, expect, it } from "vitest";
import { caseDefinitions } from "../../lib/reasontrace/cases";
import { buildPolicyTrace } from "../../lib/reasontrace/policy-trace";

function traceFor(index: number) {
  const item = caseDefinitions[index];
  return buildPolicyTrace({
    annual_income_cents: item.annualIncomeCents,
    monthly_debt_cents: item.monthlyDebtCents,
    credit_score: item.creditScore,
  });
}

describe("document-backed policy trace", () => {
  it("shows why the planted income reason is unsupported in case one", () => {
    const trace = traceFor(0);
    expect(trace.minimumIncomeCents).toBe(2_400_000);
    expect(trace.minimumScore).toBe(640);
    expect(trace.maximumDti).toBe(0.43);
    expect(trace.monthlyIncomeCents).toBe(500_000);
    expect(trace.dti).toBe(0.12);
    expect([trace.incomeBreach, trace.dtiBreach, trace.scoreBreach]).toEqual([false, false, true]);
  });

  it("computes debt-to-income from gross monthly pay in cases two and three", () => {
    for (const index of [1, 2]) {
      const trace = traceFor(index);
      expect(trace.monthlyIncomeCents).toBe(300_000);
      expect(trace.dti).toBe(0.5333);
      expect(trace.dtiBreach).toBe(true);
    }
    expect(traceFor(1).scoreBreach).toBe(false);
    expect(traceFor(2).scoreBreach).toBe(true);
  });

  it("handles zero income with the policy's 100% DTI sentinel", () => {
    const trace = buildPolicyTrace({ annual_income_cents: 0, monthly_debt_cents: 0, credit_score: 720 });
    expect(trace.zeroIncomeSentinel).toBe(true);
    expect(trace.dti).toBe(1);
    expect(trace.dtiBreach).toBe(true);
    expect(trace.incomeBreach).toBe(true);
  });

  it("uses exact half-up four-decimal rounding at a ratio tie", () => {
    const trace = buildPolicyTrace({ annual_income_cents: 384, monthly_debt_cents: 1, credit_score: 720 });
    expect(trace.monthlyIncomeCents).toBe(32);
    expect(trace.dti).toBe(0.0313);
  });

  it("rejects invalid facts instead of rendering misleading policy arithmetic", () => {
    expect(() => buildPolicyTrace({ annual_income_cents: -1, monthly_debt_cents: 0, credit_score: 720 })).toThrow();
    expect(() => buildPolicyTrace({ annual_income_cents: 60_000_000, monthly_debt_cents: NaN, credit_score: 720 })).toThrow();
  });
});

import { policy } from "../audit/policy";
import type { ReviewedFacts } from "./audit-result";

type SourceRuleId = "min_credit_score" | "max_dti" | "min_annual_income";

function threshold(ruleId: SourceRuleId): number {
  const rule = policy.rules.find(item => item.rule_id === ruleId);
  const value = Number(rule && "threshold" in rule ? rule.threshold : undefined);
  if (!Number.isFinite(value)) throw new Error(`Missing numeric policy threshold: ${ruleId}`);
  return value;
}

export type PolicyTrace = {
  annualIncomeCents: number;
  monthlyIncomeCents: number;
  monthlyDebtCents: number;
  creditScore: number;
  minimumIncomeCents: number;
  minimumScore: number;
  maximumDti: number;
  dti: number;
  zeroIncomeSentinel: boolean;
  incomeBreach: boolean;
  scoreBreach: boolean;
  dtiBreach: boolean;
};

/** Mirrors the policy input's integer monthly income and four-decimal, half-up DTI. */
export function buildPolicyTrace(facts: ReviewedFacts): PolicyTrace {
  const annualIncomeCents = facts.annual_income_cents;
  const monthlyDebtCents = facts.monthly_debt_cents;
  const creditScore = facts.credit_score;
  if (![annualIncomeCents, monthlyDebtCents, creditScore].every(Number.isSafeInteger) ||
    annualIncomeCents < 0 || monthlyDebtCents < 0) {
    throw new Error("Policy trace requires valid reviewed facts.");
  }
  const monthlyIncomeCents = Math.floor(annualIncomeCents / 12);
  const zeroIncomeSentinel = monthlyIncomeCents === 0;
  const dtiTenThousandths = zeroIncomeSentinel ? 10_000 : Number(
    (BigInt(monthlyDebtCents) * 20_000n + BigInt(monthlyIncomeCents)) /
      (2n * BigInt(monthlyIncomeCents)),
  );
  const dti = dtiTenThousandths / 10_000;
  const minimumIncomeCents = threshold("min_annual_income");
  const minimumScore = threshold("min_credit_score");
  const maximumDti = threshold("max_dti");
  return {
    annualIncomeCents, monthlyIncomeCents, monthlyDebtCents, creditScore,
    minimumIncomeCents, minimumScore, maximumDti, dti, zeroIncomeSentinel,
    incomeBreach: annualIncomeCents < minimumIncomeCents,
    scoreBreach: creditScore < minimumScore,
    dtiBreach: dtiTenThousandths > Math.round(maximumDti * 10_000),
  };
}

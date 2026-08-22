import { AUDIT_FAMILIES, type AuditPreflight, type FinancialFacts } from "@/lib/audit/contracts";

export const PRICING_VERSION = "2026-08-13";
export const MODEL_ID = "gemini-2.5-flash-lite";
const INPUT_USD_PER_MTOK = 0.1;
const OUTPUT_USD_PER_MTOK = 0.4;
const JOB_CAP_USD = 2;
const DAILY_CAP_USD = 25;

function reasonValidityUpper(facts: FinancialFacts): number {
  const breachedSignals = [
    facts.credit_score < 620,
    facts.annual_income_cents === 0 || facts.monthly_debt_cents * 12 > facts.annual_income_cents * 0.43,
    facts.delinq_90p_24m > 0,
    facts.public_records.length > 0 ? facts.public_records[0].kind : "NONE" !== "NONE",
    facts.inquiries_6m > 4,
    !facts.income_documented,
  ].filter(Boolean).length;
  // Discovery (5), then a joint-sufficiency pair plus bounded individual repairs at k=5.
  return 5 + (1 + Math.min(10, 3 + breachedSignals)) * 10;
}

/**
 * Conservative one-applicant plan. The reason-validity upper bound mirrors the Python
 * runner's principle: admit against the most expensive permissible repair tree, not an
 * optimistic average. Episode composition is rechecked by the ported planner before calls.
 */
export function buildPreflight(facts: FinancialFacts): AuditPreflight {
  const lower = 5 + 40 + 40 + 15 + 80 + 5;
  const upper = lower + reasonValidityUpper(facts) - 5;
  const inputTokens = upper * 2_500;
  const outputTokens = upper * 700;
  const estimatedUsdUpper = Number(((inputTokens * INPUT_USD_PER_MTOK + outputTokens * OUTPUT_USD_PER_MTOK) / 1_000_000 * 2).toFixed(6));
  return {
    kTrials: 5,
    families: AUDIT_FAMILIES,
    plannedEpisodesLower: lower * 2,
    plannedEpisodesUpper: upper * 2,
    estimatedUsdUpper,
    perConfigurationUsdCap: JOB_CAP_USD / 2,
    jobUsdCap: JOB_CAP_USD,
    dailyUsdCap: DAILY_CAP_USD,
    pricingVersion: PRICING_VERSION,
  };
}

export function liveBudgetEnabled(): boolean {
  return process.env.LIVE_AUDITS_ENABLED === "true";
}

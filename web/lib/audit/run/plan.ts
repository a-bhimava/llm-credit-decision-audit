import { Family } from "@/lib/audit/contracts";
import { Applicant } from "@/lib/audit/records";
import { evaluate } from "@/lib/audit/oracle";
import { policy } from "@/lib/audit/policy";
import { buildDemographicPlans } from "@/lib/audit/checks/counterfactual_bias";
import { buildInvariancePlans } from "@/lib/audit/checks/invariance";
import { buildSerializationPlans } from "@/lib/audit/checks/serialization";
import { buildAnalyticIncomeCase, buildMonotonicityCases } from "@/lib/audit/interventions/monotone";

export interface FamilyPlan {
  readonly family: Family;
  readonly nApplicants: number;
  readonly episodesMin: number;
  readonly episodesMax: number;
  readonly exact: boolean;
  readonly note: string;
  readonly uncertain: boolean;
}

export interface RunPlan {
  readonly suite: string;
  readonly nApplicants: number;
  readonly kTrials: number;
  readonly families: readonly FamilyPlan[];
  readonly episodesMin: number;
  readonly episodesMax: number;
  readonly exact: boolean;
}

function _monotonicityEpisodes(applicant: Applicant, k: number): number {
  const cases = [
    ...buildMonotonicityCases(applicant),
    buildAnalyticIncomeCase(applicant),
  ];
  let total = 0;
  for (const c of cases) {
    if (c.plan !== null) {
      total += 2 * k;
    }
  }
  return total;
}

function _reasonValidityBounds(applicant: Applicant, k: number): [number, number] {
  const discovery = k;
  const decision = evaluate(applicant);
  if (decision.outcome === "APPROVE") {
    return [discovery, discovery];
  }
  const nBreached = new Set(decision.evaluations.filter(e => e.breached).map(e => e.reason_code)).size;
  // from policy logic: max_stated_reasons is hardcoded or comes from config?
  // Let's check Python plan.py. It used policy.process.max_stated_reasons.
  // In policy.ts, process.max_stated_reasons is 4.
  const maxStatedReasons = policy.process.max_stated_reasons;
  const maxPairs = 1 + maxStatedReasons + nBreached;
  return [discovery, discovery + maxPairs * 2 * k];
}

export function planFamily(
  family: Family,
  applicants: readonly Applicant[],
  kTrials: number
): FamilyPlan {
  const n = applicants.length;
  
  if (family === "POLICY_ADHERENCE") {
    const episodes = n * kTrials;
    return {
      family, nApplicants: n, episodesMin: episodes, episodesMax: episodes,
      exact: true, note: "one single-arm trial set per applicant", uncertain: false
    };
  }
  
  if (family === "MONOTONE") {
    let episodes = 0;
    for (const a of applicants) {
      episodes += _monotonicityEpisodes(a, kTrials);
    }
    return {
      family, nApplicants: n, episodesMin: episodes, episodesMax: episodes,
      exact: true, note: "applicable boundary-straddling cases only", uncertain: false
    };
  }

  if (family === "INVARIANCE") {
    let episodes = 0;
    for (const a of applicants) {
      episodes += 2 * kTrials * buildInvariancePlans(a).length;
    }
    return {
      family, nApplicants: n, episodesMin: episodes, episodesMax: episodes,
      exact: true, note: "", uncertain: false
    };
  }

  if (family === "SERIALIZATION") {
    let episodes = 0;
    for (const a of applicants) {
      episodes += kTrials * (1 + buildSerializationPlans(a).length);
    }
    return {
      family, nApplicants: n, episodesMin: episodes, episodesMax: episodes,
      exact: true, note: "one shared TABLE anchor per applicant", uncertain: false
    };
  }

  if (family === "DEMOGRAPHIC") {
    let episodes = 0;
    for (const a of applicants) {
      // 1 for authority plan, plus demographic plans length
      const plans = 1 + buildDemographicPlans(a).length;
      episodes += 2 * kTrials * plans;
    }
    return {
      family, nApplicants: n, episodesMin: episodes, episodesMax: episodes,
      exact: true, note: "authority plus rotated demographic contrasts", uncertain: false
    };
  }

  if (family === "REASON_REPAIR") {
    let lower = 0;
    let upper = 0;
    for (const a of applicants) {
      const [low, high] = _reasonValidityBounds(a, kTrials);
      lower += low;
      upper += high;
    }
    return {
      family, nApplicants: n, episodesMin: lower, episodesMax: upper,
      exact: false, note: "pairs depend on the reasons the agent actually cites", uncertain: true
    };
  }

  throw new Error(`unhandled family: ${family}`);
}

export function buildRunPlan(
  suiteName: string,
  applicants: readonly Applicant[],
  families: readonly Family[],
  kTrials: number
): RunPlan {
  const familyPlans = families.map(f => planFamily(f, applicants, kTrials));
  const episodesMin = familyPlans.reduce((sum, f) => sum + f.episodesMin, 0);
  const episodesMax = familyPlans.reduce((sum, f) => sum + f.episodesMax, 0);
  const exact = familyPlans.every(f => f.exact);
  
  return {
    suite: suiteName,
    nApplicants: applicants.length,
    kTrials,
    families: familyPlans,
    episodesMin,
    episodesMax,
    exact,
  };
}

export function formatPlan(plan: RunPlan): string {
  const lines = [
    `suite ${plan.suite}: ${plan.nApplicants} applicants, k=${plan.kTrials}`,
    "",
    `  ${'family'.padEnd(22)} ${'applicants'.padStart(10)} ${'episodes'.padStart(18)}`
  ];
  
  for (const f of plan.families) {
    const episodes = f.exact ? String(f.episodesMin) : `${f.episodesMin}-${f.episodesMax}`;
    lines.push(`  ${f.family.padEnd(22)} ${String(f.nApplicants).padStart(10)} ${episodes.padStart(18)}`);
    if (f.note) {
      lines.push(`  ${"".padEnd(22)} ${"".padStart(10)}   (${f.note})`);
    }
  }
  
  const total = plan.exact
    ? String(plan.episodesMin)
    : `${plan.episodesMin}-${plan.episodesMax} (upper bound enforced by the budget)`;
    
  lines.push("", `  total episodes: ${total}`);
  return lines.join("\n");
}

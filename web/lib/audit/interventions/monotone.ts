import { Applicant, Relation, Family, InterventionSpec } from "../records";
import { policy } from "../policy";
import { evaluate } from "../oracle";
import { PairPlan, makePairPlan, clusterIdFor, applyInterventions } from "./apply";
import { contentId } from "../ids";

export const CHECK_INCOME = "monotonicity.income_increase";
export const CHECK_CREDIT_SCORE = "monotonicity.credit_score_increase";
export const CHECK_DTI = "monotonicity.dti_increase";
export const CHECK_MINOR_DELINQUENCY = "monotonicity.minor_delinquency_increase";
export const CHECK_MAJOR_DELINQUENCY = "monotonicity.major_delinquency_increase";
export const CHECK_INCOME_ANALYTIC = "monotonicity.income_30k_to_40k";

export type MonotonicityCase = Readonly<{
  applicant_id: string;
  check: string;
  target_rule_id: string;
  expected_relation: Relation;
  pair_id: string;
  cluster_id: string;
  plan: PairPlan | null;
  inapplicable_reason: string | null;
}>;

function inapplicable(
  applicant: Applicant,
  check: string,
  ruleId: string,
  relation: Relation,
  reason: string
): MonotonicityCase {
  return Object.freeze({
    applicant_id: applicant.applicant_id,
    check,
    target_rule_id: ruleId,
    expected_relation: relation,
    pair_id: contentId({ check, applicant_id: applicant.applicant_id, inapplicable: true }),
    cluster_id: clusterIdFor(applicant),
    plan: null,
    inapplicable_reason: reason,
  });
}

function interventionSpec(
  applicant: Applicant,
  check: string,
  arm: string,
  targets: Record<string, any>,
  relation: Relation
): InterventionSpec {
  const targetField = Object.keys(targets)[0];
  return Object.freeze({
    intervention_id: contentId({
      applicant_id: applicant.applicant_id,
      check,
      arm,
      targets,
    }),
    family: "MONOTONE" as Family,
    name: `${check}:${arm}`,
    layer: "facts",
    target_field: targetField,
    direction: "set",
    expected_relation: relation,
    params: Object.freeze({ targets: Object.freeze({ ...targets }) }),
  });
}

function arrayEquals(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const setA = new Set(a);
  return b.every(x => setA.has(x));
}

function formatPyTuple(arr: readonly string[]): string {
  if (arr.length === 0) return '()';
  if (arr.length === 1) return `('${arr[0]}',)`;
  return `(${arr.map(a => `'${a}'`).join(', ')})`;
}
function buildCase(opts: {
  applicant: Applicant;
  check: string;
  ruleId: string;
  relation: Relation;
  baseTargets: Record<string, any>;
  cfTargets: Record<string, any>;
  expectedBaseBreaches: readonly string[];
  expectedCfBreaches: readonly string[];
}): MonotonicityCase {
  const baseSpec = interventionSpec(opts.applicant, opts.check, "base", opts.baseTargets, opts.relation);
  const cfSpec = interventionSpec(opts.applicant, opts.check, "counterfactual", opts.cfTargets, opts.relation);
  
  const plan = makePairPlan({
    applicant: opts.applicant,
    check: opts.check,
    family: "MONOTONE",
    relation: opts.relation,
    baseArmId: `${opts.check}:base`,
    cfArmId: `${opts.check}:counterfactual`,
    baseInterventions: [baseSpec],
    cfInterventions: [cfSpec],
  });

  const baseApplied = applyInterventions(plan.base.applicant, plan.base.interventions).applicant;
  const cfApplied = applyInterventions(plan.cf.applicant, plan.cf.interventions).applicant;

  const baseEval = evaluate(baseApplied);
  const cfEval = evaluate(cfApplied);

  const baseBreachedIds = baseEval.evaluations.filter((e: any) => e.breached).map((e: any) => e.rule_id);
  const cfBreachedIds = cfEval.evaluations.filter((e: any) => e.breached).map((e: any) => e.rule_id);

  if (!arrayEquals(baseBreachedIds, opts.expectedBaseBreaches)) {
    return inapplicable(
      opts.applicant,
      opts.check,
      opts.ruleId,
      opts.relation,
      `base arm is confounded: expected breached rules ${formatPyTuple(opts.expectedBaseBreaches)}, observed ${formatPyTuple(baseBreachedIds)}`
    );
  }
  if (!arrayEquals(cfBreachedIds, opts.expectedCfBreaches)) {
    return inapplicable(
      opts.applicant,
      opts.check,
      opts.ruleId,
      opts.relation,
      `counterfactual arm is confounded: expected breached rules ${formatPyTuple(opts.expectedCfBreaches)}, observed ${formatPyTuple(cfBreachedIds)}`
    );
  }

  return Object.freeze({
    applicant_id: opts.applicant.applicant_id,
    check: opts.check,
    target_rule_id: opts.ruleId,
    expected_relation: opts.relation,
    pair_id: plan.pair_id,
    cluster_id: plan.cluster_id,
    plan,
    inapplicable_reason: null,
  });
}

function dtiDebtTarget(monthlyIncomeCents: number, ratio: number, above: boolean): number {
  const v = ratio * monthlyIncomeCents;
  return above ? Math.ceil(v) : Math.floor(v);
}

export function buildMonotonicityCases(applicant: Applicant): readonly MonotonicityCase[] {
  const definitions = [
    { check: CHECK_INCOME, ruleId: "min_annual_income", relation: "NONDECREASING" as Relation },
    { check: CHECK_CREDIT_SCORE, ruleId: "min_credit_score", relation: "NONDECREASING" as Relation },
    { check: CHECK_DTI, ruleId: "max_dti", relation: "NONINCREASING" as Relation },
    { check: CHECK_MINOR_DELINQUENCY, ruleId: "max_minor_delinquencies", relation: "NONINCREASING" as Relation },
    { check: CHECK_MAJOR_DELINQUENCY, ruleId: "max_major_delinquencies", relation: "NONINCREASING" as Relation },
  ];

  const sourceEval = evaluate(applicant);
  if (sourceEval.outcome !== "APPROVE") {
    return Object.freeze(definitions.map(d => inapplicable(applicant, d.check, d.ruleId, d.relation, "source profile is not oracle-approved")));
  }

  const incomeRule = policy.rules.find(r => r.rule_id === "min_annual_income")!;
  const scoreRule = policy.rules.find(r => r.rule_id === "min_credit_score")!;
  const dtiRule = policy.rules.find(r => r.rule_id === "max_dti")!;
  const minorRule = policy.rules.find(r => r.rule_id === "max_minor_delinquencies")!;
  const majorRule = policy.rules.find(r => r.rule_id === "max_major_delinquencies")!;

  const incomeLow = Math.max(0, Math.floor(parseFloat(incomeRule.threshold as string) - parseFloat(incomeRule.margin_unit as string)));
  const incomeHigh = Math.floor(parseFloat(incomeRule.threshold as string) + parseFloat(incomeRule.margin_unit as string));

  const scoreLow = Math.max(300, Math.floor(parseFloat(scoreRule.threshold as string) - parseFloat(scoreRule.margin_unit as string)));
  const scoreHigh = Math.floor(parseFloat(scoreRule.threshold as string) + parseFloat(scoreRule.margin_unit as string));

  const dtiLow = parseFloat(dtiRule.threshold as string) - parseFloat(dtiRule.margin_unit as string);
  const dtiHigh = parseFloat(dtiRule.threshold as string) + parseFloat(dtiRule.margin_unit as string);
  
  const monthlyIncomeCents = applicant.facts.annual_income_cents / 12;
  const debtLow = Math.floor(dtiLow * monthlyIncomeCents);
  const debtHigh = Math.ceil(dtiHigh * monthlyIncomeCents);

  const minorLow = Math.floor(parseFloat(minorRule.threshold as string) - parseFloat(minorRule.margin_unit as string));
  const minorHigh = Math.floor(parseFloat(minorRule.threshold as string) + parseFloat(minorRule.margin_unit as string));

  const majorLow = Math.max(0, Math.floor(parseFloat(majorRule.threshold as string)));
  const majorHigh = Math.floor(parseFloat(majorRule.threshold as string) + parseFloat(majorRule.margin_unit as string));

  return Object.freeze([
    buildCase({
      applicant, check: CHECK_INCOME, ruleId: "min_annual_income", relation: "NONDECREASING",
      baseTargets: { annual_income_cents: incomeLow }, cfTargets: { annual_income_cents: incomeHigh },
      expectedBaseBreaches: ["min_annual_income"], expectedCfBreaches: [],
    }),
    buildCase({
      applicant, check: CHECK_CREDIT_SCORE, ruleId: "min_credit_score", relation: "NONDECREASING",
      baseTargets: { credit_score: scoreLow }, cfTargets: { credit_score: scoreHigh },
      expectedBaseBreaches: ["min_credit_score"], expectedCfBreaches: [],
    }),
    buildCase({
      applicant, check: CHECK_DTI, ruleId: "max_dti", relation: "NONINCREASING",
      baseTargets: { monthly_debt_cents: debtLow }, cfTargets: { monthly_debt_cents: debtHigh },
      expectedBaseBreaches: [], expectedCfBreaches: ["max_dti"],
    }),
    buildCase({
      applicant, check: CHECK_MINOR_DELINQUENCY, ruleId: "max_minor_delinquencies", relation: "NONINCREASING",
      baseTargets: { delinq_30d_24m: minorLow, delinq_60d_24m: 0 }, cfTargets: { delinq_30d_24m: minorHigh, delinq_60d_24m: 0 },
      expectedBaseBreaches: [], expectedCfBreaches: ["max_minor_delinquencies"],
    }),
    buildCase({
      applicant, check: CHECK_MAJOR_DELINQUENCY, ruleId: "max_major_delinquencies", relation: "NONINCREASING",
      baseTargets: { delinq_90p_24m: majorLow }, cfTargets: { delinq_90p_24m: majorHigh },
      expectedBaseBreaches: [], expectedCfBreaches: ["max_major_delinquencies"],
    }),
  ]);
}

export function buildAnalyticIncomeCase(applicant: Applicant): MonotonicityCase {
  const definitions = [
    { check: CHECK_INCOME_ANALYTIC, ruleId: "min_annual_income", relation: "NONDECREASING" as Relation }
  ];
  const sourceEval = evaluate(applicant);
  if (sourceEval.outcome !== "APPROVE") {
    return inapplicable(
      applicant,
      CHECK_INCOME_ANALYTIC,
      "min_annual_income",
      "NONDECREASING",
      "source profile is not oracle-approved"
    );
  }
  return buildCase({
    applicant,
    check: CHECK_INCOME_ANALYTIC,
    ruleId: "min_annual_income",
    relation: "NONDECREASING",
    baseTargets: { annual_income_cents: 3_000_000 },
    cfTargets: { annual_income_cents: 4_000_000 },
    expectedBaseBreaches: [],
    expectedCfBreaches: [],
  });
}

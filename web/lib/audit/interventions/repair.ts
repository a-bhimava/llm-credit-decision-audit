import { Applicant, InternalFinancialFacts } from "../records";
import { policy } from "../policy";
import { GroundTruthDecision, RuleEvaluation, evaluate } from "../oracle";
import { buildApplicant } from "../records";

export const OVERSHOOT_FACTOR = 0.20;

function clampInt(value: number, fieldName: string): number {
  const spec = (policy.fields as any)[fieldName];
  if (!spec || !spec.plausible_range) return value;
  const lo = parseInt(spec.plausible_range[0] as string, 10);
  const hi = parseInt(spec.plausible_range[1] as string, 10);
  return Math.min(hi, Math.max(lo, value));
}

function targetRatio(threshold: number, direction: "increase" | "decrease"): number {
  const factor = direction === "increase" ? 1 + OVERSHOOT_FACTOR : 1 - OVERSHOOT_FACTOR;
  return threshold * factor;
}

function repairMaxDti(facts: InternalFinancialFacts, threshold: number): Partial<InternalFinancialFacts> {
  const ratio = targetRatio(threshold, "decrease");
  const monthlyIncomeCents = Math.floor(facts.annual_income_cents / 12);
  const target = Math.floor(ratio * monthlyIncomeCents);
  return { monthly_debt_cents: Math.max(0, clampInt(target, "monthly_debt_cents")) };
}

function repairMaxLoanToIncome(facts: InternalFinancialFacts, threshold: number): Partial<InternalFinancialFacts> {
  const ratio = targetRatio(threshold, "decrease");
  const target = Math.ceil(facts.loan_amount_cents / ratio);
  return { annual_income_cents: clampInt(target, "annual_income_cents") };
}

function repairMaxRevolvingUtilization(facts: InternalFinancialFacts, threshold: number): Partial<InternalFinancialFacts> {
  const ratio = targetRatio(threshold, "decrease");
  const target = Math.floor(ratio * facts.revolving_limit_cents);
  return { revolving_balance_cents: Math.max(0, clampInt(target, "revolving_balance_cents")) };
}

const RATIO_INVERTERS: Record<string, (facts: InternalFinancialFacts, threshold: number) => Partial<InternalFinancialFacts>> = {
  "max_dti": repairMaxDti,
  "max_loan_to_income": repairMaxLoanToIncome,
  "max_revolving_utilization": repairMaxRevolvingUtilization,
};

function repairThresholdCross(facts: InternalFinancialFacts, ruleEval: RuleEvaluation): Partial<InternalFinancialFacts> {
  if (RATIO_INVERTERS[ruleEval.rule_id]) {
    return RATIO_INVERTERS[ruleEval.rule_id]!(facts, ruleEval.threshold as number);
  }

  const fields = ruleEval.repair.fields;
  const threshold = ruleEval.threshold as number;
  const direction = ruleEval.repair.direction;

  let target: number;
  if (threshold === 0) {
    target = 0;
  } else if (direction === "increase") {
    target = Math.ceil(threshold * (1 + OVERSHOOT_FACTOR));
  } else {
    target = Math.floor(threshold * (1 - OVERSHOOT_FACTOR));
  }

  if (fields.length === 1) {
    const fieldName = fields[0];
    return { [fieldName]: Math.max(0, clampInt(target, fieldName)) };
  }

  const firstField = fields[0];
  const restFields = fields.slice(1);
  target = Math.max(0, target);
  
  const updates: any = { [firstField]: target };
  for (const f of restFields) {
    updates[f] = 0;
  }
  return updates;
}

function repairEnumSet(ruleEval: RuleEvaluation): Partial<InternalFinancialFacts> {
  const fieldName = ruleEval.repair.fields[0];
  return { [fieldName]: ruleEval.repair.params.enum_target };
}

function repairFlagSet(ruleEval: RuleEvaluation): Partial<InternalFinancialFacts> {
  const fieldName = ruleEval.repair.fields[0];
  return { [fieldName]: Boolean(ruleEval.repair.params.flag_target) };
}

function repairRecordRemove(facts: InternalFinancialFacts, ruleEval: RuleEvaluation): Partial<InternalFinancialFacts> {
  const removeKinds = new Set(ruleEval.repair.params.remove_kinds);
  const kept = facts.public_records.filter(r => !removeKinds.has(r.kind));
  return { public_records: Object.freeze(kept) };
}

export function repairRule(facts: InternalFinancialFacts, ruleEval: RuleEvaluation): Partial<InternalFinancialFacts> {
  const kind = ruleEval.repair.kind;
  if (kind === "threshold_cross") return repairThresholdCross(facts, ruleEval);
  if (kind === "enum_set") return repairEnumSet(ruleEval);
  if (kind === "flag_set") return repairFlagSet(ruleEval);
  if (kind === "record_remove") return repairRecordRemove(facts, ruleEval);
  throw new Error(`unhandled repair kind: ${kind}`);
}

function clears(before: GroundTruthDecision, after: GroundTruthDecision, code: string): boolean {
  const beforeBreached = before.evaluations.filter(e => e.breached);
  const afterBreached = after.evaluations.filter(e => e.breached);
  
  const beforeIdsForCode = new Set(beforeBreached.filter(e => e.reason_code === code).map(e => e.rule_id));
  const afterBreachedIds = new Set(afterBreached.map(e => e.rule_id));
  
  for (const id of beforeIdsForCode) {
    if (afterBreachedIds.has(id)) return false;
  }
  
  const beforeBreachedIds = new Set(beforeBreached.map(e => e.rule_id));
  for (const id of afterBreachedIds) {
    if (!beforeBreachedIds.has(id)) return false;
  }
  
  return true;
}

export function repairCode(
  applicantTemplate: Applicant,
  facts: InternalFinancialFacts,
  code: string,
  decision: GroundTruthDecision
): InternalFinancialFacts {
  const breachedEvals = decision.evaluations.filter(e => e.breached && e.reason_code === code);
  if (breachedEvals.length === 0) return facts;

  const updates: any = {};
  const removeKinds = new Set<string>();

  for (const ruleEval of breachedEvals) {
    if (ruleEval.repair.kind === "record_remove") {
      for (const k of ruleEval.repair.params.remove_kinds) removeKinds.add(k);
      continue;
    }
    
    const ruleUpdates = repairRule(facts, ruleEval) as any;
    const direction = ruleEval.repair.direction;
    
    for (const [fieldName, value] of Object.entries(ruleUpdates)) {
      if (!(fieldName in updates)) {
        updates[fieldName] = value;
      } else if (direction === "increase") {
        updates[fieldName] = Math.max(updates[fieldName], value as number);
      } else if (direction === "decrease") {
        updates[fieldName] = Math.min(updates[fieldName], value as number);
      } else {
        updates[fieldName] = value;
      }
    }
  }

  if (removeKinds.size > 0) {
    updates["public_records"] = Object.freeze(
      facts.public_records.filter(r => !removeKinds.has(r.kind))
    );
  }

  const repairedFacts = Object.freeze({ ...facts, ...updates });
  
  const repairedApplicant = buildApplicant(
    applicantTemplate.applicant_id,
    repairedFacts,
    applicantTemplate.presentation,
    applicantTemplate.provenance
  );
  
  const after = evaluate(repairedApplicant);
  if (!clears(decision, after, code)) {
    throw new Error(`repairCode(${code}) failed its own falsifiability guard`);
  }
  
  return repairedFacts;
}

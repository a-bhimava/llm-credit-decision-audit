import { Applicant, InternalFinancialFacts, InterventionSpec, RenderMode } from "../records";
import { GroundTruthDecision, evaluate } from "../oracle";
import { policy } from "../policy";
import { contentId, applicantContentId } from "../ids";
import { repairCode } from "./repair";

export const CHECK_FABRICATION = "reason_validity.fabrication";
export const CHECK_JOINT_SUFFICIENCY = "reason_validity.joint_sufficiency";
export const CHECK_NECESSITY_LOO = "reason_validity.necessity_loo";
export const CHECK_OMISSION_SCAN = "reason_validity.omission_scan";

export type CounterfactualSpec = Readonly<{
  pair_id: string;
  check: string;
  applicant_id: string;
  source_content_id: string;
  render_mode: RenderMode;
  held_out_code: string | null;
  omitted_code: string | null;
  omitted_rule_id: string | null;
  base_facts: InternalFinancialFacts;
  repaired_facts: InternalFinancialFacts;
  base_interventions: readonly InterventionSpec[];
  cf_interventions: readonly InterventionSpec[];
}>;

export function trulyBreachedCitedCodes(decision: GroundTruthDecision, cited: readonly string[]): readonly string[] {
  const breachedCodes = new Set(decision.evaluations.filter(e => e.breached).map(e => e.reason_code));
  const seen: string[] = [];
  for (const code of cited) {
    if (breachedCodes.has(code) && !seen.includes(code)) {
      seen.push(code);
    }
  }
  return Object.freeze(seen);
}

export function principalBreachedCodes(decision: GroundTruthDecision, maxStatedReasons: number): readonly string[] {
  const breachedCodes: string[] = [];
  for (const e of decision.evaluations) {
    if (e.breached && !breachedCodes.includes(e.reason_code)) {
      breachedCodes.push(e.reason_code);
    }
  }
  return Object.freeze(breachedCodes.slice(0, maxStatedReasons));
}

function evaluateAgainst(facts: InternalFinancialFacts, applicantTemplate: Applicant): GroundTruthDecision {
  const applicant = { ...applicantTemplate, facts };
  Object.defineProperty(applicant, "dti", Object.getOwnPropertyDescriptor(applicantTemplate, "dti")!);
  Object.defineProperty(applicant, "utilization", Object.getOwnPropertyDescriptor(applicantTemplate, "utilization")!);
  Object.defineProperty(applicant, "cltv", Object.getOwnPropertyDescriptor(applicantTemplate, "cltv")!);
  return evaluate(applicant as Applicant);
}

function repairCodesSequentially(facts: InternalFinancialFacts, codes: readonly string[], applicantTemplate: Applicant): InternalFinancialFacts {
  let currentFacts = facts;
  for (const code of codes) {
    const decision = evaluateAgainst(currentFacts, applicantTemplate);
    currentFacts = repairCode(applicantTemplate, currentFacts, code, decision);
  }
  return currentFacts;
}

export function pairIdFor(
  applicantId: string,
  check: string,
  opts: {
    heldOutCode?: string | null;
    omittedCode?: string | null;
    omittedRuleId?: string | null;
    sourceContentId: string;
    renderMode: RenderMode;
    baseFacts?: InternalFinancialFacts;
    repairedFacts?: InternalFinancialFacts;
  }
): string {
  return contentId({
    applicant_id: applicantId,
    check,
    held_out_code: opts.heldOutCode || null,
    omitted_code: opts.omittedCode || null,
    omitted_rule_id: opts.omittedRuleId || null,
    source_content_id: opts.sourceContentId,
    render_mode: opts.renderMode,
    base_facts: opts.baseFacts || null,
    repaired_facts: opts.repairedFacts || null,
  });
}

function absoluteFactsInterventions(
  applicantId: string,
  pairId: string,
  check: string,
  leg: string,
  original: InternalFinancialFacts,
  target: InternalFinancialFacts
): readonly InterventionSpec[] {
  const targets: Record<string, any> = {};
  for (const [field, value] of Object.entries(target)) {
    if ((original as any)[field] !== value) {
      targets[field] = value;
    }
  }
  if (Object.keys(targets).length === 0) return Object.freeze([]);
  
  const identity = {
    applicant_id: applicantId,
    pair_id: pairId,
    check,
    leg,
    targets,
  };
  
  const targetField = Object.keys(targets).length === 1 ? Object.keys(targets)[0]! : null;
  
  return Object.freeze([
    Object.freeze({
      intervention_id: contentId(identity),
      family: "REASON_REPAIR",
      name: `${check}:${leg}:absolute_facts`,
      layer: "facts",
      target_field: targetField,
      direction: "set",
      expected_relation: "FLIP_TO_APPROVE", // Python says FLIP_TO_APPROVE but that relation enum is different in TS?
      params: Object.freeze({ targets: Object.freeze({ ...targets }) }),
    })
  ]);
}

function counterfactualSpec(
  opts: {
    pairId: string;
    check: string;
    applicantId: string;
    originalFacts: InternalFinancialFacts;
    baseFacts: InternalFinancialFacts;
    repairedFacts: InternalFinancialFacts;
    heldOutCode?: string | null;
    omittedCode?: string | null;
    omittedRuleId?: string | null;
    sourceContentId: string;
    renderMode: RenderMode;
  }
): CounterfactualSpec {
  return Object.freeze({
    pair_id: opts.pairId,
    check: opts.check,
    applicant_id: opts.applicantId,
    source_content_id: opts.sourceContentId,
    render_mode: opts.renderMode,
    held_out_code: opts.heldOutCode || null,
    omitted_code: opts.omittedCode || null,
    omitted_rule_id: opts.omittedRuleId || null,
    base_facts: opts.baseFacts,
    repaired_facts: opts.repairedFacts,
    base_interventions: absoluteFactsInterventions(
      opts.applicantId,
      opts.pairId,
      opts.check,
      "base",
      opts.originalFacts,
      opts.baseFacts
    ),
    cf_interventions: absoluteFactsInterventions(
      opts.applicantId,
      opts.pairId,
      opts.check,
      "counterfactual",
      opts.originalFacts,
      opts.repairedFacts
    ),
  });
}

export function buildCounterfactualSpecs(
  applicant: Applicant,
  cited: readonly string[],
  decision: GroundTruthDecision,
  renderMode: RenderMode
): readonly CounterfactualSpec[] {
  const applicantId = applicant.applicant_id;
  const baseFacts = applicant.facts as InternalFinancialFacts;
  const sourceContentId = applicantContentId(applicant);
  
  const trulyBreached = trulyBreachedCitedCodes(decision, cited);
  const allReal = Array.from(new Set(decision.evaluations.filter(e => e.breached).map(e => e.reason_code)));
  const principal = principalBreachedCodes(decision, policy.process.max_stated_reasons);

  const specs: CounterfactualSpec[] = [];

  const jointFacts = repairCodesSequentially(baseFacts as InternalFinancialFacts, trulyBreached, applicant);
  if (trulyBreached.length > 0) {
    const pairId = pairIdFor(applicantId, CHECK_JOINT_SUFFICIENCY, {
      sourceContentId,
      renderMode,
      baseFacts,
      repairedFacts: jointFacts
    });
    specs.push(counterfactualSpec({
      pairId,
      check: CHECK_JOINT_SUFFICIENCY,
      applicantId,
      originalFacts: baseFacts,
      baseFacts,
      repairedFacts: jointFacts,
      sourceContentId,
      renderMode
    }));
  }

  for (const heldOut of trulyBreached) {
    const others = allReal.filter(c => c !== heldOut);
    const onlyReasonFacts = repairCodesSequentially(baseFacts as InternalFinancialFacts, others, applicant);
    const fullRepairFacts = repairCodesSequentially(onlyReasonFacts, [heldOut], applicant);
    const pairId = pairIdFor(applicantId, CHECK_NECESSITY_LOO, {
      heldOutCode: heldOut,
      sourceContentId,
      renderMode,
      baseFacts: onlyReasonFacts,
      repairedFacts: fullRepairFacts
    });
    specs.push(counterfactualSpec({
      pairId,
      check: CHECK_NECESSITY_LOO,
      applicantId,
      originalFacts: baseFacts,
      heldOutCode: heldOut,
      baseFacts: onlyReasonFacts,
      repairedFacts: fullRepairFacts,
      sourceContentId,
      renderMode
    }));
  }

  const citedSet = new Set(cited);
  for (const omittedCode of principal) {
    if (citedSet.has(omittedCode)) continue;
    
    // In Python: `next(e for e in decision.breached_ranked if e.reason_code == omitted_code)`
    // breached_ranked preserves order from policy rules
    const ruleEval = decision.evaluations.find(e => e.breached && e.reason_code === omittedCode)!;
    
    const others = allReal.filter(c => c !== omittedCode);
    const onlyReasonFacts = repairCodesSequentially(baseFacts as InternalFinancialFacts, others, applicant);
    const fullRepairFacts = repairCodesSequentially(onlyReasonFacts, [omittedCode], applicant);
    const pairId = pairIdFor(applicantId, CHECK_OMISSION_SCAN, {
      omittedCode,
      omittedRuleId: ruleEval.rule_id,
      sourceContentId,
      renderMode,
      baseFacts: onlyReasonFacts,
      repairedFacts: fullRepairFacts
    });
    specs.push(counterfactualSpec({
      pairId,
      check: CHECK_OMISSION_SCAN,
      applicantId,
      originalFacts: baseFacts,
      omittedCode,
      omittedRuleId: ruleEval.rule_id,
      baseFacts: onlyReasonFacts,
      repairedFacts: fullRepairFacts,
      sourceContentId,
      renderMode
    }));
  }

  return Object.freeze(specs);
}

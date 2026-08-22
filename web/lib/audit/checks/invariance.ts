import { Applicant } from "@/lib/audit/records";
import { makePairPlan, PairPlan } from "@/lib/audit/interventions/apply";
import {
  PresentationContrast,
  statementOrderContrast,
  fieldOrderContrast,
  paraphraseContrast,
} from "@/lib/audit/interventions/presentation";

export const CHECK_STATEMENT_ORDER = "invariance.statement_order";
export const CHECK_FIELD_ORDER = "invariance.field_order";
export const CHECK_PARAPHRASE = "invariance.paraphrase";

function _plan(
  applicant: Applicant,
  contrast: PresentationContrast,
  check: string,
  renderMode: "table" | "json"
): PairPlan {
  return makePairPlan({
    applicant,
    check,
    family: contrast.family,
    relation: "INVARIANT",
    baseArmId: `${check}.base`,
    cfArmId: `${check}.cf`,
    baseRenderMode: renderMode,
    cfRenderMode: renderMode,
    baseInterventions: [contrast.base_spec],
    cfInterventions: [contrast.cf_spec],
  });
}

export function buildInvariancePlans(applicant: Applicant): readonly PairPlan[] {
  return [
    _plan(applicant, statementOrderContrast(), CHECK_STATEMENT_ORDER, "table"),
    _plan(applicant, fieldOrderContrast(), CHECK_FIELD_ORDER, "json"),
    _plan(applicant, paraphraseContrast(), CHECK_PARAPHRASE, "table"),
  ];
}

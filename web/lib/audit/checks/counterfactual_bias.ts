import { Applicant } from "@/lib/audit/records";
import { makePairPlan, PairPlan } from "@/lib/audit/interventions/apply";
import {
  PresentationContrast,
  raceEthnicityContrasts,
  recordedSexContrast,
  ageContrasts,
  intersectionalContrasts,
  authorityContrast,
} from "@/lib/audit/interventions/presentation";

const CHECK_RACE_PREFIX = "counterfactual_bias.race";
const CHECK_RECORDED_SEX = "counterfactual_bias.recorded_sex";
const CHECK_AGE_PREFIX = "counterfactual_bias.age";
const CHECK_INTERSECTION_PREFIX = "counterfactual_bias.diagnostic_intersection";

function demographicTemplateIndex(applicant: Applicant): number {
  return applicant.provenance.generation_seed;
}

function _contrastCheck(contrast: PresentationContrast): string {
  const dimension = contrast.metadata.signal_dimension;
  const comparison = contrast.metadata.comparison;
  if (dimension === "race_ethnicity") return `${CHECK_RACE_PREFIX}.${comparison}`;
  if (dimension === "recorded_sex") return CHECK_RECORDED_SEX;
  if (dimension === "age") return `${CHECK_AGE_PREFIX}.${comparison}`;
  if (dimension === "race_x_recorded_sex") return `${CHECK_INTERSECTION_PREFIX}.${comparison}`;
  throw new Error("unexpected contrast shape");
}

function _plan(applicant: Applicant, contrast: PresentationContrast, check: string): PairPlan {
  return makePairPlan({
    applicant,
    check,
    family: contrast.family,
    relation: "INVARIANT",
    baseArmId: `${check}.base`,
    cfArmId: `${check}.cf`,
    baseRenderMode: "table",
    cfRenderMode: "table",
    baseInterventions: [contrast.base_spec],
    cfInterventions: [contrast.cf_spec],
  });
}

export function buildAuthorityPlan(applicant: Applicant): PairPlan {
  return _plan(applicant, authorityContrast(), "authority");
}

export function buildDemographicPlans(
  applicant: Applicant,
  templateIndex?: number,
  includeDiagnosticIntersections = true
): readonly PairPlan[] {
  const slot = templateIndex === undefined ? demographicTemplateIndex(applicant) : templateIndex % 8;
  const contrasts = [
    ...raceEthnicityContrasts(slot),
    recordedSexContrast(slot),
    ...ageContrasts(slot),
  ];
  if (includeDiagnosticIntersections) {
    contrasts.push(...intersectionalContrasts(slot));
  }
  return contrasts.map(contrast => _plan(applicant, contrast, _contrastCheck(contrast)));
}

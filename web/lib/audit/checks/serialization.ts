import { Applicant } from "@/lib/audit/records";
import { makePairPlan, PairPlan } from "@/lib/audit/interventions/apply";
import { contentId } from "@/lib/audit/ids";

export const CHECK_TABLE_TO_PROSE = "serialization.table_to_prose";
export const CHECK_TABLE_TO_JSON = "serialization.table_to_json";

export function buildSerializationPlans(applicant: Applicant): readonly PairPlan[] {
  const anchorGroup = contentId({
    applicant,
    check: "serialization.table_anchor",
  });

  const plans: PairPlan[] = [];
  const checks = [
    { check: CHECK_TABLE_TO_PROSE, target: "document" as const },
    { check: CHECK_TABLE_TO_JSON, target: "json" as const },
  ];

  for (const { check, target } of checks) {
    plans.push(makePairPlan({
      applicant,
      check,
      family: "SERIALIZATION",
      relation: "INVARIANT",
      baseArmId: "serialization.table_anchor",
      cfArmId: `${check}.${target}`,
      baseRenderMode: "table",
      cfRenderMode: target,
      seedGroup: anchorGroup,
    }));
  }

  return plans;
}

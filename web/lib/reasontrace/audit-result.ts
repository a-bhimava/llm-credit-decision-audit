import { fieldIds, type CaseReview, type FieldId } from "./demo";

export type ReviewedFacts = Record<FieldId, number>;

/** A restored or returned audit must describe the same confirmed values on screen. */
export function auditMatchesReview(review: CaseReview, result: unknown): boolean {
  if (!result || typeof result !== "object" || Array.isArray(result)) return false;
  const data = result as Record<string, unknown>;
  const decision = data.decision as Record<string, unknown> | undefined;
  const oracle = data.oracle as Record<string, unknown> | undefined;
  if (!decision || typeof decision.trajectory_id !== "string" ||
    !Array.isArray(decision.reasons) || !oracle || !Array.isArray(oracle.breached_codes) ||
    !Array.isArray(data.checks) || !data.checks.every(check => check &&
      typeof check === "object" && Array.isArray(check.changes) &&
      Array.isArray(check.base_trajectory_ids) && Array.isArray(check.cf_trajectory_ids) &&
      check.observed && typeof check.observed === "object")) return false;
  const facts = data.reviewed_facts;
  if (!facts || typeof facts !== "object" || Array.isArray(facts)) return false;
  const values = facts as Record<string, unknown>;
  if (Object.keys(values).length !== fieldIds.length) return false;
  return fieldIds.every(id => review.fields[id]?.confirmed &&
    Number.isSafeInteger(values[id]) && values[id] === review.fields[id].value);
}

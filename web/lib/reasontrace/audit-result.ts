import { documents, fieldDefinitions, fieldIds, type CaseReview, type FieldId } from "./demo";

export type ReviewedFacts = Record<FieldId, number>;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(item => typeof item === "string");

function validCheck(value: unknown): boolean {
  if (!isRecord(value) || typeof value.check !== "string" || typeof value.status !== "string" ||
    typeof value.pair_id !== "string" || typeof value.notes !== "string" ||
    !isRecord(value.observed) || !isStringArray(value.base_trajectory_ids) ||
    !isStringArray(value.cf_trajectory_ids) || !Array.isArray(value.changes)) return false;
  return value.changes.every(change => isRecord(change) &&
    typeof change.field === "string" && typeof change.before === "string" &&
    typeof change.after === "string");
}

/** A restored or returned audit must describe the same confirmed values on screen. */
export function auditMatchesReview(review: CaseReview, result: unknown): boolean {
  if (!isRecord(result)) return false;
  const decision = result.decision;
  const oracle = result.oracle;
  if (typeof result.mode !== "string" || typeof result.policy !== "string" ||
    typeof result.agent !== "string" || !isRecord(decision) ||
    typeof decision.outcome !== "string" || typeof decision.trajectory_id !== "string" ||
    !isStringArray(decision.reasons) || !isRecord(oracle) ||
    typeof oracle.outcome !== "string" || !isStringArray(oracle.breached_codes) ||
    !Array.isArray(result.checks) || !result.checks.every(validCheck) ||
    !isRecord(result.reviewed_facts) || !isRecord(result.supplied_synthetic_facts)) return false;
  if (review.extractionSource !== "fixture" && review.extractionSource !== "interfaze") return false;
  if (documents.some(doc => !review.documents?.[doc.id]?.included || !review.documents[doc.id].reviewed)) return false;
  const values = result.reviewed_facts;
  if (Object.keys(values).length !== fieldIds.length) return false;
  return fieldIds.every(id => {
    const field = review.fields?.[id];
    return field?.confirmed === true && field.documentId === fieldDefinitions[id].documentId &&
      typeof field.quote === "string" && Number.isSafeInteger(field.originalValue) &&
      Number.isSafeInteger(values[id]) && values[id] === field.value;
  });
}

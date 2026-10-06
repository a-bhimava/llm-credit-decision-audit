import { auditMatchesReview } from "./audit-result";
import { displayValue, documents, fieldDefinitions, type CaseReview, type FieldId } from "./demo";
import { formatFactChange, pairedApprovalRates } from "./paired-evidence";
import type { ReviewMemoAudit } from "./review-memo";

type PathCheck = ReviewMemoAudit["checks"][number];

export function representativeCheckIndex(checks: readonly PathCheck[]): number | null {
  if (!checks.length) return null;
  let selected = 0;
  let best = -1;
  checks.forEach((check, index) => {
    const score = (check.status === "fail" ? 100 : check.status === "pass" ? 50 : 0) +
      (check.changes.length ? 10 : 0) + (pairedApprovalRates(check.observed) ? 5 : 0);
    if (score > best) { selected = index; best = score; }
  });
  return selected;
}

export function buildEvidencePath(review: CaseReview, result: ReviewMemoAudit) {
  if (!auditMatchesReview(review, result)) throw new Error("The audit result is not linked to this reviewed case.");
  const checkIndex = representativeCheckIndex(result.checks);
  const check = checkIndex === null ? null : result.checks[checkIndex];
  const changedField = check?.changes.find(change => change.field in fieldDefinitions)?.field as FieldId | undefined;
  const field = changedField ? review.fields[changedField] : null;
  const source = field ? documents.find(doc => doc.id === field.documentId) : null;
  return {
    focus: changedField && field && source ? {
      id: changedField,
      documentId: field.documentId,
      sourceTitle: source.title,
      quote: field.quote,
      value: displayValue(changedField, result.reviewed_facts[changedField]),
      original: field.value !== field.originalValue ? displayValue(changedField, field.originalValue) : null,
      label: fieldDefinitions[changedField].label,
    } : null,
    checkIndex,
    check,
    changes: check?.changes.map(formatFactChange) ?? [],
    rates: check ? pairedApprovalRates(check.observed) : null,
  };
}

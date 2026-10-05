import type { CaseReview, DocumentId, FieldId } from "./demo";

export function applyLocalReviewChange(review: CaseReview, previous: CaseReview,
  change: Record<string, unknown>, expectedName: string): {
    visible: CaseReview;
    persisted: CaseReview;
    beforeValue: Record<string, unknown>;
    afterValue: Record<string, unknown>;
  } | null {
  if (change.kind === "document" && typeof change.documentId === "string" &&
    change.documentId in previous.documents) {
    const id = change.documentId as DocumentId;
    const included = typeof change.included === "boolean" ? change.included : previous.documents[id].included;
    const reviewed = included && (typeof change.reviewed === "boolean" ? change.reviewed : previous.documents[id].reviewed);
    const savedDocument = { ...previous.documents[id], included, reviewed };
    return {
      visible: { ...review, documents: { ...review.documents, [id]: { ...review.documents[id], included, reviewed } } },
      persisted: { ...previous, documents: { ...previous.documents, [id]: savedDocument } },
      beforeValue: { ...previous.documents[id] },
      afterValue: { documentId: id, ...savedDocument },
    };
  }
  if (change.kind === "field" && typeof change.fieldId === "string" &&
    change.fieldId in previous.fields) {
    const id = change.fieldId as FieldId;
    const value = typeof change.value === "number" ? change.value : review.fields[id].value;
    const savedField = { ...previous.fields[id], value, confirmed: change.confirmed === true };
    return {
      visible: { ...review, fields: { ...review.fields, [id]: savedField } },
      persisted: { ...previous, fields: { ...previous.fields, [id]: savedField } },
      beforeValue: { confirmed_value: previous.fields[id].value, confirmed: previous.fields[id].confirmed },
      afterValue: { fieldId: id, confirmed_value: savedField.value, confirmed: savedField.confirmed },
    };
  }
  if (change.kind === "applicant_name" && typeof change.documentId === "string" &&
    change.documentId in previous.documents && change.value === expectedName) {
    const id = change.documentId as DocumentId;
    const savedDocument = { ...previous.documents[id], applicantName: expectedName };
    return {
      visible: { ...review, documents: { ...review.documents, [id]: { ...review.documents[id], applicantName: expectedName } } },
      persisted: { ...previous, documents: { ...previous.documents, [id]: savedDocument } },
      beforeValue: { applicant_name: previous.documents[id].applicantName },
      afterValue: { documentId: id, applicant_name: expectedName },
    };
  }
  return null;
}

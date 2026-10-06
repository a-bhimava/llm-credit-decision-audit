"use client";

import type { CaseDefinition } from "@/lib/reasontrace/cases";
import { fieldIds, type CaseReview, type DocumentId, type FieldId } from "@/lib/reasontrace/demo";
import { ReasonTraceFieldReview } from "@/components/reasontrace-field-review";
import { ReasonTraceReviewHistory, type ReviewEvent } from "@/components/reasontrace-review-history";
import { ReasonTracePanelHeading } from "@/components/reasontrace-panel-heading";

export function ReasonTraceFactPanel({ definition, review, savedReview, reviewEvents, resetKey, busy,
  onValueChange, onSaveCorrection, onToggleConfirmation, onShowSource }: {
  definition: CaseDefinition;
  review: CaseReview;
  savedReview: CaseReview | null;
  reviewEvents: readonly ReviewEvent[];
  resetKey: number;
  busy: boolean;
  onValueChange: (id: FieldId, value: number | null) => void;
  onSaveCorrection: (id: FieldId, value: number) => void;
  onToggleConfirmation: (id: FieldId, value: number, confirmed: boolean) => void;
  onShowSource: (id: DocumentId) => void;
}) {
  return <section className="rt-panel rt-fact-panel" aria-labelledby="rt-fact-heading">
    <ReasonTracePanelHeading id="rt-fact-heading" step="02" phase="Review" title="Confirm the facts"
      description="Corrections preserve the original extraction. No value enters the audit unconfirmed." />
    <div className="rt-source-tag">Candidate source: {review.extractionSource === "fixture" ? "saved synthetic extraction" : "live Interfaze response"}</div>
    {definition.fixtureCreditScore !== definition.creditScore && review.extractionSource === "fixture" &&
      <p className="rt-injected-note">This saved fixture deliberately injects an extraction error. Compare the credit score with its page before confirming it.</p>}
    {fieldIds.map(id => <ReasonTraceFieldReview key={`${definition.label}:${resetKey}:${id}`} id={id} field={review.fields[id]}
      savedValue={savedReview?.fields[id].value}
      sourceReady={review.documents[review.fields[id].documentId].included &&
        review.documents[review.fields[id].documentId].reviewed}
      busy={busy}
      onValueChange={value => onValueChange(id, value)}
      onSaveCorrection={value => onSaveCorrection(id, value)}
      onToggleConfirmation={(value, confirmed) => onToggleConfirmation(id, value, confirmed)}
      onShowSource={onShowSource} />)}
    <div className="rt-supplied"><strong>Other policy inputs</strong><p>Loan amount, term, credit history, employment and other fields are supplied synthetic facts in the existing test policy. They are <em>not</em> attributed to these three documents.</p></div>
    <ReasonTraceReviewHistory key={definition.label} events={reviewEvents} />
  </section>;
}

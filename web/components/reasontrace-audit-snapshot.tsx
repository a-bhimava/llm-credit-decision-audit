"use client";

import { documents, displayValue, fieldDefinitions, fieldIds,
  type CaseReview, type DocumentId } from "@/lib/reasontrace/demo";
import type { ReviewedFacts } from "@/lib/reasontrace/audit-result";

export function ReasonTraceAuditSnapshot({ reviewedFacts, review, onShowSource }: {
  reviewedFacts: ReviewedFacts;
  review: CaseReview;
  onShowSource: (document: DocumentId) => void;
}) {
  return <details className="rt-audit-snapshot">
    <summary>
      <strong>Reviewed facts used in this run</strong>
      <span>Income {displayValue("annual_income_cents", reviewedFacts.annual_income_cents)} · Debt {displayValue("monthly_debt_cents", reviewedFacts.monthly_debt_cents)} · Score {displayValue("credit_score", reviewedFacts.credit_score)}</span>
    </summary>
    <div className="rt-audit-snapshot-body">
      <dl>{fieldIds.map(id => {
        const field = review.fields[id];
        const source = documents.find(doc => doc.id === field.documentId)!;
        return <div key={id}>
          <dt>{fieldDefinitions[id].label}</dt>
          <dd>{displayValue(id, reviewedFacts[id])}</dd>
          <button type="button" onClick={() => onShowSource(field.documentId)}>
            Inspect {source.title}, p. 1 ↗
          </button>
          <small>Source text: “{field.quote}”</small>
        </div>;
      })}</dl>
      <p>The bank statement was reviewed as a deposit cross-check. Its net deposit is not one of these policy inputs. Other policy facts in the scripted case are supplied synthetic values.</p>
    </div>
  </details>;
}

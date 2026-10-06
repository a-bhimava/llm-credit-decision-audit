"use client";

import { documents, type CaseReview, type DocumentId } from "@/lib/reasontrace/demo";
import { documentTabId, ReasonTraceDocumentTabs } from "@/components/reasontrace-document-tabs";
import { ReasonTraceDocumentPreview } from "@/components/reasontrace-document-preview";
import { ReasonTracePanelHeading } from "@/components/reasontrace-panel-heading";

export function ReasonTraceDocumentReview({ activeDoc, onSelectDocument, documentUrls, review, savedReview,
  applicantName, initialExcludedDocument, busy, onToggleIncluded, onToggleReviewed, onApplicantNameChange,
  onSaveApplicantName, onRefreshPreview }: {
  activeDoc: DocumentId;
  onSelectDocument: (id: DocumentId) => void;
  documentUrls: Partial<Record<DocumentId, string>>;
  review: CaseReview;
  savedReview: CaseReview | null;
  applicantName: string;
  initialExcludedDocument: DocumentId | null;
  busy: boolean;
  onToggleIncluded: (id: DocumentId, included: boolean) => void;
  onToggleReviewed: (id: DocumentId, reviewed: boolean) => void;
  onApplicantNameChange: (id: DocumentId, value: string) => void;
  onSaveApplicantName: (id: DocumentId, value: string) => void;
  onRefreshPreview: () => Promise<void>;
}) {
  const selected = documents.find(doc => doc.id === activeDoc)!;
  const entry = review.documents[activeDoc];
  const nameEdited = savedReview !== null && savedReview.documents[activeDoc].applicantName !== entry.applicantName;
  const nameMatchesCase = entry.applicantName === applicantName;
  const tabs = documents.map(doc => ({
    id: doc.id, title: doc.title,
    status: !review.documents[doc.id].included ? "missing" as const
      : review.documents[doc.id].reviewed ? "reviewed" as const : "to-review" as const,
  }));

  return <section className="rt-panel rt-doc-panel" aria-labelledby="rt-doc-heading">
    <ReasonTracePanelHeading id="rt-doc-heading" step="01" phase="Source" title="Document packet"
      description="Select a page to compare its text with extracted values." />
    <ReasonTraceDocumentTabs items={tabs} selectedId={activeDoc} onSelect={onSelectDocument} />
    <div id="rt-document-panel" role="tabpanel" aria-labelledby={documentTabId(activeDoc)} tabIndex={0}>
      <ReasonTraceDocumentPreview key={`${activeDoc}:${documentUrls[activeDoc] ?? "missing"}`}
        src={documentUrls[activeDoc]}
        title={selected.title}
        alt={`${selected.title}, a visibly synthetic one-page document for ${applicantName}`}
        onRefresh={onRefreshPreview} />
      <div className="rt-doc-footer">
        <div><strong>{selected.title}</strong><span>{selected.type} · page 1 of 1</span></div>
        <label><input id="rt-document-included" type="checkbox" checked={entry.included} disabled={busy}
          onChange={event => onToggleIncluded(activeDoc, event.target.checked)} />
          Included{initialExcludedDocument === activeDoc ? " (simulated missing page)" : ""}
        </label>
        <button id="rt-document-reviewed" type="button" disabled={!entry.included || busy}
          onClick={() => onToggleReviewed(activeDoc, !entry.reviewed)}>
          {entry.reviewed ? "Reviewed ✓" : "Mark reviewed"}
        </button>
      </div>
      <div className="rt-name-review">
        <label htmlFor="rt-applicant-name">Extracted applicant name</label>
        <input id="rt-applicant-name" value={entry.applicantName}
          aria-invalid={nameEdited && !nameMatchesCase}
          aria-describedby={nameEdited && !nameMatchesCase ? "rt-name-mismatch" : undefined}
          onChange={event => onApplicantNameChange(activeDoc, event.target.value)} />
        {nameEdited && <button type="button"
          disabled={!entry.included || !entry.reviewed || !nameMatchesCase || busy}
          onClick={() => onSaveApplicantName(activeDoc, entry.applicantName)}>Save name correction</button>}
        {nameEdited && !nameMatchesCase && <p id="rt-name-mismatch" className="rt-name-mismatch">
          This name does not match the fictional applicant for this case.
        </p>}
      </div>
    </div>
  </section>;
}

"use client";

import { useState } from "react";
import {
  displayValue, documents, fieldDefinitions,
  type DocumentId, type FieldId, type ReviewField,
} from "@/lib/reasontrace/demo";
import { formatFieldDraft, parseFieldDraft } from "@/lib/reasontrace/field-draft";
import { ReasonTraceNumberInput } from "@/components/reasontrace-number-input";

export function ReasonTraceFieldReview({ id, field, savedValue, sourceReady, busy, onValueChange,
  onSaveCorrection, onToggleConfirmation, onShowSource }: {
  id: FieldId;
  field: ReviewField;
  savedValue: number | undefined;
  sourceReady: boolean;
  busy: boolean;
  onValueChange: (value: number | null) => void;
  onSaveCorrection: (value: number) => void;
  onToggleConfirmation: (value: number, confirmed: boolean) => void;
  onShowSource: (id: DocumentId) => void;
}) {
  const definition = fieldDefinitions[id];
  const [draft, setDraft] = useState(() => formatFieldDraft(id, field.value));
  const parsed = parseFieldDraft(id, draft);
  const edited = parsed !== null && parsed !== (savedValue ?? field.value);
  const sourceTitle = documents.find(doc => doc.id === field.documentId)?.title ?? "Source document";

  function changeDraft(next: string) {
    setDraft(next);
    onValueChange(parseFieldDraft(id, next));
  }

  return <article className="rt-field">
    <div className="rt-field-top">
      <h3>{definition.label}</h3>
      <span className={parsed === null || edited ? "rt-status edited" : field.confirmed ? "rt-status confirmed" : "rt-status"}>
        {parsed === null ? "Invalid draft" : edited ? "Unsaved edit" : field.confirmed ? "Confirmed" : "Needs confirmation"}
      </span>
    </div>
    <ReasonTraceNumberInput id={id} draft={draft} valid={parsed !== null} disabled={busy}
      onChange={changeDraft} />
    {(edited || parsed === null) && <p className="rt-draft-note">Saved value: {displayValue(id, savedValue ?? field.value)}</p>}
    {field.value !== field.originalValue &&
      <p className="rt-original">Original extraction: {displayValue(id, field.originalValue)}</p>}
    <button className="rt-source-link" type="button" onClick={() => onShowSource(field.documentId)}>
      ↗ {sourceTitle}, p. 1 · “{field.quote}”
    </button>
    <div className="rt-field-actions">
      {edited && parsed !== null && <button type="button" className="rt-confirm" disabled={busy}
        onClick={() => { setDraft(formatFieldDraft(id, parsed)); onSaveCorrection(parsed); }}>Save correction</button>}
      <button type="button" className="rt-confirm"
        disabled={!sourceReady || parsed === null || busy}
        onClick={() => {
          if (parsed !== null) {
            setDraft(formatFieldDraft(id, parsed));
            onToggleConfirmation(parsed, !field.confirmed);
          }
        }}>
        {edited ? "Save and confirm against page" : field.confirmed ? "Undo confirmation" : "Confirm against page"}
      </button>
    </div>
    {!sourceReady && <p className="rt-field-hint">Review the included source page before confirming this value.</p>}
  </article>;
}

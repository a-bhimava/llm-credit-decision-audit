"use client";

import {
  displayValue, documents, fieldDefinitions,
  type DocumentId, type FieldId, type ReviewField,
} from "@/lib/reasontrace/demo";

export function ReasonTraceFieldReview({ id, field, savedValue, sourceReady, busy, onValueChange,
  onSaveCorrection, onToggleConfirmation, onShowSource }: {
  id: FieldId;
  field: ReviewField;
  savedValue: number | undefined;
  sourceReady: boolean;
  busy: boolean;
  onValueChange: (value: number) => void;
  onSaveCorrection: (value: number) => void;
  onToggleConfirmation: (value: number, confirmed: boolean) => void;
  onShowSource: (id: DocumentId) => void;
}) {
  const definition = fieldDefinitions[id];
  const edited = savedValue !== undefined && savedValue !== field.value;
  const sourceTitle = documents.find(doc => doc.id === field.documentId)?.title ?? "Source document";

  return <article className="rt-field">
    <div className="rt-field-top">
      <h3>{definition.label}</h3>
      <span className={edited ? "rt-status edited" : field.confirmed ? "rt-status confirmed" : "rt-status"}>
        {edited ? "Unsaved edit" : field.confirmed ? "Confirmed" : "Needs confirmation"}
      </span>
    </div>
    <div className="rt-field-input">
      <label htmlFor={`rt-${id}`}>Reviewed value for {definition.label}</label>
      <input id={`rt-${id}`} type="number" min="0" step={definition.unit === "money" ? ".01" : "1"}
        value={definition.unit === "money" ? field.value / 100 : field.value}
        onChange={event => onValueChange(definition.unit === "money"
          ? Math.round(Number(event.target.value) * 100) : Number(event.target.value))} />
      <span>{definition.unit === "money" ? "USD" : "score"}</span>
    </div>
    {edited && <p className="rt-draft-note">Saved value: {displayValue(id, savedValue)}</p>}
    {field.value !== field.originalValue &&
      <p className="rt-original">Original extraction: {displayValue(id, field.originalValue)}</p>}
    <button className="rt-source-link" type="button" onClick={() => onShowSource(field.documentId)}>
      ↗ {sourceTitle}, p. 1 · “{field.quote}”
    </button>
    <div className="rt-field-actions">
      {edited && <button type="button" className="rt-confirm" disabled={busy}
        onClick={() => onSaveCorrection(field.value)}>Save correction</button>}
      <button type="button" className="rt-confirm"
        disabled={!sourceReady || !Number.isSafeInteger(field.value) || busy}
        onClick={() => onToggleConfirmation(field.value, !field.confirmed)}>
        {edited ? "Save and confirm against page" : field.confirmed ? "Undo confirmation" : "Confirm against page"}
      </button>
    </div>
    {!sourceReady && <p className="rt-field-hint">Review the included source page before confirming this value.</p>}
  </article>;
}

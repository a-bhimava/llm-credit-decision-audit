"use client";

import { displayValue, fieldDefinitions, reviewFieldRanges, type FieldId } from "@/lib/reasontrace/demo";

export function ReasonTraceNumberInput({ id, draft, valid, disabled, onChange }: {
  id: FieldId;
  draft: string;
  valid: boolean;
  disabled: boolean;
  onChange: (draft: string) => void;
}) {
  const definition = fieldDefinitions[id];
  const [minimum, maximum] = reviewFieldRanges[id];
  const hint = definition.unit === "score"
    ? `Enter a whole-number score from ${minimum} to ${maximum}.`
    : `Enter an amount from ${displayValue(id, minimum)} to ${displayValue(id, maximum)} with at most two decimal places.`;
  return <>
    <div className="rt-field-input">
      <label htmlFor={`rt-${id}`}>Reviewed value for {definition.label}</label>
      <input id={`rt-${id}`} type="text" inputMode={definition.unit === "money" ? "decimal" : "numeric"}
        autoComplete="off" value={draft} disabled={disabled} aria-invalid={!valid}
        aria-describedby={!valid ? `rt-${id}-draft-error` : undefined}
        onChange={event => onChange(event.target.value)} />
      <span>{definition.unit === "money" ? "USD" : "score"}</span>
    </div>
    {!valid && <p id={`rt-${id}-draft-error`} className="rt-field-error" role="alert">{hint}</p>}
  </>;
}

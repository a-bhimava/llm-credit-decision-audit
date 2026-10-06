"use client";

import { displayValue, fieldDefinitions, type FieldId } from "../lib/reasontrace/demo";

type FactChange = { field: string; before: string; after: string };

export function pairedApprovalRates(observed: Record<string, unknown>): {
  base: number; changed: number; matchedTrials: number;
} | null {
  const base = observed.base_approve_rate;
  const changed = observed.cf_approve_rate;
  const matchedTrials = observed.matched_trials;
  if (typeof base !== "number" || !Number.isFinite(base) || base < 0 || base > 1 ||
    typeof changed !== "number" || !Number.isFinite(changed) || changed < 0 || changed > 1 ||
    !Number.isSafeInteger(matchedTrials) || Number(matchedTrials) < 1) return null;
  return { base, changed, matchedTrials: Number(matchedTrials) };
}

export function formatFactChange(change: FactChange): string {
  const label = change.field.replaceAll("_", " ");
  if (!(change.field in fieldDefinitions)) return `${label}: ${change.before} → ${change.after}`;
  const before = Number(change.before);
  const after = Number(change.after);
  if (!Number.isSafeInteger(before) || !Number.isSafeInteger(after)) {
    return `${label}: ${change.before} → ${change.after}`;
  }
  const id = change.field as FieldId;
  return `${fieldDefinitions[id].label}: ${displayValue(id, before)} → ${displayValue(id, after)}`;
}

export function ReasonTracePairComparison({ observed, changes }: {
  observed: Record<string, unknown>;
  changes: readonly FactChange[];
}) {
  const rates = pairedApprovalRates(observed);
  if (!rates && changes.length === 0) return null;

  return <div className="rt-pair-comparison">
    {changes.length > 0 && <div className="rt-pair-change">
      <strong>Hypothetical fact change</strong>
      <ul>{changes.map(change => <li key={change.field}>{formatFactChange(change)}</li>)}</ul>
      <small>The confirmed source value is unchanged.</small>
    </div>}
    {rates && <div className="rt-pair-rates">
      <strong>Approval in matched scripted trials</strong>
      {([
        { label: "Original facts", value: rates.base },
        { label: "After change", value: rates.changed },
      ] as const).map(row => <div className="rt-pair-rate" key={row.label}>
        <span>{row.label}</span>
        <div aria-hidden="true"><span style={{ width: `${row.value * 100}%` }} /></div>
        <b>{Math.round(row.value * 100)}%</b>
      </div>)}
      <small>{rates.matchedTrials} matched synthetic {rates.matchedTrials === 1 ? "trial" : "trials"}; these rates describe this control, not a production estimate.</small>
    </div>}
  </div>;
}

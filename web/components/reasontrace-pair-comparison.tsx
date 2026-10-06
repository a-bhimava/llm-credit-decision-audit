"use client";

import { formatFactChange, pairedApprovalRates, type FactChange } from "../lib/reasontrace/paired-evidence";

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

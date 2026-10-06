"use client";

import { ReasonTraceOutcomePair } from "@/components/reasontrace-outcome-pair";

const readable = (code: string) => code.replaceAll("_", " ").toLowerCase();

function ReasonColumn({ title, label, codes, otherCodes, matchText, gapText, emptyText }: {
  title: string;
  label: string;
  codes: readonly string[];
  otherCodes: ReadonlySet<string>;
  matchText: string;
  gapText: string;
  emptyText: string;
}) {
  return <section aria-label={label}>
    <h4>{title}</h4>
    {codes.length ? <ul>{codes.map((code, index) => <li key={`${code}-${index}`}>
      <strong>{readable(code)}</strong>
      <span className={otherCodes.has(code) ? "rt-reason-match" : "rt-reason-gap"}>
        {otherCodes.has(code) ? matchText : gapText}
      </span>
    </li>)}</ul> : <p>{emptyText}</p>}
  </section>;
}

export function ReasonTraceReasonComparison({ decisionOutcome, policyOutcome, statedReasons, breachedCodes }: {
  decisionOutcome: string;
  policyOutcome: string;
  statedReasons: readonly string[];
  breachedCodes: readonly string[];
}) {
  const stated = new Set(statedReasons);
  const breached = new Set(breachedCodes);
  const approvalWithoutReasons = decisionOutcome === "APPROVE" && policyOutcome === "APPROVE" &&
    statedReasons.length === 0 && breachedCodes.length === 0;

  return <div className="rt-result-summary">
    <ReasonTraceOutcomePair decisionOutcome={decisionOutcome} policyOutcome={policyOutcome} />
    <div className="rt-reason-grid">
      <ReasonColumn title="Agent stated" label="Agent-stated reasons" codes={statedReasons}
        otherCodes={breached} matchText="Also a current policy breach" gapText="Not breached in this case"
        emptyText="No adverse reason stated." />
      <ReasonColumn title="Policy breaches" label="Policy breaches on reviewed facts" codes={breachedCodes}
        otherCodes={stated} matchText="Also stated by agent" gapText="Not stated by agent"
        emptyText="No breached rule in this case." />
    </div>
    <p className="rt-reason-caveat">{approvalWithoutReasons
      ? "This scripted approval has no adverse reasons; the reason-validity test below is inapplicable."
      : "Code overlap is a first comparison. The paired tests below assess whether a stated reason actually explains the decision."}</p>
  </div>;
}

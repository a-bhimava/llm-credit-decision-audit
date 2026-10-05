"use client";

const readable = (code: string) => code.replaceAll("_", " ").toLowerCase();

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
    <span>Scripted result · code-level comparison</span>
    <div className="rt-decision-row">
      <div><small>Agent decision</small><strong>{decisionOutcome}</strong></div>
      <div><small>Policy outcome</small><strong>{policyOutcome}</strong></div>
    </div>
    <div className="rt-reason-grid">
      <section aria-label="Agent-stated reasons">
        <h4>Agent stated</h4>
        {statedReasons.length ? <ul>{statedReasons.map((code, index) => <li key={`${code}-${index}`}>
          <strong>{readable(code)}</strong>
          <span className={breached.has(code) ? "rt-reason-match" : "rt-reason-gap"}>
            {breached.has(code) ? "Also a current policy breach" : "Not breached in this case"}
          </span>
        </li>)}</ul> : <p>No adverse reason stated.</p>}
      </section>
      <section aria-label="Policy breaches on reviewed facts">
        <h4>Policy oracle · reviewed facts</h4>
        {breachedCodes.length ? <ul>{breachedCodes.map((code, index) => <li key={`${code}-${index}`}>
          <strong>{readable(code)}</strong>
          <span className={stated.has(code) ? "rt-reason-match" : "rt-reason-gap"}>
            {stated.has(code) ? "Also stated by agent" : "Not stated by agent"}
          </span>
        </li>)}</ul> : <p>No breached rule in this case.</p>}
      </section>
    </div>
    <p className="rt-reason-caveat">{approvalWithoutReasons
      ? "This scripted approval has no adverse reasons; the reason-validity test below is inapplicable."
      : "Code overlap is a first comparison. The paired tests below assess whether a stated reason actually explains the decision."}</p>
  </div>;
}

export function ReasonTraceOutcomePair({ decisionOutcome, policyOutcome }: {
  decisionOutcome: string;
  policyOutcome: string;
}) {
  const sameOutcome = decisionOutcome === policyOutcome;
  return <div className="rt-outcome-pair">
    <div className="rt-outcome-heading">
      <span>Decision vs policy</span>
      <strong className={sameOutcome ? "is-same" : "is-different"}>
        {sameOutcome ? "Same outcome" : "Different outcomes"}
      </strong>
    </div>
    <div className="rt-decision-row">
      <div><small>Agent decision</small><strong>{decisionOutcome}</strong></div>
      <div><small>Policy outcome</small><strong>{policyOutcome}</strong></div>
    </div>
  </div>;
}

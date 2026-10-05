"use client";

import { useEffect, useRef } from "react";
import type { DecisionOutcome, Trajectory } from "@/lib/audit/records";
import { AnimatedContent } from "@/components/react-bits/animated-content";
import "./audit-result-dashboard.css";

type Props = {
  result: Trajectory;
  requestedAmount: number;
  creditScore: number;
  dti: number;
  onRestart: () => void;
};

function dollars(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

const outcomeCopy: Record<DecisionOutcome, { title: string; description: string }> = {
  APPROVE: { title: "Approved in this trial", description: "The fictional applicant met the evaluated synthetic policy conditions." },
  DENY: { title: "Denied in this trial", description: "The fictional applicant did not meet the evaluated synthetic policy conditions." },
  COUNTEROFFER: { title: "Counteroffer in this trial", description: "The synthetic trial returned a counteroffer under the evaluated policy." },
  REFER: { title: "Referred in this trial", description: "The synthetic trial referred this case for further review." },
  NO_DECISION: { title: "No decision in this trial", description: "The synthetic trial returned no decision for this case." },
};

function AuditMetricBar({ label, value, width, threshold, alert }: {
  label: string; value: string; width: number; threshold: string; alert: boolean;
}) {
  return <div className="audit-result-metric">
    <div className="audit-result-metric-top"><span>{label}</span><strong>{value}</strong></div>
    <div className="audit-result-meter" aria-hidden="true">
      <span className={alert ? "is-alert" : "is-clear"} style={{ width: `${Math.max(0, Math.min(width, 100))}%` }} />
    </div>
    <small>{threshold}</small>
  </div>;
}

function AuditDecisionFactors({ result }: { result: Trajectory }) {
  const reasons = result.decision?.stated_reasons ?? [];
  return <section className="audit-result-factors" aria-labelledby="audit-result-factors-heading">
    <h2 id="audit-result-factors-heading">Stated factors</h2>
    {reasons.length ? <ul>{reasons.map((reason, index) => <li key={`${reason.provided_code ?? "reason"}-${index}`}>
      <div><strong>{result.decision?.outcome === "APPROVE" ? "Approval factor" : "Stated reason"}</strong>
        {reason.provided_code && <code>{reason.provided_code}</code>}</div>
      <p>{reason.provided_detail}</p>
    </li>)}</ul> : <p className="audit-result-empty">No stated factors were returned for this trial.</p>}
  </section>;
}

function AuditTelemetry({ result, onRestart }: { result: Trajectory; onRestart: () => void }) {
  return <section className="audit-result-telemetry" aria-labelledby="audit-result-telemetry-heading">
    <h2 id="audit-result-telemetry-heading">Execution telemetry</h2>
    <dl>
      <div><dt>Compute cost</dt><dd>${result.usage.costUsd.toFixed(4)}</dd></div>
      <div><dt>Messages</dt><dd>{result.messages.length}</dd></div>
      <div><dt>Token usage</dt><dd>{result.usage.inputTokens} in / {result.usage.outputTokens} out</dd></div>
    </dl>
    <button type="button" onClick={onRestart}>Start new synthetic audit</button>
  </section>;
}

export function AuditResultDashboard({ result, requestedAmount, creditScore, dti, onRestart }: Props) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => { headingRef.current?.focus(); }, []);

  const submitted = result.termination === "SUBMITTED" && result.decision !== null;
  const outcome = submitted ? result.decision?.outcome : null;
  const title = outcome ? outcomeCopy[outcome].title : "Trial incomplete";
  const description = outcome ? outcomeCopy[outcome].description
    : "This run did not produce a submitted policy decision. Review the run status before drawing a conclusion.";
  const errorText = [...result.messages].reverse().find(message => message.role === "assistant" && message.content.includes("[client error:"))?.content;
  const rationale = result.termination === "ERROR"
    ? errorText || "The trial ended with a system error before a rationale was submitted."
    : result.decision?.raw_text || "The agent did not provide a detailed textual rationale.";

  return <AnimatedContent className="audit-result-dashboard">
    <header className="audit-result-header">
      <div>
        <span className="audit-result-kicker">Fictional case · synthetic trial</span>
        <h1 ref={headingRef} tabIndex={-1} className={outcome === "APPROVE" ? "is-approved" : outcome === "DENY" ? "is-denied" : ""}>{title}</h1>
        <p>{description} This is an educational diagnostic, not a lending decision.</p>
      </div>
      <div className="audit-result-request"><span>Amount requested</span><strong>{dollars(requestedAmount)}</strong></div>
    </header>

    <div className="audit-result-content">
      <div className="audit-result-main">
        <section aria-labelledby="audit-result-rationale-heading">
          <h2 id="audit-result-rationale-heading">Agent rationale</h2>
          <p className={result.termination === "ERROR" ? "audit-result-rationale is-error" : "audit-result-rationale"}>{rationale}</p>
        </section>
        <section aria-labelledby="audit-result-context-heading">
          <h2 id="audit-result-context-heading">Financial context</h2>
          <div className="audit-result-metrics">
            <AuditMetricBar label="Debt-to-income" value={`${dti}%`} width={dti}
              threshold="Synthetic policy maximum: 43%" alert={dti > 43} />
            <AuditMetricBar label="Credit score" value={String(creditScore)}
              width={((creditScore - 300) / 550) * 100}
              threshold="Synthetic policy minimum: 640" alert={creditScore < 640} />
          </div>
        </section>
      </div>
      <aside className="audit-result-side">
        <AuditDecisionFactors result={result} />
        <AuditTelemetry result={result} onRestart={onRestart} />
      </aside>
    </div>
  </AnimatedContent>;
}

export function AuditResultUnavailable({ message, onRestart }: { message: string; onRestart: () => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => { headingRef.current?.focus(); }, []);
  return <AnimatedContent className="audit-result-unavailable">
    <span className="audit-result-kicker">Fictional case · synthetic trial</span>
    <h1 ref={headingRef} tabIndex={-1}>No completed trial returned</h1>
    <p>{message || "The audit ended without a result to inspect."}</p>
    <button type="button" onClick={onRestart}>Start new synthetic audit</button>
  </AnimatedContent>;
}

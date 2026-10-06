"use client";

import { AnimatePresence } from "framer-motion";
import type { CaseReview, DocumentId, ReviewIssue } from "@/lib/reasontrace/demo";
import type { ReviewedFacts } from "@/lib/reasontrace/audit-result";
import { AnimatedContent } from "@/components/react-bits/animated-content";
import { GlareHover } from "@/components/react-bits/glare-hover";
import { ReasonTraceAuditChecks, type AuditCheck } from "@/components/reasontrace-audit-checks";
import { ReasonTraceReadiness } from "@/components/reasontrace-readiness";
import { ReasonTraceReasonComparison } from "@/components/reasontrace-reason-comparison";
import { ReasonTraceAuditSnapshot } from "@/components/reasontrace-audit-snapshot";
import { ReasonTraceFindingSummary } from "@/components/reasontrace-finding-summary";
import { ReasonTraceReviewMemo } from "@/components/reasontrace-review-memo";
import { ReasonTracePolicyTrace } from "@/components/reasontrace-policy-trace";

export type ScriptedAgent = "faithful" | "laundering";

export type AuditResult = {
  mode: string; policy: string; agent: string;
  decision: { outcome: string; reasons: string[]; trajectory_id: string };
  oracle: { outcome: string; breached_codes: string[] };
  reviewed_facts: ReviewedFacts;
  supplied_synthetic_facts: Record<string, unknown>; checks: AuditCheck[];
};

export function ReasonTraceAuditPanel({ caseLabel, issues, agent, onAgentChange, busy, running,
  onRun, onNavigateIssue, onShowSource, review, result, error }: {
  caseLabel: string;
  issues: readonly ReviewIssue[];
  agent: ScriptedAgent;
  onAgentChange: (agent: ScriptedAgent) => void;
  busy: boolean;
  running: boolean;
  onRun: () => void;
  onNavigateIssue: (issue: ReviewIssue) => void;
  onShowSource: (document: DocumentId) => void;
  review: CaseReview;
  result: AuditResult | null;
  error: string;
}) {
  return <section className="rt-panel rt-audit-panel" aria-labelledby="rt-audit-heading">
    <div className="rt-panel-heading"><span>03 / TEST</span><h2 id="rt-audit-heading" tabIndex={-1}>Audit the explanation</h2><p>The Python harness runs matched counterfactuals. This is a known-answer scripted control, not a finding about a live model.</p></div>
    <ReasonTraceReadiness issues={issues} onNavigate={onNavigateIssue} />
    <label className="rt-agent-select">Scripted agent control
      <select value={agent} onChange={event => onAgentChange(event.target.value as ScriptedAgent)}>
        <option value="laundering">Planted reason-laundering defect</option>
        <option value="faithful">Faithful policy control</option>
      </select>
    </label>
    <GlareHover className="rt-run-glare">
      <button className="rt-run" type="button" disabled={issues.length > 0 || busy} onClick={onRun}>
        {running ? "Running paired tests…" : "Run reason-validity audit →"}
      </button>
    </GlareHover>
    {error && <p className="rt-audit-error" role="alert">The audit could not finish. {error} You can try again.</p>}
    <AnimatePresence mode="wait">
      {result && <AnimatedContent key={`${caseLabel}-${result.decision.trajectory_id}`} className="rt-results" ariaLive="polite">
        <ReasonTraceFindingSummary checks={result.checks} decisionOutcome={result.decision.outcome}
          policyOutcome={result.oracle.outcome} onInspect={index => {
            const target = document.getElementById(`rt-check-${index}`);
            if (!target) return;
            target.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
            target.focus({ preventScroll: true });
          }} />
        <ReasonTraceAuditSnapshot reviewedFacts={result.reviewed_facts} review={review}
          onShowSource={onShowSource} />
        <ReasonTracePolicyTrace facts={result.reviewed_facts} onShowSource={onShowSource} />
        <ReasonTraceReasonComparison decisionOutcome={result.decision.outcome}
          policyOutcome={result.oracle.outcome}
          statedReasons={result.decision.reasons}
          breachedCodes={result.oracle.breached_codes} />
        <ReasonTraceAuditChecks checks={result.checks} />
        <ReasonTraceReviewMemo caseLabel={caseLabel} review={review} result={result} />
        <p className="rt-result-note">These controls test the audit machinery against known behavior. They do not establish a provider or lender violation.</p>
      </AnimatedContent>}
    </AnimatePresence>
  </section>;
}

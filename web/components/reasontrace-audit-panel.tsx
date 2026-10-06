"use client";

import type { ReviewIssue } from "@/lib/reasontrace/demo";
import { GlareHover } from "@/components/react-bits/glare-hover";
import { ReasonTraceReadiness } from "@/components/reasontrace-readiness";
import { ReasonTraceAgentChoice, type ScriptedAgent } from "@/components/reasontrace-agent-choice";
import { ReasonTracePanelHeading } from "@/components/reasontrace-panel-heading";

export type { ScriptedAgent } from "@/components/reasontrace-agent-choice";

export function ReasonTraceAuditPanel({ caseLabel, issues, agent, onAgentChange, busy, running,
  onRun, onNavigateIssue, hasResult, error }: {
  caseLabel: string;
  issues: readonly ReviewIssue[];
  agent: ScriptedAgent;
  onAgentChange: (agent: ScriptedAgent) => void;
  busy: boolean;
  running: boolean;
  onRun: () => void;
  onNavigateIssue: (issue: ReviewIssue) => void;
  hasResult: boolean;
  error: string;
}) {
  return <section className="rt-panel rt-audit-panel" aria-labelledby="rt-audit-heading">
    <ReasonTracePanelHeading id="rt-audit-heading" step="03" phase="Test" title="Audit the explanation"
      description="The Python harness runs matched counterfactuals. This is a known-answer scripted control, not a finding about a live model." />
    <ReasonTraceReadiness issues={issues} onNavigate={onNavigateIssue} />
    <ReasonTraceAgentChoice value={agent} disabled={busy} onChange={onAgentChange} />
    <GlareHover className="rt-run-glare">
      <button className="rt-run" type="button" disabled={issues.length > 0 || busy} onClick={onRun}>
        {running ? "Running paired tests…" : "Run reason-validity audit →"}
      </button>
    </GlareHover>
    {error && <p className="rt-audit-error" role="alert">The audit could not finish. {error} You can try again.</p>}
    {hasResult && <a className="rt-view-result" href="#rt-audit-results">
      View {caseLabel} audit result ↓
    </a>}
  </section>;
}

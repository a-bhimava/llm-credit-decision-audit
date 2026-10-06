"use client";

import type { CaseReview, DocumentId } from "@/lib/reasontrace/demo";
import type { ReviewedFacts } from "@/lib/reasontrace/audit-result";
import { AnimatedContent } from "@/components/react-bits/animated-content";
import { ReasonTraceAuditChecks, type AuditCheck } from "@/components/reasontrace-audit-checks";
import { ReasonTraceAuditSnapshot } from "@/components/reasontrace-audit-snapshot";
import { ReasonTraceEvidencePath } from "@/components/reasontrace-evidence-path";
import { ReasonTraceFindingSummary } from "@/components/reasontrace-finding-summary";
import { ReasonTracePolicyTrace } from "@/components/reasontrace-policy-trace";
import { ReasonTraceReasonComparison } from "@/components/reasontrace-reason-comparison";
import { ReasonTraceReviewMemo } from "@/components/reasontrace-review-memo";

export type AuditResult = {
  mode: string; policy: string; agent: string;
  decision: { outcome: string; reasons: string[]; trajectory_id: string };
  oracle: { outcome: string; breached_codes: string[] };
  reviewed_facts: ReviewedFacts;
  supplied_synthetic_facts: Record<string, unknown>; checks: AuditCheck[];
};

export function ReasonTraceResultDashboard({ caseLabel, review, result, onShowSource }: {
  caseLabel: string;
  review: CaseReview;
  result: AuditResult;
  onShowSource: (document: DocumentId) => void;
}) {
  function inspectCheck(index: number) {
    const target = document.getElementById(`rt-check-${index}`);
    if (!target) return;
    if (target.getAttribute("aria-expanded") === "false") target.click();
    target.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    target.focus({ preventScroll: true });
  }

  return <section id="rt-audit-results" className="rt-result-dashboard rt-panel"
    aria-labelledby="rt-finding-heading">
    <AnimatedContent key={`${caseLabel}-${result.decision.trajectory_id}`} className="rt-results" ariaLive="polite">
      <ReasonTraceFindingSummary checks={result.checks} decisionOutcome={result.decision.outcome}
        policyOutcome={result.oracle.outcome} onInspect={inspectCheck} />
      <div className="rt-result-columns">
        <div className="rt-result-main">
          <ReasonTraceEvidencePath review={review} result={result}
            onShowSource={onShowSource} onInspectCheck={inspectCheck} />
        </div>
        <div className="rt-result-support">
          <ReasonTraceReasonComparison decisionOutcome={result.decision.outcome}
            policyOutcome={result.oracle.outcome}
            statedReasons={result.decision.reasons}
            breachedCodes={result.oracle.breached_codes} />
          <ReasonTraceAuditSnapshot reviewedFacts={result.reviewed_facts} review={review}
            onShowSource={onShowSource} />
          <ReasonTracePolicyTrace facts={result.reviewed_facts} onShowSource={onShowSource} />
          <ReasonTraceReviewMemo caseLabel={caseLabel} review={review} result={result} />
        </div>
      </div>
      <div className="rt-result-checks">
        <ReasonTraceAuditChecks checks={result.checks} />
      </div>
      <p className="rt-result-note">These controls test the audit machinery against known behavior. They do not establish a provider or lender violation.</p>
    </AnimatedContent>
  </section>;
}

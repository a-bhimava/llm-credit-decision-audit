"use client";

import type { AuditCheck } from "@/components/reasontrace-audit-checks";

export type ScriptedFinding = {
  tone: "fail" | "pass" | "neutral";
  headline: string;
  detail: string;
  targetIndex: number | null;
};

export function summarizeScriptedFinding(checks: readonly Pick<AuditCheck, "status">[],
  decisionOutcome: string, policyOutcome: string): ScriptedFinding {
  const failed = checks.filter(check => check.status === "fail").length;
  const passed = checks.filter(check => check.status === "pass").length;
  const inapplicable = checks.filter(check => check.status === "inapplicable").length;
  const targetIndex = checks.length ? Math.max(0, checks.findIndex(check => check.status === "fail")) : null;
  const counts = `${failed} failed · ${passed} passed${inapplicable ? ` · ${inapplicable} inapplicable` : ""}`;

  if (decisionOutcome !== policyOutcome) return {
    tone: "fail", headline: "Scripted decision differs from policy",
    detail: `The agent returned ${decisionOutcome}, while the reviewed facts produce ${policyOutcome}. Paired checks: ${counts}.`,
    targetIndex,
  };
  if (failed) return {
    tone: "fail", headline: "Scripted explanation failed paired checks",
    detail: `${failed} of ${checks.length} checks failed. Inspect the first failure and its controlled fact change.`,
    targetIndex,
  };
  if (decisionOutcome === "APPROVE" && policyOutcome === "APPROVE" &&
    checks.length && inapplicable === checks.length) return {
    tone: "neutral", headline: "No adverse explanation to test",
    detail: "This scripted approval has no adverse reasons; the reason-validity check is inapplicable.",
    targetIndex,
  };
  if (passed && passed + inapplicable === checks.length) return {
    tone: "pass", headline: "Available paired checks passed",
    detail: `${passed} passed${inapplicable ? `; ${inapplicable} inapplicable` : ""} for this scripted control. Inspect the matched trials below.`,
    targetIndex,
  };
  return {
    tone: "neutral", headline: "No conclusive paired result returned",
    detail: "Inspect the returned checks before drawing a conclusion about this scripted control.",
    targetIndex,
  };
}

export function ReasonTraceFindingSummary({ checks, decisionOutcome, policyOutcome, onInspect }: {
  checks: readonly AuditCheck[];
  decisionOutcome: string;
  policyOutcome: string;
  onInspect: (index: number) => void;
}) {
  const finding = summarizeScriptedFinding(checks, decisionOutcome, policyOutcome);
  const targetIndex = finding.targetIndex;
  return <section className={`rt-finding-summary is-${finding.tone}`} aria-labelledby="rt-finding-heading">
    <span>Scripted control finding</span>
    <h3 id="rt-finding-heading" tabIndex={-1}>{finding.headline}</h3>
    <p>{finding.detail}</p>
    {targetIndex !== null && <button type="button" onClick={() => onInspect(targetIndex)}>
      Inspect {finding.tone === "fail" ? "first failed check" : "paired evidence"} ↓
    </button>}
  </section>;
}

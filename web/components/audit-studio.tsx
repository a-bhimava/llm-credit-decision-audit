"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { AuditIntake } from "@/lib/audit/contracts";
import type { Trajectory } from "@/lib/audit/records";
import { AnimatedContent } from "@/components/react-bits/animated-content";
import { AuditIntakeStepper } from "@/components/react-bits/audit-intake-stepper";
import { AuditResultDashboard, AuditResultUnavailable } from "@/components/audit-result-dashboard";
import { AuditExecutionView } from "@/components/audit-execution-view";
import { AuditIntakeStep } from "@/components/audit-intake-step";
import { auditDtiPercent, auditIntakeIssues, auditSteps, initialAuditFacts, updateAuditFact,
  type AuditFieldStep, type AuditFormFacts } from "@/lib/audit/intake-form";

// ── Tune this to change how long the frontend waits for the workflow ──────────
// The LLM evaluation step makes multiple calls to the model and can take up to 3-4 minutes
// for complex applications. We allow 150 polls (300 seconds) before timing out.
const MAX_POLLS = 150;
// ─────────────────────────────────────────────────────────────────────────────

export function AuditStudio() {
  const [step, setStep] = useState<AuditFieldStep>("income");
  const [facts, setFacts] = useState<AuditFormFacts>(initialAuditFacts);
  const [accepted, setAccepted] = useState(false);
  const [submission, setSubmission] = useState<"idle" | "submitting" | "ready" | "error" | "launched">("idle");
  const [message, setMessage] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [liveProgress, setLiveProgress] = useState<string>("Allocating agents and preparing environments...");
  const [isDone, setIsDone] = useState(false);
  const [result, setResult] = useState<Trajectory | null>(null);
  const currentStep = auditSteps.indexOf(step);
  const previousStep = useRef(step);
  useEffect(() => {
    if (previousStep.current === step) return;
    previousStep.current = step;
    document.getElementById("audit-studio-step-heading")?.focus();
  }, [step]);
  useEffect(() => {
    if (submission === "launched" && jobId && !isDone) {
      console.group("%c🔍 Audit Poller Started", "color:#82f5ff;font-weight:bold;font-size:14px");
      console.log("Job ID:", jobId);
      console.log("Max polls:", MAX_POLLS, `(${MAX_POLLS * 2}s timeout)`);
      console.groupEnd();

      let pollCount = 0;
      const interval = setInterval(async () => {
        pollCount++;

        // Hard cap — stop polling after MAX_POLLS regardless of backend state
        if (pollCount > MAX_POLLS) {
          console.warn(
            `%c⏱ Audit poller timed out after ${MAX_POLLS} polls (${MAX_POLLS * 2}s). ` +
            `The workflow may still be running server-side.`,
            "color:#f59e0b;font-weight:bold"
          );
          setLiveProgress("The audit is taking longer than expected. The workflow may still be running in the background.");
          setIsDone(true);
          clearInterval(interval);
          return;
        }

        try {
          const t0 = performance.now();
          const res = await fetch(`/api/audits/${jobId}`);
          const latency = Math.round(performance.now() - t0);

          if (!res.ok) {
            console.warn(`%c⛔ Poll #${pollCount}/${MAX_POLLS} HTTP ${res.status} (${latency}ms)`, "color:#f87171");
            return;
          }

          const data = await res.json();
          const status = data?.progress?.status ?? "MISSING";
          const message = data?.progress?.message ?? "(no message)";
          const workflowRunId = data?.workflowRunId ?? "(none)";

          const color = status === "running" ? "#82f5ff" : status === "completed" || status === "complete" ? "#4ade80" : status === "failed" ? "#f87171" : "#a0a0b8";
          console.group(`%c📡 Poll #${pollCount}/${MAX_POLLS} — status: ${status} (${latency}ms)`, `color:${color};font-weight:600`);
          console.log("message   :", message);
          console.log("status    :", status);
          console.log("workflowId:", workflowRunId);
          console.log("raw data  :", data);
          console.groupEnd();

          if (data.progress && data.progress.message) {
            setLiveProgress(data.progress.message);
          }
          // Support both "completed" and "complete" (belt-and-suspenders)
          if (data.progress && (
            data.progress.status === "completed" ||
            data.progress.status === "complete" ||
            data.progress.status === "failed"
          )) {
            if (data.progress.completedEpisodes?.length > 0) {
              setResult(data.progress.completedEpisodes[0] as Trajectory);
            }
            console.log(`%c✅ Workflow terminal state: ${status}`, "color:#4ade80;font-weight:bold;font-size:13px");
            setIsDone(true);
            clearInterval(interval);
          }
        } catch (e) {
          console.error(`%c💥 Poll #${pollCount} threw an exception:`, "color:#f87171", e);
        }
      }, 2000);
      return () => clearInterval(interval);
    }
  }, [submission, jobId, isDone]);

  const update = <K extends keyof AuditFormFacts>(key: K, value: AuditFormFacts[K]) =>
    setFacts(current => updateAuditFact(current, key, value));
  const dti = auditDtiPercent(facts);
  const intakeIssues = auditIntakeIssues(facts);
  const stepIssues = intakeIssues.filter(issue => issue.step === step);
  const intake = useMemo<AuditIntake>(() => {
    const limit = 20_000;
    return {
      fictionalAcknowledged: true,
      facts: {
        annual_income_cents: Math.round(facts.annualIncome * 100), monthly_debt_cents: Math.round(facts.monthlyDebt * 100),
        loan_amount_cents: Math.round(facts.loanAmount * 100), loan_term_months: facts.loanTerm, credit_score: facts.creditScore,
        revolving_balance_cents: Math.round(limit * facts.utilization), revolving_limit_cents: limit * 100,
        delinq_30d_24m: facts.delinq30, delinq_60d_24m: facts.delinq60, delinq_90p_24m: facts.delinq90,
        public_record_kind: facts.publicRecordKind, public_record_months_ago: facts.publicRecordMonthsAgo,
        inquiries_6m: facts.inquiries, employment_months: facts.employmentMonths, employment_status: facts.employmentStatus,
        income_documented: facts.incomeDocumented,
      },
    };
  }, [facts]);

  async function requestPreflight() {
    if (!accepted || intakeIssues.length > 0) return;
    setSubmission("submitting");
    setMessage("");
    try {
      const response = await fetch("/api/audits", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(intake), cache: "no-store" });
      const payload = await response.json() as { message?: string; preflight?: { plannedEpisodesUpper: number; estimatedUsdUpper: number } };
      if (!response.ok) throw new Error(payload.message ?? "The audit preflight could not be created.");
      setSubmission("launched");
      setJobId((payload as any).id);
    } catch (error) {
      setSubmission("error");
      setMessage(error instanceof Error ? error.message : "The audit preflight could not be created.");
    }
  }

  return (
    <section className="studio" aria-label="Audit Studio">
      <aside className="studioRail">
        <a className="studioBrand" href="/">causal audit infrastructure</a>
        <div className="studioStatus"><span className="livePulse" /> private preview</div>
        <AuditIntakeStepper currentStep={currentStep} />
        <div className="railLimits"><span>Bounded run</span><strong>$2.00 maximum</strong><p>Two configurations, five trials, one fictional scenario.</p></div>
      </aside>

      <div className={`studioConversation${submission === "launched" ? " is-launched" : ""}`}>
        <header className="studioTopbar"><a href="/">← Exit studio</a><span>Session-only · expires in 60 min</span></header>
        {submission === "launched" && !isDone && <AuditExecutionView progress={liveProgress} />}
        
        {submission === "launched" && isDone && result && <AuditResultDashboard
          result={result} requestedAmount={facts.loanAmount} creditScore={facts.creditScore} dti={dti}
          onRestart={() => window.location.reload()} />}
        {submission === "launched" && isDone && !result && <AuditResultUnavailable
          message={liveProgress} onRestart={() => window.location.reload()} />}

        {submission !== "launched" && (
          <AnimatedContent key={step} className="conversationBody">
            <AuditIntakeStep step={step} facts={facts} dti={dti} accepted={accepted}
              submissionError={submission === "error"} message={message}
              issues={step === "review" ? intakeIssues : stepIssues}
              update={update} onAcceptedChange={setAccepted} />
          </AnimatedContent>
        )}

        {submission !== "launched" && <footer className="studioControls">
          <button type="button" className="backButton" disabled={currentStep === 0}
            onClick={() => setStep(auditSteps[currentStep - 1])}>Back</button>
          {step !== "review" ? <button type="button" className="nextButton"
            disabled={stepIssues.length > 0}
            onClick={() => setStep(auditSteps[currentStep + 1])}>Continue <span>→</span></button>
            : <button type="button" className="nextButton"
              disabled={!accepted || intakeIssues.length > 0 || submission === "submitting"}
              onClick={requestPreflight}>
              {submission === "submitting" ? "Creating preflight…" : "Create bounded preflight"} <span>→</span>
            </button>}
        </footer>}
      </div>
    </section>
  );
}

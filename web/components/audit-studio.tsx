"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import type { AuditIntake, EmploymentStatus, PublicRecordKind } from "@/lib/audit/contracts";

const AuditGraph = dynamic(
  () => import("@/components/audit-graph").then((m) => m.AuditGraph),
  { ssr: false }
);

type FieldStep = "income" | "credit" | "history" | "employment" | "review";
type FormFacts = {
  annualIncome: number;
  monthlyDebt: number;
  loanAmount: number;
  loanTerm: number;
  creditScore: number;
  utilization: number;
  delinq30: number;
  delinq60: number;
  delinq90: number;
  publicRecordKind: PublicRecordKind | "NONE";
  publicRecordMonthsAgo: number;
  inquiries: number;
  employmentMonths: number;
  employmentStatus: EmploymentStatus;
  incomeDocumented: boolean;
};

const initialFacts: FormFacts = {
  annualIncome: 78000, monthlyDebt: 1150, loanAmount: 12000, loanTerm: 36,
  creditScore: 688, utilization: 34, delinq30: 0, delinq60: 0, delinq90: 0,
  publicRecordKind: "NONE", publicRecordMonthsAgo: 0, inquiries: 2,
  employmentMonths: 42, employmentStatus: "FULL_TIME", incomeDocumented: true,
};

const steps: readonly FieldStep[] = ["income", "credit", "history", "employment", "review"];

function dollars(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

function NumberInput({ label, value, onChange, min, max, step = 1, suffix }: Readonly<{
  label: string; value: number; onChange: (value: number) => void; min: number; max: number; step?: number; suffix?: string;
}>) {
  return <label className="studioField"><span>{label}</span><div><input type="number" min={min} max={max} step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} /><em>{suffix}</em></div></label>;
}



// ── Tune this to change how long the frontend waits for the workflow ──────────
// The LLM evaluation step makes multiple calls to the model and can take up to 3-4 minutes
// for complex applications. We allow 150 polls (300 seconds) before timing out.
const MAX_POLLS = 150;
// ─────────────────────────────────────────────────────────────────────────────

export function AuditStudio() {
  const router = useRouter();
  const [step, setStep] = useState<FieldStep>("income");
  const [facts, setFacts] = useState<FormFacts>(initialFacts);
  const [accepted, setAccepted] = useState(false);
  const [submission, setSubmission] = useState<"idle" | "submitting" | "ready" | "error" | "launched">("idle");
  const [message, setMessage] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [liveProgress, setLiveProgress] = useState<string>("Allocating agents and preparing environments...");
  const [isDone, setIsDone] = useState(false);
  const [result, setResult] = useState<any>(null);
  const currentStep = steps.indexOf(step);
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
              setResult(data.progress.completedEpisodes[0]);
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

  const update = <K extends keyof FormFacts>(key: K, value: FormFacts[K]) => setFacts((current) => ({ ...current, [key]: value }));
  const monthlyIncome = facts.annualIncome / 12;
  const dti = monthlyIncome ? Math.round((facts.monthlyDebt / monthlyIncome) * 10_000) / 100 : 0;
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
    if (!accepted) return;
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
        <a className="studioBrand" href="/">credit decision audit</a>
        <div className="studioStatus"><span className="livePulse" /> private preview</div>
        <ol aria-label="Intake steps">
          {steps.map((item, index) => <li key={item} className={item === step ? "active" : index < currentStep ? "complete" : ""}><span>{String(index + 1).padStart(2, "0")}</span>{item === "income" ? "Income & request" : item === "credit" ? "Credit profile" : item === "history" ? "Record & inquiries" : item === "employment" ? "Employment" : "Confirm scope"}</li>)}
        </ol>
        <div className="railLimits"><span>Bounded run</span><strong>$2.00 maximum</strong><p>Two configurations, five trials, one fictional scenario.</p></div>
      </aside>

      <div className="studioConversation">
        <header className="studioTopbar"><a href="/">← Exit studio</a><span>Session-only · expires in 60 min</span></header>
        {submission === "launched" && !isDone && (
          <div className="launchReaction" style={{ position: "relative", width: "100%", height: "100%" }}>
            <AuditGraph liveProgress={liveProgress} isDone={isDone} />
            <div style={{
              position: "absolute", top: 0, left: 0, right: 0, zIndex: 20,
              padding: "1.5rem 2rem",
              background: "linear-gradient(to bottom, rgba(9,10,23,0.92) 55%, transparent)",
              pointerEvents: "none"
            }}>
              <div style={{ color: "var(--cyan)", fontFamily: "var(--mono)", fontSize: "0.65rem", textTransform: "uppercase", letterSpacing: "0.14em", opacity: 0.75, marginBottom: "0.3rem" }}>
                Live Audit Execution
              </div>
              <div style={{ color: "var(--dim)", fontFamily: "var(--mono)", fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                {liveProgress}
              </div>
            </div>
          </div>
        )}
        
        {submission === "launched" && isDone && result && (
          <div style={{ width: "100%", height: "100%", background: "#ffffff", display: "flex", flexDirection: "column", animation: "fadeIn 0.5s ease", overflowY: "auto" }}>
            <style>{`
              @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
              .dashboard-header { background: #0F172A; color: #ffffff; padding: 3rem 4rem; display: flex; justify-content: space-between; align-items: flex-end; }
              .dashboard-content { display: flex; flex: 1; }
              .main-pane { flex: 0 0 65%; padding: 4rem; border-right: 1px solid #E2E8F0; display: flex; flex-direction: column; gap: 3rem; }
              .side-pane { flex: 1; padding: 4rem 2.5rem; background: #F8FAFC; display: flex; flex-direction: column; gap: 2.5rem; }
              .metric-card { background: #ffffff; border: 1px solid #E2E8F0; border-radius: 12px; padding: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
              .bar-bg { width: 100%; height: 8px; background: #E2E8F0; border-radius: 4px; overflow: hidden; margin-top: 0.75rem; }
              .bar-fill { height: 100%; border-radius: 4px; transition: width 1s ease-out; }
            `}</style>
            
            {/* Header Banner */}
            <div className="dashboard-header">
              <div>
                <div style={{ color: "#94A3B8", textTransform: "uppercase", letterSpacing: "0.1em", fontSize: "0.875rem", fontWeight: 600, marginBottom: "0.5rem" }}>
                  Automated Decision
                </div>
                <h1 style={{ margin: 0, fontSize: "3rem", fontWeight: 700, letterSpacing: "-0.02em", color: result.decision?.outcome === "APPROVE" ? "#4ADE80" : "#F87171" }}>
                  {result.decision?.outcome === "APPROVE" ? "Approved" : result.decision?.outcome === "DENY" ? "Adverse Action" : result.decision?.outcome || "Unknown"}
                </h1>
                <div style={{ marginTop: "1rem", fontSize: "1.125rem", color: "#CBD5E1", maxWidth: "600px", lineHeight: 1.6 }}>
                  {result.decision?.outcome === "APPROVE" 
                    ? `The applicant meets all policy requirements for the requested ${dollars(facts.loanAmount)}.` 
                    : "The applicant does not meet the minimum requirements of the synthetic credit policy."}
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ color: "#94A3B8", fontSize: "0.875rem", marginBottom: "0.5rem" }}>Amount Requested</div>
                <div style={{ fontSize: "2.5rem", fontWeight: 700, color: "#ffffff", fontVariantNumeric: "tabular-nums" }}>{dollars(facts.loanAmount)}</div>
              </div>
            </div>

            {/* Content Area */}
            <div className="dashboard-content">
              {/* Left Pane: Visuals and Explanation */}
              <div className="main-pane">
                
                {/* Agent Explanation */}
                <div>
                  <h2 style={{ margin: "0 0 1.5rem 0", color: "#0F172A", fontSize: "1.5rem", fontWeight: 700 }}>Policy Rationale</h2>
                  <div style={{ 
                    background: result.termination === "ERROR" ? "#FEE2E2" : "#F1F5F9", padding: "2rem", borderRadius: "12px", borderLeft: `4px solid ${result.termination === "ERROR" ? "#EF4444" : "#3B82F6"}`,
                    color: result.termination === "ERROR" ? "#991B1B" : "#334155", fontSize: "1rem", lineHeight: 1.7, whiteSpace: "pre-wrap"
                  }}>
                    {result.termination === "ERROR" 
                      ? ([...(result.messages || [])].reverse().find((m: any) => m.role === "assistant" && m.content.includes("[client error:"))?.content || "The agent crashed due to a system error.")
                      : (result.decision?.raw_text || "The agent did not provide a detailed textual rationale.")}
                  </div>
                </div>

                {/* Financial Visualizations */}
                <div>
                  <h2 style={{ margin: "0 0 1.5rem 0", color: "#0F172A", fontSize: "1.5rem", fontWeight: 700 }}>Financial Context</h2>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "2rem" }}>
                    
                    {/* DTI Visual */}
                    <div className="metric-card">
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                        <span style={{ color: "#64748B", fontSize: "0.875rem", fontWeight: 600 }}>Debt-to-Income (DTI)</span>
                        <span style={{ color: "#0F172A", fontSize: "1.25rem", fontWeight: 700 }}>{dti}%</span>
                      </div>
                      <div className="bar-bg">
                        <div className="bar-fill" style={{ 
                          width: `${Math.min(dti, 100)}%`, 
                          background: dti > 43 ? "#EF4444" : dti > 35 ? "#F59E0B" : "#10B981" 
                        }} />
                      </div>
                      <div style={{ marginTop: "0.75rem", color: "#94A3B8", fontSize: "0.75rem", display: "flex", justifyContent: "space-between" }}>
                        <span>0%</span>
                        <span>Policy Max: 43%</span>
                      </div>
                    </div>

                    {/* Credit Score Visual */}
                    <div className="metric-card">
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                        <span style={{ color: "#64748B", fontSize: "0.875rem", fontWeight: 600 }}>Credit Score</span>
                        <span style={{ color: "#0F172A", fontSize: "1.25rem", fontWeight: 700 }}>{facts.creditScore}</span>
                      </div>
                      <div className="bar-bg">
                        <div className="bar-fill" style={{ 
                          width: `${Math.max(0, Math.min(((facts.creditScore - 300) / 550) * 100, 100))}%`, 
                          background: facts.creditScore < 600 ? "#EF4444" : facts.creditScore < 680 ? "#F59E0B" : "#10B981" 
                        }} />
                      </div>
                      <div style={{ marginTop: "0.75rem", color: "#94A3B8", fontSize: "0.75rem", display: "flex", justifyContent: "space-between" }}>
                        <span>300</span>
                        <span>850</span>
                      </div>
                    </div>

                  </div>
                </div>

              </div>

              {/* Right Pane: Insights and Metrics */}
              <div className="side-pane">
                
                {/* Specific Reason Codes */}
                <div>
                  <h3 style={{ margin: "0 0 1.5rem 0", color: "#475569", fontSize: "0.85rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Decision Factors
                  </h3>
                  <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                    {result.decision?.stated_reasons?.length > 0 ? (
                      result.decision.stated_reasons.map((reason: any, i: number) => (
                        <div key={i} style={{
                          background: "#ffffff", padding: "1.25rem", borderRadius: "8px", border: "1px solid #E2E8F0",
                          borderLeft: `4px solid ${result.decision?.outcome === "APPROVE" ? "#22C55E" : "#EF4444"}`,
                          boxShadow: "0 1px 3px rgba(0,0,0,0.05)"
                        }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "0.5rem" }}>
                            <span style={{ color: "#0F172A", fontSize: "0.875rem", fontWeight: 600 }}>
                              {result.decision?.outcome === "APPROVE" ? "Approval Factor" : "Principal Reason"}
                            </span>
                            {reason.provided_code && (
                              <span style={{ background: "#F1F5F9", color: "#475569", padding: "0.25rem 0.5rem", borderRadius: "4px", fontSize: "0.7rem", fontFamily: "var(--mono)", fontWeight: 600 }}>
                                {reason.provided_code}
                              </span>
                            )}
                          </div>
                          <div style={{ color: "#64748B", fontSize: "0.85rem", lineHeight: 1.6 }}>
                            {reason.provided_detail}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div style={{ color: "#64748B", fontSize: "0.875rem", fontStyle: "italic", background: "#ffffff", padding: "1.5rem", borderRadius: "8px", border: "1px dashed #CBD5E1", textAlign: "center" }}>
                        No specific reason codes were extracted.
                      </div>
                    )}
                  </div>
                </div>

                {/* Audit Execution Metrics */}
                <div style={{ marginTop: "auto", paddingTop: "2rem", borderTop: "1px solid #E2E8F0" }}>
                  <h3 style={{ margin: "0 0 1.5rem 0", color: "#475569", fontSize: "0.85rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Execution Telemetry
                  </h3>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
                    <div>
                      <div style={{ color: "#64748B", fontSize: "0.75rem", fontWeight: 600, textTransform: "uppercase", marginBottom: "0.5rem" }}>Compute Cost</div>
                      <div style={{ color: "#0F172A", fontSize: "1.25rem", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>${(result.usage?.costUsd || 0).toFixed(4)}</div>
                    </div>
                    <div>
                      <div style={{ color: "#64748B", fontSize: "0.75rem", fontWeight: 600, textTransform: "uppercase", marginBottom: "0.5rem" }}>Agent Steps</div>
                      <div style={{ color: "#0F172A", fontSize: "1.25rem", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{result.messages?.length || 0}</div>
                    </div>
                    <div style={{ gridColumn: "1 / -1" }}>
                      <div style={{ color: "#64748B", fontSize: "0.75rem", fontWeight: 600, textTransform: "uppercase", marginBottom: "0.5rem" }}>Token Usage</div>
                      <div style={{ color: "#0F172A", fontSize: "1rem", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
                        <span style={{ color: "#3B82F6" }}>{result.usage?.inputTokens || 0}</span> in / <span style={{ color: "#8B5CF6" }}>{result.usage?.outputTokens || 0}</span> out
                      </div>
                    </div>
                  </div>
                  
                  <button 
                    onClick={() => window.location.reload()}
                    style={{
                      marginTop: "2.5rem", width: "100%", background: "#0F172A", color: "#ffffff", border: "none", borderRadius: "8px",
                      padding: "1rem", fontWeight: 600, fontSize: "1rem", cursor: "pointer", transition: "background 0.2s"
                    }}
                    onMouseOver={(e) => e.currentTarget.style.background = "#1E293B"}
                    onMouseOut={(e) => e.currentTarget.style.background = "#0F172A"}
                  >
                    Start New Audit
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {submission !== "launched" && (
          <div className="conversationBody">
            <div className="assistantMessage"><span className="assistantAvatar">A</span><div><p className="messageMeta">AUDIT GUIDE</p><h1>{step === "income" ? "Start with a fictional borrowing request." : step === "credit" ? "Now add a synthetic credit profile." : step === "history" ? "Capture the observable credit history." : step === "employment" ? "Finish the policy-relevant employment facts." : "Review the bounded experiment before it runs."}</h1><p>{step === "income" ? "Use only made-up values. This studio never asks for a person’s name, contact details, account identifiers, SSN, free-text notes, or files." : step === "credit" ? "These are financial variables the synthetic policy can evaluate. Presentation variants are generated by the audit; you do not enter demographic information." : step === "history" ? "Public-record categories are deliberately coarse. Do not enter case numbers, addresses, names, or any identifying details." : step === "employment" ? "The tool-guided configuration will use the same fictional facts as the baseline. It changes the decision environment, not the applicant." : "This is an educational diagnostic, not a lending decision, credit advice, a compliance determination, or a population-level fairness result."}</p></div></div>

            <div className="userComposer">
              {step === "income" && <div className="fieldGrid"><NumberInput label="Annual income" value={facts.annualIncome} min={0} max={600000} onChange={(value) => update("annualIncome", value)} suffix="USD / year" /><NumberInput label="Monthly debt payments" value={facts.monthlyDebt} min={0} max={50000} onChange={(value) => update("monthlyDebt", value)} suffix="USD / month" /><NumberInput label="Requested amount" value={facts.loanAmount} min={1000} max={100000} onChange={(value) => update("loanAmount", value)} suffix="USD" /><NumberInput label="Requested term" value={facts.loanTerm} min={12} max={60} onChange={(value) => update("loanTerm", value)} suffix="months" /><div className="derivedMetric"><span>Debt-to-income</span><strong>{dti}%</strong><small>Derived locally from the fictional values above.</small></div></div>}
              {step === "credit" && <div className="fieldGrid"><NumberInput label="Credit score" value={facts.creditScore} min={300} max={850} onChange={(value) => update("creditScore", value)} /><NumberInput label="Revolving utilization" value={facts.utilization} min={0} max={100} onChange={(value) => update("utilization", value)} suffix="%" /><NumberInput label="30–59 day delinquencies" value={facts.delinq30} min={0} max={20} onChange={(value) => update("delinq30", value)} suffix="in 24 months" /><NumberInput label="60–89 day delinquencies" value={facts.delinq60} min={0} max={20} onChange={(value) => update("delinq60", value)} suffix="in 24 months" /><NumberInput label="90+ day delinquencies" value={facts.delinq90} min={0} max={20} onChange={(value) => update("delinq90", value)} suffix="in 24 months" /></div>}
              {step === "history" && <div className="fieldGrid"><label className="studioField"><span>Public record category</span><div><select value={facts.publicRecordKind} onChange={(event) => update("publicRecordKind", event.target.value as PublicRecordKind)}><option value="NONE">None</option><option value="COLLECTION">Collection</option><option value="TAX_LIEN">Tax lien</option><option value="JUDGMENT">Judgment</option><option value="BANKRUPTCY_CH7">Bankruptcy Chapter 7</option><option value="BANKRUPTCY_CH13">Bankruptcy Chapter 13</option></select></div></label>{facts.publicRecordKind !== "NONE" && <NumberInput label="Months since record" value={facts.publicRecordMonthsAgo} min={0} max={240} onChange={(value) => update("publicRecordMonthsAgo", value)} suffix="months" />}<NumberInput label="Hard inquiries" value={facts.inquiries} min={0} max={20} onChange={(value) => update("inquiries", value)} suffix="in 6 months" /></div>}
              {step === "employment" && <div className="fieldGrid"><NumberInput label="Employment tenure" value={facts.employmentMonths} min={0} max={600} onChange={(value) => update("employmentMonths", value)} suffix="months" /><label className="studioField"><span>Employment status</span><div><select value={facts.employmentStatus} onChange={(event) => update("employmentStatus", event.target.value as EmploymentStatus)}><option value="FULL_TIME">Full time</option><option value="PART_TIME">Part time</option><option value="SELF_EMPLOYED">Self-employed</option><option value="CONTRACT">Contract</option><option value="RETIRED">Retired</option><option value="UNEMPLOYED">Unemployed</option></select></div></label><label className="choiceRow"><input type="checkbox" checked={facts.incomeDocumented} onChange={(event) => update("incomeDocumented", event.target.checked)} /><span><strong>Income is documented</strong><small>The fictional policy can require verification before citing unverified income.</small></span></label></div>}
              {step === "review" && <div className="reviewCard"><div className="reviewFacts"><span>Fictional scenario</span><strong>{dollars(facts.loanAmount)} / {facts.loanTerm} months</strong><p>{dollars(facts.annualIncome)} income · {facts.creditScore} score · {facts.utilization}% utilization · {dti}% DTI</p></div><div className="reviewCompare"><span>Audit design</span><strong>Baseline × platform</strong><p>All six audit families · k=5 · up to $1 per configuration.</p></div><label className="scopeCheck"><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} /><span>I confirm every value is fictional and I understand this cannot evaluate a real applicant or provide a lending, credit, legal, or compliance outcome.</span></label>{message && <p className={submission === "error" ? "submissionMessage error" : "submissionMessage"}>{message}</p>}</div>}
            </div>
          </div>
        )}

        {submission !== "launched" && <footer className="studioControls"><button type="button" className="backButton" disabled={currentStep === 0} onClick={() => setStep(steps[currentStep - 1])}>Back</button>{step !== "review" ? <button type="button" className="nextButton" onClick={() => setStep(steps[currentStep + 1])}>Continue <span>→</span></button> : <button type="button" className="nextButton" disabled={!accepted || submission === "submitting"} onClick={requestPreflight}>{submission === "submitting" ? "Creating preflight…" : "Create bounded preflight"} <span>→</span></button>}</footer>}
      </div>
    </section>
  );
}

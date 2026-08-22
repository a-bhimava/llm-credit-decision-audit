"use client";

import { useEffect, useMemo, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import type { AuditIntake, EmploymentStatus, PublicRecordKind } from "@/lib/audit/contracts";

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


const DEMO_LOGS = [
  "Bootstrapping agent environments...",
  "Loading baseline credit policy...",
  "Verifying LLM context limits...",
  "Initializing parallel evaluation workers...",
  "Running control variants...",
  "Injecting synthetic adversarial profiles...",
];

function AuditVisualizer({ liveProgress }: { liveProgress: string }) {
  const [logs, setLogs] = useState<string[]>([]);
  const logEndRef = useRef<HTMLDivElement>(null);
  const [activeNode, setActiveNode] = useState(0);

  useEffect(() => {
    if (liveProgress) {
      setLogs((prev) => [...prev, '[SYSTEM] ' + liveProgress]);
    }
  }, [liveProgress]);

  useEffect(() => {
    let index = 0;
    const interval = setInterval(() => {
      if (index < DEMO_LOGS.length) {
        setLogs((prev) => [...prev, '[WORKER-' + Math.floor(Math.random() * 4) + '] ' + DEMO_LOGS[index]]);
        setActiveNode(index % 3);
        index++;
      }
    }, 1500);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "2rem", width: "100%", maxWidth: "600px", margin: "0 auto", marginTop: "2rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "1.5rem", background: "rgba(255,255,255,0.05)", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.1)" }}>
        {["Orchestrator", "Policy Agent", "Evaluator"].map((node, i) => (
          <div key={node} style={{ 
            padding: "0.75rem 1.25rem", 
            borderRadius: "6px", 
            background: activeNode === i ? "var(--cyan)" : "rgba(255,255,255,0.1)",
            color: activeNode === i ? "var(--ink-dark)" : "white",
            transition: "all 0.3s ease",
            boxShadow: activeNode === i ? "0 0 15px var(--cyan)" : "none",
            fontWeight: "600",
            fontSize: "0.85rem",
            fontFamily: "var(--mono)"
          }}>
            {node}
          </div>
        ))}
      </div>
      <div style={{ background: "rgba(0,0,0,0.6)", color: "var(--cyan)", fontFamily: "var(--mono)", padding: "1.25rem", borderRadius: "8px", height: "180px", overflowY: "auto", fontSize: "0.8rem", border: "1px solid rgba(255,255,255,0.1)", textAlign: "left" }}>
        {logs.map((log, i) => (
          <div key={i} style={{ marginBottom: "0.5rem", opacity: i === logs.length - 1 ? 1 : 0.7 }}>
            <span style={{ color: "#888" }}>{new Date().toISOString().split('T')[1].slice(0, 8)}</span> {log}
          </div>
        ))}
        <div ref={logEndRef} />
      </div>
    </div>
  );
}

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
  const currentStep = steps.indexOf(step);
  useEffect(() => {
    if (submission === "launched" && jobId && !isDone) {
      const interval = setInterval(async () => {
        try {
          const res = await fetch(`/api/audits/${jobId}`);
          if (res.ok) {
            const data = await res.json();
            if (data.progress && data.progress.message) {
              setLiveProgress(data.progress.message);
            }
            if (data.progress && (data.progress.status === "complete" || data.progress.status === "failed")) {
              setIsDone(true);
              clearInterval(interval);
            }
          }
        } catch (e) {}
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
        <div className="conversationBody">
          {submission === "launched" ? (
            <div className="launchReaction">
              <div className="launchGradient"></div>
              <div className="launchContent" style={{ width: '100%', zIndex: 10 }}>
                <h2 style={{ textAlign: 'center', margin: 0 }}>Executing Audit Workflow</h2>
                <AuditVisualizer liveProgress={liveProgress} />
              </div>
            </div>
          ) : (
            <>
          <div className="assistantMessage"><span className="assistantAvatar">A</span><div><p className="messageMeta">AUDIT GUIDE</p><h1>{step === "income" ? "Start with a fictional borrowing request." : step === "credit" ? "Now add a synthetic credit profile." : step === "history" ? "Capture the observable credit history." : step === "employment" ? "Finish the policy-relevant employment facts." : "Review the bounded experiment before it runs."}</h1><p>{step === "income" ? "Use only made-up values. This studio never asks for a person’s name, contact details, account identifiers, SSN, free-text notes, or files." : step === "credit" ? "These are financial variables the synthetic policy can evaluate. Presentation variants are generated by the audit; you do not enter demographic information." : step === "history" ? "Public-record categories are deliberately coarse. Do not enter case numbers, addresses, names, or any identifying details." : step === "employment" ? "The tool-guided configuration will use the same fictional facts as the baseline. It changes the decision environment, not the applicant." : "This is an educational diagnostic, not a lending decision, credit advice, a compliance determination, or a population-level fairness result."}</p></div></div>

          <div className="userComposer">
            {step === "income" && <div className="fieldGrid"><NumberInput label="Annual income" value={facts.annualIncome} min={0} max={600000} onChange={(value) => update("annualIncome", value)} suffix="USD / year" /><NumberInput label="Monthly debt payments" value={facts.monthlyDebt} min={0} max={50000} onChange={(value) => update("monthlyDebt", value)} suffix="USD / month" /><NumberInput label="Requested amount" value={facts.loanAmount} min={1000} max={100000} onChange={(value) => update("loanAmount", value)} suffix="USD" /><NumberInput label="Requested term" value={facts.loanTerm} min={12} max={60} onChange={(value) => update("loanTerm", value)} suffix="months" /><div className="derivedMetric"><span>Debt-to-income</span><strong>{dti}%</strong><small>Derived locally from the fictional values above.</small></div></div>}
            {step === "credit" && <div className="fieldGrid"><NumberInput label="Credit score" value={facts.creditScore} min={300} max={850} onChange={(value) => update("creditScore", value)} /><NumberInput label="Revolving utilization" value={facts.utilization} min={0} max={100} onChange={(value) => update("utilization", value)} suffix="%" /><NumberInput label="30–59 day delinquencies" value={facts.delinq30} min={0} max={20} onChange={(value) => update("delinq30", value)} suffix="in 24 months" /><NumberInput label="60–89 day delinquencies" value={facts.delinq60} min={0} max={20} onChange={(value) => update("delinq60", value)} suffix="in 24 months" /><NumberInput label="90+ day delinquencies" value={facts.delinq90} min={0} max={20} onChange={(value) => update("delinq90", value)} suffix="in 24 months" /></div>}
            {step === "history" && <div className="fieldGrid"><label className="studioField"><span>Public record category</span><div><select value={facts.publicRecordKind} onChange={(event) => update("publicRecordKind", event.target.value as PublicRecordKind)}><option value="NONE">None</option><option value="COLLECTION">Collection</option><option value="TAX_LIEN">Tax lien</option><option value="JUDGMENT">Judgment</option><option value="BANKRUPTCY_CH7">Bankruptcy Chapter 7</option><option value="BANKRUPTCY_CH13">Bankruptcy Chapter 13</option></select></div></label>{facts.publicRecordKind !== "NONE" && <NumberInput label="Months since record" value={facts.publicRecordMonthsAgo} min={0} max={240} onChange={(value) => update("publicRecordMonthsAgo", value)} suffix="months" />}<NumberInput label="Hard inquiries" value={facts.inquiries} min={0} max={20} onChange={(value) => update("inquiries", value)} suffix="in 6 months" /></div>}
            {step === "employment" && <div className="fieldGrid"><NumberInput label="Employment tenure" value={facts.employmentMonths} min={0} max={600} onChange={(value) => update("employmentMonths", value)} suffix="months" /><label className="studioField"><span>Employment status</span><div><select value={facts.employmentStatus} onChange={(event) => update("employmentStatus", event.target.value as EmploymentStatus)}><option value="FULL_TIME">Full time</option><option value="PART_TIME">Part time</option><option value="SELF_EMPLOYED">Self-employed</option><option value="CONTRACT">Contract</option><option value="RETIRED">Retired</option><option value="UNEMPLOYED">Unemployed</option></select></div></label><label className="choiceRow"><input type="checkbox" checked={facts.incomeDocumented} onChange={(event) => update("incomeDocumented", event.target.checked)} /><span><strong>Income is documented</strong><small>The fictional policy can require verification before citing unverified income.</small></span></label></div>}
            {step === "review" && <div className="reviewCard"><div className="reviewFacts"><span>Fictional scenario</span><strong>{dollars(facts.loanAmount)} / {facts.loanTerm} months</strong><p>{dollars(facts.annualIncome)} income · {facts.creditScore} score · {facts.utilization}% utilization · {dti}% DTI</p></div><div className="reviewCompare"><span>Audit design</span><strong>Baseline × platform</strong><p>All six audit families · k=5 · up to $1 per configuration.</p></div><label className="scopeCheck"><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} /><span>I confirm every value is fictional and I understand this cannot evaluate a real applicant or provide a lending, credit, legal, or compliance outcome.</span></label>{message && <p className={submission === "error" ? "submissionMessage error" : "submissionMessage"}>{message}</p>}</div>}
          </div>
            </>
          )}
        </div>
        {submission !== "launched" && <footer className="studioControls"><button type="button" className="backButton" disabled={currentStep === 0} onClick={() => setStep(steps[currentStep - 1])}>Back</button>{step !== "review" ? <button type="button" className="nextButton" onClick={() => setStep(steps[currentStep + 1])}>Continue <span>→</span></button> : <button type="button" className="nextButton" disabled={!accepted || submission === "submitting"} onClick={requestPreflight}>{submission === "submitting" ? "Creating preflight…" : "Create bounded preflight"} <span>→</span></button>}</footer>}
      </div>
    </section>
  );
}

"use client";

import { useEffect, useMemo, useState } from "react";
import { AnimatePresence } from "framer-motion";
import {
  documents, fieldDefinitions, fieldIds, fixtureReview, validateReview,
  type CaseReview, type DocumentId, type FieldId,
} from "@/lib/reasontrace/demo";
import { caseDefinitions, getCaseDefinition } from "@/lib/reasontrace/cases";
import { applyLocalReviewChange } from "@/lib/reasontrace/local-review";
import { GlareHover } from "@/components/react-bits/glare-hover";
import { WorkflowStepper } from "@/components/react-bits/workflow-stepper";
import { AnimatedContent } from "@/components/react-bits/animated-content";
import { documentTabId } from "@/components/reasontrace-document-tabs";
import { ReasonTraceAuditChecks, type AuditCheck } from "@/components/reasontrace-audit-checks";
import { ReasonTraceCasePicker } from "@/components/reasontrace-case-picker";
import { ReasonTraceReviewHistory, type ReviewEvent } from "@/components/reasontrace-review-history";
import { ReasonTraceFieldReview } from "@/components/reasontrace-field-review";
import { ReasonTraceDocumentReview } from "@/components/reasontrace-document-review";

type AuditResult = {
  mode: string; policy: string; agent: string;
  decision: { outcome: string; reasons: string[]; trajectory_id: string };
  oracle: { outcome: string; breached_codes: string[] };
  supplied_synthetic_facts: Record<string, unknown>; checks: AuditCheck[];
};
type CaseDetail = { case: { case_label: string }; review: CaseReview; documents: { id: string; kind: string; previewUrl: string | null }[];
  observations: { id: string; field_key: string }[]; reviewEvents: ReviewEvent[];
  currentRun?: { id: string; status: string; agent_kind: string; result: AuditResult | null } | null };

async function fetchCase(id: string): Promise<CaseDetail> {
  const response = await fetch(`/api/reasontrace/cases/${id}`, { cache: "no-store" });
  const detail = await response.json();
  if (!response.ok) throw new Error(detail.error || "The private case could not be loaded.");
  return detail;
}

const pretty = (code: string) => code.replaceAll("_", " ").toLowerCase();

export function ReasonTrace({ localFixtures = false }: { localFixtures?: boolean }) {
  const [caseId, setCaseId] = useState<string | null>(null);
  const [caseLabel, setCaseLabel] = useState(caseDefinitions[0].label);
  const [availableCases, setAvailableCases] = useState<{ id: string; label: string }[]>([]);
  const [caseError, setCaseError] = useState("");
  const [documentUrls, setDocumentUrls] = useState<Partial<Record<DocumentId, string>>>({});
  const [review, setReview] = useState<CaseReview>(() => fixtureReview());
  const [savedReview, setSavedReview] = useState<CaseReview | null>(null);
  const [reviewEvents, setReviewEvents] = useState<ReviewEvent[]>([]);
  const [activeDoc, setActiveDoc] = useState<DocumentId>("credit-report");
  const [agent, setAgent] = useState<"faithful" | "laundering">("laundering");
  const [auditResult, setAuditResult] = useState<AuditResult | null>(null);
  const [busy, setBusy] = useState<"extract" | "audit" | "review" | "case" | null>(null);
  const [message, setMessage] = useState("");
  const definition = getCaseDefinition(caseLabel) ?? caseDefinitions[0];
  const problems = useMemo(() => validateReview(review, definition.applicantName, definition.creditScore).problems,
    [review, definition.applicantName, definition.creditScore]);
  const reviewedDocuments = documents.filter(doc => review.documents[doc.id].included && review.documents[doc.id].reviewed).length;
  const confirmedFields = fieldIds.filter(id => {
    const field = review.fields[id];
    return field.confirmed && review.documents[field.documentId].included && review.documents[field.documentId].reviewed;
  }).length;

  function showSourceDocument(id: DocumentId) {
    setActiveDoc(id);
    requestAnimationFrame(() => document.getElementById(documentTabId(id))?.focus());
  }

  function applyLocalCase(label: string, selectedDocument: DocumentId = "credit-report") {
    const item = getCaseDefinition(label);
    if (!item) throw new Error("Unknown synthetic case.");
    let saved: { review?: CaseReview; reviewEvents?: ReviewEvent[]; auditResult?: AuditResult; agent?: "faithful" | "laundering" } = {};
    try { saved = JSON.parse(window.localStorage.getItem(`reasontrace-local-${label}`) || "{}"); }
    catch { saved = {}; }
    const candidate = saved.review;
    const validShape = candidate?.documents && candidate?.fields && documents.every(doc => candidate.documents[doc.id]) &&
      fieldIds.every(id => candidate.fields[id]) && candidate.extractionSource === "fixture";
    const current = validShape ? candidate : fixtureReview(item);
    setCaseId(label); setCaseLabel(label);
    setReview(current); setSavedReview(current);
    setReviewEvents(Array.isArray(saved.reviewEvents) ? saved.reviewEvents : []);
    setAuditResult(saved.auditResult ?? null);
    setAgent(saved.agent === "faithful" || saved.agent === "laundering" ? saved.agent : item.agent);
    setActiveDoc(selectedDocument);
    setDocumentUrls(Object.fromEntries(documents.map(doc => [doc.id,
      `/api/reasontrace/local/document?case=${encodeURIComponent(label)}&document=${encodeURIComponent(doc.id)}`,
    ])) as Record<DocumentId, string>);
  }

  function persistLocal(current: CaseReview, events: ReviewEvent[], result: AuditResult | null,
    selectedAgent: "faithful" | "laundering" = agent) {
    try {
      window.localStorage.setItem(`reasontrace-local-${caseLabel}`, JSON.stringify({
        review: current, reviewEvents: events, auditResult: result, agent: selectedAgent,
      }));
    } catch { setMessage("Browser storage is unavailable; this review will last only until the page closes."); }
  }

  function applyDetail(id: string, detail: CaseDetail, selectedDocument: DocumentId = "credit-report") {
    const item = getCaseDefinition(detail.case.case_label);
    if (!item) throw new Error("Unknown synthetic case returned by the server.");
    const kinds: Record<string, DocumentId> = {
      pay_statement: "pay-stub", bank_statement: "bank-statement", credit_summary: "credit-report",
    };
    const urls: Partial<Record<DocumentId, string>> = {};
    for (const doc of detail.documents) {
      if (kinds[doc.kind] && typeof doc.previewUrl === "string") urls[kinds[doc.kind]] = doc.previewUrl;
    }
    if (Object.keys(urls).length !== documents.length) throw new Error("One or more private document previews are unavailable.");
    setCaseId(id); setCaseLabel(item.label); setDocumentUrls(urls);
    setReview(detail.review); setSavedReview(detail.review);
    const keyByObservation = new Map(detail.observations.map(row => [row.id, row.field_key]));
    const documentById = new Map(detail.documents.map(doc => [doc.id, kinds[doc.kind]]));
    setReviewEvents(detail.reviewEvents.map(event => {
      const key = event.observation_id ? keyByObservation.get(event.observation_id) : undefined;
      const fieldId = key && key in fieldDefinitions ? key as FieldId : undefined;
      const after = event.after_value && typeof event.after_value === "object" ? event.after_value as Record<string, unknown> : {};
      const docId = typeof after.document_id === "string" ? documentById.get(after.document_id) : undefined;
      return { ...event, fieldId, subject: fieldId ? fieldDefinitions[fieldId].label
        : key === "applicant_name" ? "Applicant name"
          : docId ? documents.find(doc => doc.id === docId)?.title : undefined };
    }));
    setActiveDoc(selectedDocument);
    setAgent(detail.currentRun?.agent_kind === "faithful" || detail.currentRun?.agent_kind === "laundering"
      ? detail.currentRun.agent_kind : item.agent);
    setAuditResult(detail.currentRun?.status === "completed" ? detail.currentRun.result : null);
  }

  useEffect(() => {
    let active = true;
    async function seed() {
      try {
        if (localFixtures) {
          const requested = new URLSearchParams(window.location.search).get("case");
          const chosen = getCaseDefinition(requested ?? "") ?? caseDefinitions[0];
          if (active) {
            setAvailableCases(caseDefinitions.map(item => ({ id: item.label, label: item.label })));
            applyLocalCase(chosen.label);
          }
          return;
        }
        let response = await fetch("/api/reasontrace/cases", { cache: "no-store" });
        let created = await response.json();
        const existing = Array.isArray(created.cases) ? created.cases.filter(
          (entry: { case_label: string }) => getCaseDefinition(entry.case_label),
        ) : [];
        if (response.ok && existing.length === caseDefinitions.length) {
          created = { cases: existing.map((entry: { id: string; case_label: string }) => ({ id: entry.id, label: entry.case_label })) };
        } else {
          response = await fetch("/api/reasontrace/cases", { method: "POST", cache: "no-store" });
          created = await response.json();
        }
        if (!response.ok || !Array.isArray(created.cases) || created.cases.length !== caseDefinitions.length) {
          throw new Error(created.error || "The five private Supabase cases could not be prepared.");
        }
        const requested = new URLSearchParams(window.location.search).get("case");
        const chosen = created.cases.find((item: { label: string }) => item.label === requested) ?? created.cases[0];
        const detail = await fetchCase(chosen.id);
        if (active) {
          setAvailableCases(created.cases);
          applyDetail(chosen.id, detail);
        }
      } catch (error) {
        if (active) setCaseError(error instanceof Error ? error.message : "The private case is unavailable.");
      }
    }
    void seed();
    return () => { active = false; };
  }, [localFixtures]);

  function updateReview(next: CaseReview) { setReview(next); setAuditResult(null); setMessage(""); }
  function updateField(id: FieldId, changes: Partial<CaseReview["fields"][FieldId]>) {
    updateReview({ ...review, fields: { ...review.fields, [id]: { ...review.fields[id], ...changes } } });
  }
  async function reloadSavedCase() {
    if (!caseId) return;
    if (localFixtures) { applyLocalCase(caseLabel, activeDoc); return; }
    const detail = await fetchCase(caseId);
    applyDetail(caseId, detail, activeDoc);
  }
  async function switchCase(id: string) {
    if (busy || id === caseId) return;
    setBusy("case"); setMessage("");
    try {
      if (localFixtures) {
        applyLocalCase(id);
        const url = new URL(window.location.href);
        url.searchParams.set("case", id);
        window.history.replaceState(null, "", url);
        return;
      }
      const detail = await fetchCase(id);
      applyDetail(id, detail);
      const url = new URL(window.location.href);
      url.searchParams.set("case", detail.case.case_label);
      window.history.replaceState(null, "", url);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Case could not be loaded"); }
    finally { setBusy(null); }
  }
  async function saveReview(change: Record<string, unknown>) {
    if (!caseId) return;
    if (localFixtures) {
      const changed = applyLocalReviewChange(review, savedReview ?? review, change, definition.applicantName);
      if (!changed) { setMessage("This local fixture action is unavailable."); return; }
      const events = [...reviewEvents, { id: `${Date.now()}-${reviewEvents.length}`, observation_id: null,
        action: String(change.kind), before_value: changed.beforeValue, after_value: changed.afterValue,
        created_at: new Date().toISOString() }];
      setReview(changed.visible); setSavedReview(changed.persisted); setReviewEvents(events); setAuditResult(null); setMessage("");
      persistLocal(changed.persisted, events, null);
      return;
    }
    setBusy("review"); setMessage("");
    try {
      const response = await fetch(`/api/reasontrace/cases/${caseId}/review`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(change), cache: "no-store",
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Review could not be saved");
      await reloadSavedCase();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Review could not be saved"); }
    finally { setBusy(null); }
  }
  async function extractLive() {
    setBusy("extract"); setMessage("");
    try {
      const response = await fetch(`/api/reasontrace/cases/${caseId}/extract`, { method: "POST", cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Extraction failed");
      await reloadSavedCase();
      setMessage("Interfaze returned candidate values. Check the source pages, then confirm each value.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Extraction failed"); }
    finally { setBusy(null); }
  }
  async function runAudit() {
    if (problems.length) return;
    setBusy("audit"); setMessage(""); setAuditResult(null);
    try {
      const response = await fetch(localFixtures ? "/api/reasontrace/local/audit" : `/api/reasontrace/cases/${caseId}/audits`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(localFixtures ? { caseLabel, review, agent } : { agent }), cache: "no-store",
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.problems?.join(" ") || body.detail || body.error || "Audit failed");
      setAuditResult(body);
      if (localFixtures) persistLocal(review, reviewEvents, body, agent);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Audit failed"); }
    finally { setBusy(null); }
  }

  if (!caseId) return <main className="rt"><section className="rt-hero">
    <div className="rt-kicker">ReasonTrace / private synthetic cases</div>
    <h1>{caseError ? "Case setup needs attention" : "Preparing your private case…"}</h1>
    <p role="status">{caseError || (localFixtures ? "Loading five saved fictional document packets." : "Preparing five fictional document packets in Supabase private Storage.")}</p>
  </section></main>;

  return <main className="rt">
    <section className="rt-hero">
      <div className="rt-kicker"><span className="rt-live-dot" /> ReasonTrace / synthetic case {caseLabel}</div>
      <h1>Can we trust the reason<br />behind this credit decision?</h1>
      <p>Trace three reviewed values from fictional documents into a real paired reason-validity test. The audit engine uses the repository’s unchanged <strong>Meridian Personal Loan</strong> policy.</p>
      {localFixtures && <p className="rt-local-notice">Local saved-fixture mode · no Supabase sign-in or Interfaze request</p>}
      <WorkflowStepper reviewedDocuments={reviewedDocuments} confirmedFields={confirmedFields}
        ready={problems.length === 0} audited={auditResult !== null} />
    </section>

    <ReasonTraceCasePicker currentLabel={caseLabel} availableCases={availableCases}
      busy={busy !== null} onSelect={id => { void switchCase(id); }} />

    <div className="rt-toolbar">
      <div><strong>Extraction mode</strong><span>{localFixtures ? "Saved synthetic extraction; review progress stays in this browser." : "Fixed fixture is reproducible. Live mode calls Interfaze from the server."}</span></div>
      <div className="rt-toolbar-actions">
        <button type="button" onClick={() => {
          if (review.extractionSource === "interfaze") void saveReview({ kind: "mode", mode: "fixture" });
          else void reloadSavedCase().then(() => setMessage("Reloaded the saved synthetic case.")).catch(error => setMessage(error instanceof Error ? error.message : "Reload failed"));
        }} disabled={busy !== null}>{review.extractionSource === "interfaze" ? "Use saved fixture" : "Reload saved case"}</button>
        {!localFixtures && <button type="button" className="rt-outline" onClick={extractLive} disabled={busy !== null}>{busy === "extract" ? "Reading documents…" : "Run with Interfaze"}</button>}
      </div>
    </div>
    {message && <p className="rt-message" role="status">{message}</p>}

    <div className="rt-workspace">
      <ReasonTraceDocumentReview activeDoc={activeDoc} onSelectDocument={setActiveDoc}
        documentUrls={documentUrls} review={review} savedReview={savedReview}
        applicantName={definition.applicantName} initialExcludedDocument={definition.initialExcludedDocument}
        busy={busy !== null}
        onToggleIncluded={(id, included) => {
          void saveReview({ kind: "document", documentId: id, included, reviewed: false });
        }}
        onToggleReviewed={(id, reviewed) => {
          void saveReview({ kind: "document", documentId: id, reviewed });
        }}
        onApplicantNameChange={(id, value) => updateReview({ ...review, documents: { ...review.documents,
          [id]: { ...review.documents[id], applicantName: value } } })}
        onSaveApplicantName={(id, value) => {
          void saveReview({ kind: "applicant_name", documentId: id, value });
        }}
        onRefreshPreview={reloadSavedCase} />

      <section className="rt-panel rt-fact-panel" aria-labelledby="rt-fact-heading">
        <div className="rt-panel-heading"><span>02 / REVIEW</span><h2 id="rt-fact-heading" tabIndex={-1}>Confirm the facts</h2><p>Corrections preserve the original extraction. No value enters the audit unconfirmed.</p></div>
        <div className="rt-source-tag">Candidate source: {review.extractionSource === "fixture" ? "saved synthetic extraction" : "live Interfaze response"}</div>
        {definition.fixtureCreditScore !== definition.creditScore && review.extractionSource === "fixture" &&
          <p className="rt-injected-note">This saved fixture deliberately injects an extraction error. Compare the credit score with its page before confirming it.</p>}
        {fieldIds.map(id => <ReasonTraceFieldReview key={id} id={id} field={review.fields[id]}
          savedValue={savedReview?.fields[id].value}
          sourceReady={review.documents[review.fields[id].documentId].included &&
            review.documents[review.fields[id].documentId].reviewed}
          busy={busy !== null}
          onValueChange={value => updateField(id, { value, confirmed: false })}
          onSaveCorrection={value => { void saveReview({ kind: "field", fieldId: id, value }); }}
          onToggleConfirmation={(value, confirmed) => {
            void saveReview({ kind: "field", fieldId: id, value, confirmed });
          }}
          onShowSource={showSourceDocument} />)}
        <div className="rt-supplied"><strong>Other policy inputs</strong><p>Loan amount, term, credit history, employment and other fields are supplied synthetic facts in the existing test policy. They are <em>not</em> attributed to these three documents.</p></div>
        <ReasonTraceReviewHistory key={caseLabel} events={reviewEvents} />
      </section>

      <section className="rt-panel rt-audit-panel" aria-labelledby="rt-audit-heading">
        <div className="rt-panel-heading"><span>03 / TEST</span><h2 id="rt-audit-heading" tabIndex={-1}>Audit the explanation</h2><p>The Python harness runs matched counterfactuals. This is a known-answer scripted control, not a finding about a live model.</p></div>
        <div className={problems.length ? "rt-readiness blocked" : "rt-readiness ready"}>
          <strong>{problems.length ? "Needs review" : "Ready for audit"}</strong>
          {problems.length ? <ul>{problems.map(problem => <li key={problem}>{problem}</li>)}</ul> : <p>All three documents and decision-relevant extracted values are confirmed.</p>}
        </div>
        <label className="rt-agent-select">Scripted agent control
          <select value={agent} onChange={e => { setAgent(e.target.value as typeof agent); setAuditResult(null); }}>
            <option value="laundering">Planted reason-laundering defect</option>
            <option value="faithful">Faithful policy control</option>
          </select>
        </label>
        <GlareHover className="rt-run-glare">
          <button className="rt-run" type="button" disabled={problems.length > 0 || busy !== null} onClick={runAudit}>{busy === "audit" ? "Running paired tests…" : "Run reason-validity audit →"}</button>
        </GlareHover>
        <AnimatePresence mode="wait">
        {auditResult && <AnimatedContent key={`${caseLabel}-${auditResult.decision.trajectory_id}`} className="rt-results" ariaLive="polite">
          <div className="rt-result-summary"><span>Scripted result</span><h3>{auditResult.decision.outcome}</h3><p>Agent stated: <strong>{auditResult.decision.reasons.map(pretty).join(", ") || "no adverse reason"}</strong></p><p>Policy oracle: <strong>{auditResult.oracle.breached_codes.map(pretty).join(", ") || "no breached rule"}</strong></p></div>
          <ReasonTraceAuditChecks checks={auditResult.checks} />
          <p className="rt-result-note">These controls test the audit machinery against known behavior. They do not establish a provider or lender violation.</p>
        </AnimatedContent>}
        </AnimatePresence>
      </section>
    </div>
    <aside className="rt-boundary"><strong>Product boundary</strong><p>Packet readiness and reason validity are separate decisions. This synthetic evaluation never approves a loan, issues an adverse-action notice, or certifies compliance.</p></aside>
  </main>;
}

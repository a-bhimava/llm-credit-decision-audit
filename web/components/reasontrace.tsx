"use client";

import { useEffect, useMemo, useState } from "react";
import {
  documents, fieldDefinitions, fieldIds, fixtureReview, validateReview,
  type CaseReview, type DocumentId, type FieldId, type ReviewIssue,
} from "@/lib/reasontrace/demo";
import { caseDefinitions, getCaseDefinition } from "@/lib/reasontrace/cases";
import { applyLocalReviewChange } from "@/lib/reasontrace/local-review";
import { auditMatchesReview } from "@/lib/reasontrace/audit-result";
import { WorkflowStepper } from "@/components/react-bits/workflow-stepper";
import { documentTabId } from "@/components/reasontrace-document-tabs";
import { ReasonTraceCasePicker } from "@/components/reasontrace-case-picker";
import type { ReviewEvent } from "@/components/reasontrace-review-history";
import { ReasonTraceDocumentReview } from "@/components/reasontrace-document-review";
import { ReasonTraceFactPanel } from "@/components/reasontrace-fact-panel";
import { ReasonTraceExtractionToolbar } from "@/components/reasontrace-extraction-toolbar";
import { ReasonTraceAuditPanel, type AuditResult, type ScriptedAgent } from "@/components/reasontrace-audit-panel";

type CaseDetail = { case: { case_label: string }; review: CaseReview; documents: { id: string; kind: string; previewUrl: string | null }[];
  observations: { id: string; field_key: string }[]; reviewEvents: ReviewEvent[];
  currentRun?: { id: string; status: string; agent_kind: string; result: AuditResult | null } | null };

async function fetchCase(id: string): Promise<CaseDetail> {
  const response = await fetch(`/api/reasontrace/cases/${id}`, { cache: "no-store" });
  const detail = await response.json();
  if (!response.ok) throw new Error(detail.error || "The private case could not be loaded.");
  return detail;
}

const localCaseStorageKey = (label: string) => `reasontrace-local-${label}`;

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
  const [agent, setAgent] = useState<ScriptedAgent>("laundering");
  const [auditResult, setAuditResult] = useState<AuditResult | null>(null);
  const [auditError, setAuditError] = useState("");
  const [busy, setBusy] = useState<"extract" | "audit" | "review" | "case" | null>(null);
  const [message, setMessage] = useState("");
  const definition = getCaseDefinition(caseLabel) ?? caseDefinitions[0];
  const validation = useMemo(() => validateReview(review, definition.applicantName, definition.creditScore),
    [review, definition.applicantName, definition.creditScore]);
  const problems = validation.problems;
  const reviewedDocuments = documents.filter(doc => review.documents[doc.id].included && review.documents[doc.id].reviewed).length;
  const confirmedFields = fieldIds.filter(id => {
    const field = review.fields[id];
    return field.confirmed && review.documents[field.documentId].included && review.documents[field.documentId].reviewed;
  }).length;

  function showSourceDocument(id: DocumentId) {
    setActiveDoc(id);
    requestAnimationFrame(() => document.getElementById(documentTabId(id))?.focus());
  }

  function navigateToIssue(issue: ReviewIssue) {
    const target = issue.target;
    if (!target) return;
    if (target.kind === "document") setActiveDoc(target.id);
    requestAnimationFrame(() => {
      const id = target.kind === "field" ? `rt-${target.id}`
        : target.control === "included" ? "rt-document-included"
          : target.control === "reviewed" ? "rt-document-reviewed" : "rt-applicant-name";
      const element = document.getElementById(id);
      if (!element) return;
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      element.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "center" });
      element.focus({ preventScroll: true });
    });
  }

  function applyLocalCase(label: string, selectedDocument: DocumentId = "credit-report",
    ignoreSaved = false) {
    const item = getCaseDefinition(label);
    if (!item) throw new Error("Unknown synthetic case.");
    let saved: { review?: CaseReview; reviewEvents?: ReviewEvent[]; auditResult?: AuditResult; agent?: ScriptedAgent } = {};
    if (!ignoreSaved) {
      try { saved = JSON.parse(window.localStorage.getItem(localCaseStorageKey(label)) || "{}"); }
      catch { saved = {}; }
    }
    const candidate = saved.review;
    const validShape = candidate?.documents && candidate?.fields && documents.every(doc => candidate.documents[doc.id]) &&
      fieldIds.every(id => candidate.fields[id]) && candidate.extractionSource === "fixture";
    const current = validShape ? candidate : fixtureReview(item);
    setCaseId(label); setCaseLabel(label);
    setReview(current); setSavedReview(current);
    setReviewEvents(Array.isArray(saved.reviewEvents) ? saved.reviewEvents : []);
    setAuditResult(saved.auditResult && auditMatchesReview(current, saved.auditResult)
      ? saved.auditResult : null);
    setAuditError("");
    setAgent(saved.agent === "faithful" || saved.agent === "laundering" ? saved.agent : item.agent);
    setActiveDoc(selectedDocument);
    setDocumentUrls(Object.fromEntries(documents.map(doc => [doc.id,
      `/api/reasontrace/local/document?case=${encodeURIComponent(label)}&document=${encodeURIComponent(doc.id)}`,
    ])) as Record<DocumentId, string>);
  }

  function persistLocal(current: CaseReview, events: ReviewEvent[], result: AuditResult | null,
    selectedAgent: ScriptedAgent = agent) {
    try {
      window.localStorage.setItem(localCaseStorageKey(caseLabel), JSON.stringify({
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
    setAuditResult(detail.currentRun?.status === "completed" &&
      auditMatchesReview(detail.review, detail.currentRun.result) ? detail.currentRun.result : null);
    setAuditError("");
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

  function updateReview(next: CaseReview) { setReview(next); setAuditResult(null); setAuditError(""); setMessage(""); }
  function updateField(id: FieldId, changes: Partial<CaseReview["fields"][FieldId]>) {
    updateReview({ ...review, fields: { ...review.fields, [id]: { ...review.fields[id], ...changes } } });
  }
  async function reloadSavedCase() {
    if (!caseId) return;
    if (localFixtures) { applyLocalCase(caseLabel, activeDoc); return; }
    const detail = await fetchCase(caseId);
    applyDetail(caseId, detail, activeDoc);
  }
  function restartLocalCase() {
    if (!localFixtures) return;
    let stored = true;
    try { window.localStorage.removeItem(localCaseStorageKey(caseLabel)); }
    catch { stored = false; }
    applyLocalCase(caseLabel, "credit-report", true);
    setMessage(stored ? `Restarted ${caseLabel} from its fictional source packet.`
      : "The case restarted for this session, but browser storage could not be cleared. Reloading may restore the earlier review.");
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
      setReview(changed.visible); setSavedReview(changed.persisted); setReviewEvents(events); setAuditResult(null); setAuditError(""); setMessage("");
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
    setBusy("audit"); setMessage(""); setAuditResult(null); setAuditError("");
    try {
      const response = await fetch(localFixtures ? "/api/reasontrace/local/audit" : `/api/reasontrace/cases/${caseId}/audits`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(localFixtures ? { caseLabel, review, agent } : { agent }), cache: "no-store",
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.problems?.join(" ") || body.detail || body.error || "Audit failed");
      if (!auditMatchesReview(review, body)) throw new Error("The returned audit facts do not match the confirmed review.");
      setAuditResult(body);
      if (localFixtures) persistLocal(review, reviewEvents, body, agent);
    } catch (error) { setAuditError(error instanceof Error ? error.message : "Audit failed"); }
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

    <ReasonTraceExtractionToolbar localFixtures={localFixtures} caseLabel={caseLabel} source={review.extractionSource}
      busy={busy !== null} extracting={busy === "extract"} message={message}
      onReload={() => {
        void reloadSavedCase().then(() => setMessage("Reloaded the saved synthetic case."))
          .catch(error => setMessage(error instanceof Error ? error.message : "Reload failed"));
      }}
      onUseFixture={() => { void saveReview({ kind: "mode", mode: "fixture" }); }}
      onExtractLive={() => { void extractLive(); }} onRestartCase={restartLocalCase} />

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

      <ReasonTraceFactPanel definition={definition} review={review} savedReview={savedReview}
        reviewEvents={reviewEvents} busy={busy !== null}
        onValueChange={(id, value) => updateField(id, { value, confirmed: false })}
        onSaveCorrection={(id, value) => { void saveReview({ kind: "field", fieldId: id, value }); }}
        onToggleConfirmation={(id, value, confirmed) => {
          void saveReview({ kind: "field", fieldId: id, value, confirmed });
        }}
        onShowSource={showSourceDocument} />

      <ReasonTraceAuditPanel caseLabel={caseLabel} issues={validation.issues} agent={agent}
        onAgentChange={next => { setAgent(next); setAuditResult(null); setAuditError(""); }}
        busy={busy !== null} running={busy === "audit"} onRun={() => { void runAudit(); }}
        onNavigateIssue={navigateToIssue} onShowSource={showSourceDocument}
        review={review} result={auditResult} error={auditError} />
    </div>
    <aside className="rt-boundary"><strong>Product boundary</strong><p>Packet readiness and reason validity are separate decisions. This synthetic evaluation never approves a loan, issues an adverse-action notice, or certifies compliance.</p></aside>
  </main>;
}

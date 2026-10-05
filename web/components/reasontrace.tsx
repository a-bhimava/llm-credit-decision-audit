"use client";

import { useEffect, useMemo, useState } from "react";
import { AnimatePresence } from "framer-motion";
import {
  documents, displayValue, fieldDefinitions, fieldIds, fixtureReview, validateReview,
  type CaseReview, type DocumentId, type FieldId,
} from "@/lib/reasontrace/demo";
import { caseDefinitions, getCaseDefinition } from "@/lib/reasontrace/cases";
import { SpotlightCard } from "@/components/react-bits/spotlight-card";
import { GlareHover } from "@/components/react-bits/glare-hover";
import { WorkflowStepper } from "@/components/react-bits/workflow-stepper";
import { AnimatedContent } from "@/components/react-bits/animated-content";

type Check = {
  check: string; status: string; pair_id: string; effect: number | null;
  observed: Record<string, unknown>; expected: string; notes: string;
  changes: { field: string; before: string; after: string }[];
  base_trajectory_ids: string[]; cf_trajectory_ids: string[];
};
type AuditResult = {
  mode: string; policy: string; agent: string;
  decision: { outcome: string; reasons: string[]; trajectory_id: string };
  oracle: { outcome: string; breached_codes: string[] };
  supplied_synthetic_facts: Record<string, unknown>; checks: Check[];
};
type ReviewEvent = { id: string; observation_id: string | null; action: string; before_value: unknown; after_value: unknown; created_at: string };
type CaseDetail = { case: { case_label: string }; review: CaseReview; documents: { kind: string; previewUrl: string | null }[]; reviewEvents: ReviewEvent[];
  currentRun?: { id: string; status: string; agent_kind: string; result: AuditResult | null } | null };

async function fetchCase(id: string): Promise<CaseDetail> {
  const response = await fetch(`/api/reasontrace/cases/${id}`, { cache: "no-store" });
  const detail = await response.json();
  if (!response.ok) throw new Error(detail.error || "The private case could not be loaded.");
  return detail;
}

const pretty = (code: string) => code.replaceAll("_", " ").toLowerCase();
const names: Record<string, string> = {
  "reason_validity.fabrication": "Unsupported stated reason",
  "reason_validity.joint_sufficiency": "Do the cited reasons jointly explain denial?",
  "reason_validity.necessity_loo": "Is a cited reason independently binding?",
  "reason_validity.omission_scan": "Was a binding reason omitted?",
  "reason_validity.base_inapplicable": "Decision was not adverse",
};

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
  const selected = documents.find(doc => doc.id === activeDoc)!;
  const reviewedDocuments = documents.filter(doc => review.documents[doc.id].included && review.documents[doc.id].reviewed).length;
  const confirmedFields = fieldIds.filter(id => {
    const field = review.fields[id];
    return field.confirmed && review.documents[field.documentId].included && review.documents[field.documentId].reviewed;
  }).length;

  function applyLocalCase(label: string) {
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
    setActiveDoc("credit-report");
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

  function applyDetail(id: string, detail: CaseDetail) {
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
    setReviewEvents(detail.reviewEvents); setActiveDoc("credit-report");
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
    if (localFixtures) { applyLocalCase(caseLabel); return; }
    const detail = await fetchCase(caseId);
    applyDetail(caseId, detail);
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
      let next = review;
      if (change.kind === "document" && typeof change.documentId === "string" && change.documentId in review.documents) {
        const id = change.documentId as DocumentId;
        const included = typeof change.included === "boolean" ? change.included : review.documents[id].included;
        const reviewed = included && (typeof change.reviewed === "boolean" ? change.reviewed : review.documents[id].reviewed);
        next = { ...review, documents: { ...review.documents, [id]: { ...review.documents[id], included, reviewed } } };
      } else if (change.kind === "field" && typeof change.fieldId === "string" && change.fieldId in review.fields) {
        const id = change.fieldId as FieldId;
        const value = typeof change.value === "number" ? change.value : review.fields[id].value;
        next = { ...review, fields: { ...review.fields, [id]: {
          ...review.fields[id], value,
          confirmed: change.confirmed === true,
        } } };
      } else if (change.kind === "applicant_name" && typeof change.documentId === "string" &&
        change.documentId in review.documents && change.value === definition.applicantName) {
        const id = change.documentId as DocumentId;
        next = { ...review, documents: { ...review.documents, [id]: { ...review.documents[id], applicantName: definition.applicantName } } };
      } else { setMessage("This local fixture action is unavailable."); return; }
      const events = [...reviewEvents, { id: `${Date.now()}-${reviewEvents.length}`, observation_id: null,
        action: String(change.kind), before_value: null, after_value: change, created_at: new Date().toISOString() }];
      setReview(next); setSavedReview(next); setReviewEvents(events); setAuditResult(null); setMessage("");
      persistLocal(next, events, null);
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

    <nav className="rt-case-picker" aria-label="Select a synthetic interview case">
      {caseDefinitions.map((item, index) => {
        const match = availableCases.find(entry => entry.label === item.label);
        return <SpotlightCard key={item.label} className={`rt-case-tile${item.label === caseLabel ? " is-active" : ""}`}>
          <button type="button" disabled={!match || busy !== null}
            aria-current={item.label === caseLabel ? "page" : undefined}
            onClick={() => { if (match) void switchCase(match.id); }}>
            <span>CASE {index + 1} / {item.label}</span><strong>{item.title}</strong><small>{item.summary}</small>
          </button>
        </SpotlightCard>;
      })}
    </nav>

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
      <section className="rt-panel rt-doc-panel" aria-labelledby="rt-doc-heading">
        <div className="rt-panel-heading"><span>01 / SOURCE</span><h2 id="rt-doc-heading" tabIndex={-1}>Document packet</h2><p>Select a page to compare its text with extracted values.</p></div>
        <div className="rt-doc-tabs" role="group" aria-label="Synthetic documents">
          {documents.map(doc => <button type="button" key={doc.id} onClick={() => setActiveDoc(doc.id)} className={doc.id === activeDoc ? "is-active" : ""} aria-pressed={doc.id === activeDoc}>{doc.title}</button>)}
        </div>
        <div className="rt-doc-frame"><img src={documentUrls[selected.id]} alt={`${selected.title}, a visibly synthetic one-page document for ${definition.applicantName}`} /></div>
        <div className="rt-doc-footer">
          <div><strong>{selected.title}</strong><span>{selected.type} · page 1 of 1</span></div>
          <label><input type="checkbox" checked={review.documents[selected.id].included} disabled={busy !== null} onChange={e => { void saveReview({ kind: "document", documentId: selected.id, included: e.target.checked, reviewed: false }); }} /> Included{definition.initialExcludedDocument === selected.id ? " (simulated missing page)" : ""}</label>
          <button type="button" disabled={!review.documents[selected.id].included || busy !== null} onClick={() => { void saveReview({ kind: "document", documentId: selected.id, reviewed: !review.documents[selected.id].reviewed }); }}>{review.documents[selected.id].reviewed ? "Reviewed ✓" : "Mark reviewed"}</button>
        </div>
        <div className="rt-name-review">
          <label htmlFor="rt-applicant-name">Extracted applicant name</label>
          <input id="rt-applicant-name" value={review.documents[selected.id].applicantName}
            onChange={event => updateReview({ ...review, documents: { ...review.documents,
              [selected.id]: { ...review.documents[selected.id], applicantName: event.target.value } } })} />
          {savedReview?.documents[selected.id].applicantName !== review.documents[selected.id].applicantName &&
            <button type="button" disabled={!review.documents[selected.id].reviewed || busy !== null}
              onClick={() => { void saveReview({ kind: "applicant_name", documentId: selected.id,
                value: review.documents[selected.id].applicantName }); }}>Save name correction</button>}
        </div>
      </section>

      <section className="rt-panel rt-fact-panel" aria-labelledby="rt-fact-heading">
        <div className="rt-panel-heading"><span>02 / REVIEW</span><h2 id="rt-fact-heading" tabIndex={-1}>Confirm the facts</h2><p>Corrections preserve the original extraction. No value enters the audit unconfirmed.</p></div>
        <div className="rt-source-tag">Candidate source: {review.extractionSource === "fixture" ? "saved synthetic extraction" : "live Interfaze response"}</div>
        {definition.fixtureCreditScore !== definition.creditScore && review.extractionSource === "fixture" &&
          <p className="rt-injected-note">This saved fixture deliberately injects an extraction error. Compare the credit score with its page before confirming it.</p>}
        {fieldIds.map(id => {
          const field = review.fields[id];
          const definition = fieldDefinitions[id];
          return <article className="rt-field" key={id}>
            <div className="rt-field-top"><h3>{definition.label}</h3><span className={field.confirmed ? "rt-status confirmed" : "rt-status"}>{field.confirmed ? "Confirmed" : "Needs confirmation"}</span></div>
            <div className="rt-field-input"><label htmlFor={`rt-${id}`}>Reviewed value</label><input id={`rt-${id}`} type="number" min="0" step={definition.unit === "money" ? ".01" : "1"} value={definition.unit === "money" ? field.value / 100 : field.value} onChange={e => updateField(id, { value: definition.unit === "money" ? Math.round(Number(e.target.value) * 100) : Number(e.target.value), confirmed: false })} /><span>{definition.unit === "money" ? "USD" : "score"}</span></div>
            {field.value !== field.originalValue && <p className="rt-original">Original extraction: {displayValue(id, field.originalValue)}</p>}
            <button className="rt-source-link" type="button" onClick={() => setActiveDoc(field.documentId)}>↗ {documents.find(doc => doc.id === field.documentId)?.title}, p. 1 · “{field.quote}”</button>
            {savedReview?.fields[id].value !== field.value && <button type="button" className="rt-confirm" disabled={busy !== null} onClick={() => { void saveReview({ kind: "field", fieldId: id, value: field.value }); }}>Save correction</button>}
            <button type="button" className="rt-confirm" disabled={!review.documents[field.documentId].included || !review.documents[field.documentId].reviewed || !Number.isSafeInteger(field.value) || busy !== null} onClick={() => { void saveReview({ kind: "field", fieldId: id, value: field.value, confirmed: !field.confirmed }); }}>{field.confirmed ? "Undo confirmation" : "Confirm against page"}</button>
          </article>;
        })}
        <div className="rt-supplied"><strong>Other policy inputs</strong><p>Loan amount, term, credit history, employment and other fields are supplied synthetic facts in the existing test policy. They are <em>not</em> attributed to these three documents.</p></div>
        <details className="rt-review-history"><summary>Review history ({reviewEvents.length})</summary>
          <ol>{reviewEvents.map(event => <li key={event.id}><strong>{event.action.replaceAll("_", " ")}</strong> · {new Date(event.created_at).toLocaleString()}</li>)}</ol>
        </details>
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
          <h3 className="rt-check-title">Paired evidence</h3>
          {auditResult.checks.map(check => <article className="rt-check" key={check.pair_id}>
            <div><span className={`rt-check-status ${check.status}`}>{check.status}</span><h4>{names[check.check] || check.check}</h4></div>
            <p>{check.notes || check.expected}</p>
            {check.changes.length > 0 && <ul>{check.changes.map(change => <li key={change.field}>{change.field.replaceAll("_", " ")}: {change.before} → {change.after}</li>)}</ul>}
            {typeof check.observed.base_approve_rate === "number" && <p className="rt-pair">Base approved {Math.round(check.observed.base_approve_rate * 100)}% → repaired approved {Math.round(Number(check.observed.cf_approve_rate) * 100)}% · {String(check.observed.matched_trials)} matched trials</p>}
            <details><summary>Inspect trace IDs</summary><code>Pair {check.pair_id}<br />Original {check.base_trajectory_ids[0]}<br />Repaired {check.cf_trajectory_ids[0] || "not applicable"}</code></details>
          </article>)}
          <p className="rt-result-note">These controls test the audit machinery against known behavior. They do not establish a provider or lender violation.</p>
        </AnimatedContent>}
        </AnimatePresence>
      </section>
    </div>
    <aside className="rt-boundary"><strong>Product boundary</strong><p>Packet readiness and reason validity are separate decisions. This synthetic evaluation never approves a loan, issues an adverse-action notice, or certifies compliance.</p></aside>
  </main>;
}

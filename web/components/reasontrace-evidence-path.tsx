"use client";

import type { DocumentId, CaseReview } from "@/lib/reasontrace/demo";
import { displayValue } from "@/lib/reasontrace/demo";
import { buildEvidencePath } from "@/lib/reasontrace/evidence-path";
import type { ReviewMemoAudit } from "@/lib/reasontrace/review-memo";
import { summarizeScriptedFinding } from "@/components/reasontrace-finding-summary";

const reasonText = (codes: readonly string[]) => codes.length
  ? codes.map(code => code.replaceAll("_", " ").toLowerCase()).join("; ") : "none";

export function ReasonTraceEvidencePath({ review, result, onShowSource, onInspectCheck }: {
  review: CaseReview;
  result: ReviewMemoAudit;
  onShowSource: (document: DocumentId) => void;
  onInspectCheck: (index: number) => void;
}) {
  const path = buildEvidencePath(review, result);
  const finding = summarizeScriptedFinding(result.checks, result.decision.outcome, result.oracle.outcome);
  const rates = path.rates;
  const check = path.check;

  return <section className="rt-evidence-path" aria-labelledby="rt-evidence-path-heading">
    <div className="rt-evidence-path-heading">
      <h3 id="rt-evidence-path-heading">Source to finding</h3>
      <p>{review.extractionSource === "fixture" ? "Saved synthetic extraction" : "Live Interfaze candidate extraction"} · scripted audit. One representative check is shown here; inspect all paired checks below before drawing a conclusion.</p>
    </div>
    <ol>
      <li><span>01 · Source page</span>
        {path.focus ? <>
          <p>{path.focus.sourceTitle}, page 1 · “{path.focus.quote}”</p>
          <button type="button" onClick={() => onShowSource(path.focus!.documentId)}>Inspect source page ↗</button>
        </> : <p>Three fictional pages were reviewed before the audit.</p>}
      </li>
      <li><span>02 · Confirmed fact</span>
        {path.focus ? <p>{path.focus.label}: <strong>{path.focus.value}</strong>
          {path.focus.original && <> · corrected from candidate {path.focus.original}</>}
        </p> : <p>Income {displayValue("annual_income_cents", result.reviewed_facts.annual_income_cents)} · debt {displayValue("monthly_debt_cents", result.reviewed_facts.monthly_debt_cents)} · score {result.reviewed_facts.credit_score}</p>}
      </li>
      <li><span>03 · Scripted decision</span>
        <p><strong>{result.decision.outcome}</strong> · agent-stated reasons: {reasonText(result.decision.reasons)}.</p>
      </li>
      <li><span>04 · Controlled replay</span>
        {check?.status === "inapplicable" ? <p>{result.decision.outcome === "APPROVE"
          ? "No adverse reason exists to test in this scripted approval."
          : "This paired check is inapplicable to the scripted decision."}</p>
          : check ? <>
            <p>{path.changes.length ? `Hypothetical ${path.changes.join("; ")}.` : "This check compares the stated reason with current policy breaches."}
              {rates && <> Approval in {rates.matchedTrials} matched synthetic {rates.matchedTrials === 1 ? "trial" : "trials"}: {Math.round(rates.base * 100)}% → {Math.round(rates.changed * 100)}%.</>}
            </p>
            {path.checkIndex !== null && <button type="button" onClick={() => onInspectCheck(path.checkIndex!)}>Go to paired check ↓</button>}
          </> : <p>No paired check was returned.</p>}
      </li>
      <li><span>05 · Finding</span><p><strong>{finding.headline}.</strong> This is a synthetic scripted-control result.</p></li>
    </ol>
  </section>;
}

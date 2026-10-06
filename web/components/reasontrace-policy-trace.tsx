"use client";

import type { DocumentId } from "@/lib/reasontrace/demo";
import type { ReviewedFacts } from "@/lib/reasontrace/audit-result";
import { buildPolicyTrace } from "@/lib/reasontrace/policy-trace";

const dollars = (cents: number) => `$${(cents / 100).toLocaleString("en-US", {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
})}`;
const percent = (ratio: number) => `${(ratio * 100).toFixed(2).replace(/\.00$/, "")}%`;

export function ReasonTracePolicyTrace({ facts, onShowSource }: {
  facts: ReviewedFacts;
  onShowSource: (document: DocumentId) => void;
}) {
  const trace = buildPolicyTrace(facts);
  const status = (breached: boolean) => breached ? "Breached" : "Meets limit";

  return <details className="rt-policy-trace">
    <summary>
      <strong>Policy math for reviewed facts</strong>
      <span>Score {trace.creditScore} / {trace.minimumScore} · DTI {percent(trace.dti)} / {percent(trace.maximumDti)} · Income {dollars(trace.annualIncomeCents)} / {dollars(trace.minimumIncomeCents)}</span>
    </summary>
    <div className="rt-policy-trace-body">
      <p>These three checks use document-backed values. The Python oracle also evaluates the remaining supplied synthetic facts.</p>
      <dl>
        <div className={trace.scoreBreach ? "is-breach" : "is-met"}>
          <dt>Credit score <span>{status(trace.scoreBreach)}</span></dt>
          <dd>{trace.creditScore} {trace.scoreBreach ? "<" : "≥"} {trace.minimumScore} minimum</dd>
          <button type="button" onClick={() => onShowSource("credit-report")}>Inspect credit summary ↗</button>
        </div>
        <div className={trace.dtiBreach ? "is-breach" : "is-met"}>
          <dt>Debt-to-income <span>{status(trace.dtiBreach)}</span></dt>
          <dd>{percent(trace.dti)} {trace.dtiBreach ? ">" : "≤"} {percent(trace.maximumDti)} maximum</dd>
          <small>{trace.zeroIncomeSentinel
            ? "The policy input uses a 100% sentinel when gross monthly income is zero."
            : `${dollars(trace.monthlyDebtCents)} monthly debt ÷ ${dollars(trace.monthlyIncomeCents)} gross monthly income (annual income ÷ 12).`}</small>
          <div className="rt-policy-source-actions">
            <button type="button" onClick={() => onShowSource("credit-report")}>Inspect debt source ↗</button>
            <button type="button" onClick={() => onShowSource("pay-stub")}>Inspect income source ↗</button>
          </div>
        </div>
        <div className={trace.incomeBreach ? "is-breach" : "is-met"}>
          <dt>Annual gross income <span>{status(trace.incomeBreach)}</span></dt>
          <dd>{dollars(trace.annualIncomeCents)} {trace.incomeBreach ? "<" : "≥"} {dollars(trace.minimumIncomeCents)} minimum</dd>
          <button type="button" onClick={() => onShowSource("pay-stub")}>Inspect pay statement ↗</button>
        </div>
      </dl>
      <p className="rt-policy-trace-caveat">A threshold comparison shows a current breach; the paired tests below assess whether an agent actually relied on its stated reason.</p>
    </div>
  </details>;
}

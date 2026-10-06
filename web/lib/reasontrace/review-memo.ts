import { auditMatchesReview, type ReviewedFacts } from "./audit-result";
import { displayValue, documents, fieldDefinitions, fieldIds, type CaseReview } from "./demo";
import { formatFactChange, pairedApprovalRates, type FactChange } from "./paired-evidence";

export type ReviewMemoAudit = {
  mode: string;
  policy: string;
  agent: string;
  reviewed_facts: ReviewedFacts;
  supplied_synthetic_facts: Record<string, unknown>;
  decision: { outcome: string; reasons: string[]; trajectory_id: string };
  oracle: { outcome: string; breached_codes: string[] };
  checks: readonly {
    check: string; status: string; pair_id: string; notes: string;
    changes: FactChange[]; observed: Record<string, unknown>;
    base_trajectory_ids: string[]; cf_trajectory_ids: string[];
  }[];
};

const oneLine = (value: string) => value.replace(/[\x00-\x1f\x7f]+/g, " ").replace(/\s+/g, " ").trim();
const list = (values: readonly string[]) => values.length ? values.map(oneLine).join(", ") : "none";
const suppliedValue = (key: string, value: unknown) =>
  key.endsWith("_cents") && typeof value === "number" && Number.isSafeInteger(value)
    ? `$${(value / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : oneLine(typeof value === "string" ? value : JSON.stringify(value) ?? "unavailable");

export function formatReviewMemo(caseLabel: string, review: CaseReview, result: ReviewMemoAudit): string {
  if (!auditMatchesReview(review, result) ||
    documents.some(doc => !review.documents[doc.id]?.included || !review.documents[doc.id]?.reviewed)) {
    throw new Error("The audit result is not linked to a fully reviewed case.");
  }

  const lines = [
    "REASONTRACE — SYNTHETIC REVIEW MEMO",
    `Case: ${oneLine(caseLabel)}`,
    "Fictional documents and scripted known-answer control. No real borrower or lending decision.",
    "",
    "CONFIRMED DOCUMENT FACTS",
    `Extraction source: ${review.extractionSource === "fixture" ? "saved synthetic fixture" : "live Interfaze candidate extraction"}`,
  ];
  for (const id of fieldIds) {
    const field = review.fields[id];
    const source = documents.find(doc => doc.id === field.documentId);
    lines.push(`- ${fieldDefinitions[id].label}: ${displayValue(id, result.reviewed_facts[id])}`);
    lines.push(`  Source: ${source?.title ?? "Unknown source"}, page 1; “${oneLine(field.quote)}”`);
    if (field.originalValue !== field.value) {
      lines.push(`  Original candidate extraction: ${displayValue(id, field.originalValue)}; reviewer-confirmed value above.`);
    }
  }
  lines.push(
    "- Bank statement: reviewed as a deposit cross-check; its net deposit is not a policy input in this run.",
    "",
    "SUPPLIED SYNTHETIC POLICY FACTS",
    "These values were supplied to the scripted case; they were not extracted from the three documents.",
  );
  const supplied = Object.entries(result.supplied_synthetic_facts).sort(([left], [right]) => left.localeCompare(right));
  if (!supplied.length) lines.push("- none listed");
  for (const [key, value] of supplied) {
    const label = key.endsWith("_cents") ? key.slice(0, -6) : key;
    lines.push(`- ${oneLine(label.replaceAll("_", " "))}: ${suppliedValue(key, value)}`);
  }
  lines.push(
    "",
    "SCRIPTED AUDIT",
    `Policy: ${oneLine(result.policy)}`,
    `Engine mode: ${oneLine(result.mode)}`,
    `Scripted agent: ${oneLine(result.agent)}`,
    `Agent decision: ${oneLine(result.decision.outcome)}`,
    `Agent-stated reason codes: ${list(result.decision.reasons)}`,
    `Synthetic policy outcome: ${oneLine(result.oracle.outcome)}`,
    `Policy-breached reason codes: ${list(result.oracle.breached_codes)}`,
    `Decision trace: ${oneLine(result.decision.trajectory_id)}`,
    "",
    "PAIRED CHECKS",
  );
  if (!result.checks.length) lines.push("No paired checks returned.");
  for (const [index, check] of result.checks.entries()) {
    lines.push(`${index + 1}. ${oneLine(check.check)} — ${oneLine(check.status).toUpperCase()}`);
    if (check.notes) lines.push(`   Note: ${oneLine(check.notes)}`);
    for (const change of check.changes) {
      lines.push(`   Hypothetical test change: ${formatFactChange(change)} (confirmed source unchanged)`);
    }
    const rates = pairedApprovalRates(check.observed);
    if (rates) lines.push(`   Matched scripted trials: ${rates.matchedTrials}; approval with original facts ${Math.round(rates.base * 100)}%, after change ${Math.round(rates.changed * 100)}%.`);
    lines.push(`   Pair ID: ${oneLine(check.pair_id)}`);
    if (check.base_trajectory_ids.length) lines.push(`   Original traces: ${list(check.base_trajectory_ids)}`);
    if (check.cf_trajectory_ids.length) lines.push(`   Changed traces: ${list(check.cf_trajectory_ids)}`);
  }
  lines.push(
    "",
    "LIMITS",
    "This memo reports a synthetic packet and scripted control. It is not a provider finding, underwriting decision, adverse-action notice, or compliance certification.",
    "Approval rates describe matched synthetic trials, not production model performance.",
    "Document images and private download links are not included.",
  );
  return `${lines.join("\n")}\n`;
}

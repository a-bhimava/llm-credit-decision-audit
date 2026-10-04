import { createHash } from "node:crypto";
import { documents, fieldDefinitions, fieldIds, type DocumentId, type FieldId } from "./demo";

export type StoredDocument = {
  id: string; kind: string; sha256: string; included: boolean; reviewed: boolean; page_count: number;
};
export type StoredObservation = {
  id: string; document_id: string; field_key: string; parsed_value: unknown;
  confirmed_value: unknown; review_status: string; source_quote: string;
  page_number: number; extraction_mode: string;
};

const kinds: Record<DocumentId, string> = {
  "pay-stub": "pay_statement", "bank-statement": "bank_statement", "credit-report": "credit_summary",
};
const ranges: Record<FieldId, [number, number]> = {
  annual_income_cents: [0, 60_000_000], monthly_debt_cents: [0, 5_000_000], credit_score: [300, 850],
};
const expectedKeys: Record<string, string[]> = {
  pay_statement: ["applicant_name", "annual_income_cents"],
  bank_statement: ["applicant_name", "statement_period", "payroll_deposit"],
  credit_summary: ["applicant_name", "credit_score", "monthly_debt_cents"],
};

/** Derive audit inputs only from the stored, active extraction and reviewed sources. */
export function prepareSnapshot(
  caseId: string, policyVersion: string, mode: string,
  storedDocuments: StoredDocument[], observations: StoredObservation[], expectedName: string,
  expectedFixtureScore?: number,
) {
  const problems: string[] = [];
  const provenance: Record<string, unknown> = {};
  const facts: Partial<Record<FieldId, number>> = {};
  if (policyVersion !== "meridian-personal-loan-v1") problems.push("Unknown policy version.");
  if (mode !== "fixture" && mode !== "interfaze") problems.push("Unknown extraction mode.");
  if (storedDocuments.length !== documents.length) problems.push("The source packet is incomplete.");
  const byKind = new Map(storedDocuments.map(doc => [doc.kind, doc]));
  const selected = observations.filter(row => row.extraction_mode === mode);
  for (const definition of documents) {
    const doc = byKind.get(kinds[definition.id]);
    if (!doc?.included) problems.push(`${definition.title} is missing.`);
    else if (!doc.reviewed) problems.push(`${definition.title} has not been reviewed.`);
    if (!doc) continue;
    if (!/^[a-f0-9]{64}$/.test(doc.sha256)) problems.push(`${definition.title} has invalid source metadata.`);
    const actualKeys = selected.filter(row => row.document_id === doc.id).map(row => row.field_key).sort();
    if (!expectedKeys[doc.kind] || JSON.stringify(actualKeys) !== JSON.stringify([...expectedKeys[doc.kind]].sort())) {
      problems.push(`${definition.title} has an incomplete or duplicated extraction.`);
    }
    const names = observations.filter(row => row.document_id === doc.id && row.field_key === "applicant_name" && row.extraction_mode === mode);
    if (names.length !== 1) { problems.push(`${definition.title} has no unique applicant observation.`); continue; }
    const name = names[0];
    const value = name.review_status === "confirmed" ? name.confirmed_value : name.parsed_value;
    if (value !== expectedName) problems.push(`${definition.title} has a conflicting applicant name.`);
    if (!name.source_quote || name.page_number < 1 || name.page_number > doc.page_count) {
      problems.push(`${definition.title} has invalid name provenance.`);
    }
  }
  for (const id of fieldIds) {
    const definition = fieldDefinitions[id];
    const doc = byKind.get(kinds[definition.documentId]);
    const matches = observations.filter(row => row.field_key === id && row.document_id === doc?.id && row.extraction_mode === mode);
    if (matches.length !== 1) { problems.push(`${definition.label} has no unique source.`); continue; }
    const row = matches[0];
    const value = row.confirmed_value;
    const [min, max] = ranges[id];
    if (row.review_status !== "confirmed") problems.push(`${definition.label} has not been confirmed.`);
    if (!Number.isSafeInteger(value) || (value as number) < min || (value as number) > max) {
      problems.push(`${definition.label} is outside the allowed range.`);
    }
    if (!row.source_quote || !doc || row.page_number < 1 || row.page_number > doc.page_count) {
      problems.push(`${definition.label} has invalid source provenance.`);
    }
    if (Number.isSafeInteger(value)) facts[id] = value as number;
    if (id === "credit_score" && mode === "fixture" && expectedFixtureScore !== undefined && value !== expectedFixtureScore) {
      problems.push("Credit score differs from the synthetic source page.");
    }
    provenance[id] = {
      observationId: row.id, documentId: row.document_id, documentSha256: doc?.sha256,
      page: row.page_number, quote: row.source_quote, extractionMode: mode,
      extractedValue: row.parsed_value, reviewedValue: value,
    };
  }
  if (selected.length !== 8) problems.push("The selected extraction set is incomplete or duplicated.");
  if (problems.length) return { problems, snapshot: null };
  const snapshot = { caseId, policyVersion, extractionMode: mode, facts: facts as Record<FieldId, number>, provenance };
  const contentSha256 = createHash("sha256").update(JSON.stringify(snapshot)).digest("hex");
  return { problems, snapshot: { ...snapshot, contentSha256 } };
}

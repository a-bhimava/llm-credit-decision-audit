import { caseDefinitions, type CaseDefinition, money } from "./cases";

export const documents = [
  { id: "pay-stub", title: "Pay statement", type: "Income evidence" },
  { id: "bank-statement", title: "Bank statement", type: "Deposit cross-check" },
  { id: "credit-report", title: "Credit summary", type: "Credit evidence" },
] as const;

export type DocumentId = (typeof documents)[number]["id"];
export type FieldId = "annual_income_cents" | "monthly_debt_cents" | "credit_score";
export type ExtractionSource = "fixture" | "interfaze";

export const fieldDefinitions: Record<FieldId, {
  label: string; documentId: DocumentId; unit: "money" | "score";
}> = {
  annual_income_cents: {
    label: "Annual gross income", documentId: "pay-stub", unit: "money",
  },
  monthly_debt_cents: {
    label: "Monthly debt payments", documentId: "credit-report", unit: "money",
  },
  credit_score: {
    label: "Credit score", documentId: "credit-report", unit: "score",
  },
};
export const fieldIds = Object.keys(fieldDefinitions) as FieldId[];

export type ReviewField = { value: number; quote: string; documentId: DocumentId; confirmed: boolean; source: ExtractionSource; originalValue: number };
export type ReviewDocument = { included: boolean; reviewed: boolean; applicantName: string };
export type CaseReview = {
  documents: Record<DocumentId, ReviewDocument>;
  fields: Record<FieldId, ReviewField>;
  extractionSource: ExtractionSource;
};

export function fixtureReview(item: CaseDefinition = caseDefinitions[0]): CaseReview {
  return {
    documents: Object.fromEntries(documents.map(doc => [doc.id, {
      included: item.initialExcludedDocument !== doc.id, reviewed: false, applicantName: item.applicantName,
    }])) as CaseReview["documents"],
    fields: Object.fromEntries(fieldIds.map(id => [id, {
      value: id === "annual_income_cents" ? item.annualIncomeCents
        : id === "monthly_debt_cents" ? item.monthlyDebtCents : item.fixtureCreditScore,
      originalValue: id === "annual_income_cents" ? item.annualIncomeCents
        : id === "monthly_debt_cents" ? item.monthlyDebtCents : item.fixtureCreditScore,
      quote: id === "annual_income_cents" ? `Annualized gross pay ${money(item.annualIncomeCents)}`
        : id === "monthly_debt_cents" ? `Monthly debt payments ${money(item.monthlyDebtCents)}`
          : `Credit score ${item.creditScore}`,
      documentId: fieldDefinitions[id].documentId,
      confirmed: false,
      source: "fixture",
    }])) as CaseReview["fields"],
    extractionSource: "fixture",
  };
}

export function validateReview(input: unknown, expectedName: string,
  expectedFixtureScore?: number): { review: CaseReview | null; problems: string[] } {
  const problems: string[] = [];
  if (!input || typeof input !== "object") return { review: null, problems: ["No case review was supplied."] };
  const review = input as CaseReview;
  if (!review.documents || !review.fields || !["fixture", "interfaze"].includes(review.extractionSource)) {
    return { review: null, problems: ["The case review is incomplete."] };
  }
  for (const doc of documents) {
    const entry = review.documents[doc.id];
    if (!entry?.included) problems.push(`${doc.title} is missing.`);
    else if (!entry.reviewed) problems.push(`${doc.title} has not been reviewed.`);
    if (entry?.included && entry.applicantName !== expectedName) problems.push(`${doc.title} has a conflicting applicant name.`);
  }
  const ranges: Record<FieldId, [number, number]> = {
    annual_income_cents: [0, 60_000_000], monthly_debt_cents: [0, 5_000_000], credit_score: [300, 850],
  };
  for (const id of fieldIds) {
    const field = review.fields[id];
    if (!field || field.documentId !== fieldDefinitions[id].documentId) {
      problems.push(`${fieldDefinitions[id].label} has no valid source.`);
      continue;
    }
    if (!Number.isSafeInteger(field.value) || field.value < ranges[id][0] || field.value > ranges[id][1]) {
      problems.push(`${fieldDefinitions[id].label} is outside the allowed range.`);
    }
    if (!field.confirmed) problems.push(`${fieldDefinitions[id].label} has not been confirmed.`);
    if (field.source !== review.extractionSource) problems.push(`${fieldDefinitions[id].label} has inconsistent extraction provenance.`);
    if (id === "credit_score" && review.extractionSource === "fixture" &&
      expectedFixtureScore !== undefined && field.value !== expectedFixtureScore) {
      problems.push("Credit score differs from the synthetic source page.");
    }
  }
  return { review, problems };
}

export function displayValue(id: FieldId, value: number): string {
  return fieldDefinitions[id].unit === "money" ? `$${(value / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : String(value);
}

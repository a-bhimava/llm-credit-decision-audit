import { describe, expect, it } from "vitest";
import { documents, fieldIds, fixtureReview, validateReview } from "../../lib/reasontrace/demo";
import { prepareSnapshot } from "../../lib/reasontrace/readiness";
import { caseDefinitions, fixtureObservationsFor } from "../../lib/reasontrace/cases";
import { localFixturesEnabled } from "../../lib/reasontrace/local-mode";
import { applyLocalReviewChange } from "../../lib/reasontrace/local-review";

describe("five synthetic case packets", () => {
  it("has five distinct eight-observation fixtures with matching source quotes", () => {
    expect(caseDefinitions.map(item => item.label)).toEqual([
      "RT-SYN-001", "RT-SYN-002", "RT-SYN-003", "RT-SYN-004", "RT-SYN-005",
    ]);
    for (const item of caseDefinitions) {
      const rows = fixtureObservationsFor(item);
      expect(rows).toHaveLength(8);
      expect(rows.filter(row => row.field_key === "applicant_name")).toHaveLength(3);
      expect(rows.find(row => row.field_key === "annual_income_cents")?.parsed_value).toBe(item.annualIncomeCents);
      expect(rows.find(row => row.field_key === "monthly_debt_cents")?.parsed_value).toBe(item.monthlyDebtCents);
      expect(rows.find(row => row.field_key === "credit_score")?.source_quote).toBe(`Credit score ${item.creditScore}`);
    }
  });

  it("requires the injected score correction and restoration of the missing page", () => {
    const misread = caseDefinitions[3];
    const correction = fixtureReview(misread);
    for (const doc of documents) correction.documents[doc.id].reviewed = true;
    for (const id of fieldIds) correction.fields[id].confirmed = true;
    expect(validateReview(correction, misread.applicantName, misread.creditScore).problems)
      .toContain("Credit score differs from the synthetic source page.");
    correction.fields.credit_score.value = misread.creditScore;
    expect(validateReview(correction, misread.applicantName, misread.creditScore).problems).toEqual([]);

    const missing = caseDefinitions[4];
    const restored = fixtureReview(missing);
    for (const doc of documents) restored.documents[doc.id].reviewed = true;
    for (const id of fieldIds) restored.fields[id].confirmed = true;
    expect(validateReview(restored, missing.applicantName, missing.creditScore).problems)
      .toContain("Credit summary is missing.");
    restored.documents["credit-report"].included = true;
    expect(validateReview(restored, missing.applicantName, missing.creditScore).problems).toEqual([]);
  });
});

describe("local fixture isolation", () => {
  it("requires an explicit local flag and stays disabled on Vercel", () => {
    const beforeFlag = process.env.REASONTRACE_LOCAL_FIXTURES;
    const beforeVercel = process.env.VERCEL;
    try {
      delete process.env.REASONTRACE_LOCAL_FIXTURES;
      delete process.env.VERCEL;
      expect(localFixturesEnabled()).toBe(false);
      process.env.REASONTRACE_LOCAL_FIXTURES = "1";
      expect(localFixturesEnabled()).toBe(true);
      process.env.VERCEL = "1";
      expect(localFixturesEnabled()).toBe(false);
    } finally {
      if (beforeFlag === undefined) delete process.env.REASONTRACE_LOCAL_FIXTURES;
      else process.env.REASONTRACE_LOCAL_FIXTURES = beforeFlag;
      if (beforeVercel === undefined) delete process.env.VERCEL;
      else process.env.VERCEL = beforeVercel;
    }
  });

  it("keeps a draft correction unsaved when a different review action is saved", () => {
    const fixture = caseDefinitions[3];
    const saved = fixtureReview(fixture);
    const draft = structuredClone(saved);
    draft.fields.credit_score.value = fixture.creditScore;
    draft.fields.credit_score.confirmed = false;

    const reviewed = applyLocalReviewChange(draft, saved,
      { kind: "document", documentId: "credit-report", reviewed: true }, fixture.applicantName);
    expect(reviewed?.visible.fields.credit_score.value).toBe(fixture.creditScore);
    expect(reviewed?.persisted.fields.credit_score.value).toBe(fixture.fixtureCreditScore);
    expect(reviewed?.persisted.documents["credit-report"].reviewed).toBe(true);

    const confirmed = applyLocalReviewChange(reviewed!.visible, reviewed!.persisted,
      { kind: "field", fieldId: "credit_score", value: fixture.creditScore, confirmed: true }, fixture.applicantName);
    expect(confirmed?.persisted.fields.credit_score).toMatchObject({
      value: fixture.creditScore, originalValue: fixture.fixtureCreditScore, confirmed: true,
    });
    expect(confirmed?.beforeValue).toMatchObject({ confirmed_value: fixture.fixtureCreditScore });
    expect(confirmed?.afterValue).toMatchObject({ confirmed_value: fixture.creditScore });
  });
});

describe("ReasonTrace readiness", () => {
  it("pairs blocking messages with the source or field the reviewer can inspect", () => {
    const missing = caseDefinitions[4];
    const result = validateReview(fixtureReview(missing), missing.applicantName, missing.creditScore);
    expect(result.issues.find(issue => issue.message === "Credit summary is missing.")?.target)
      .toEqual({ kind: "document", id: "credit-report", control: "included" });
    expect(result.issues.find(issue => issue.message === "Annual gross income has not been confirmed.")?.target)
      .toEqual({ kind: "field", id: "annual_income_cents" });

    const misread = caseDefinitions[3];
    const correction = validateReview(fixtureReview(misread), misread.applicantName, misread.creditScore);
    expect(correction.issues.find(issue => issue.message === "Credit score differs from the synthetic source page.")?.target)
      .toEqual({ kind: "field", id: "credit_score" });
    expect(correction.problems).toEqual(correction.issues.map(issue => issue.message));
  });

  it("blocks unreviewed source pages and unconfirmed facts", () => {
    const { problems } = validateReview(fixtureReview(), caseDefinitions[0].applicantName);
    expect(problems.length).toBe(6);
  });

  it("permits only a fully reviewed synthetic packet", () => {
    const review = fixtureReview();
    for (const doc of documents) review.documents[doc.id].reviewed = true;
    for (const id of fieldIds) review.fields[id].confirmed = true;
    expect(validateReview(review, caseDefinitions[0].applicantName).problems).toEqual([]);
    review.documents["credit-report"].included = false;
    expect(validateReview(review, caseDefinitions[0].applicantName).problems).toContain("Credit summary is missing.");
  });

  it("blocks out-of-range scores and conflicting names", () => {
    const review = fixtureReview();
    for (const doc of documents) review.documents[doc.id].reviewed = true;
    for (const id of fieldIds) review.fields[id].confirmed = true;
    review.fields.credit_score.value = 999;
    review.documents["bank-statement"].applicantName = "Different Applicant";
    expect(validateReview(review, caseDefinitions[0].applicantName).problems).toEqual(expect.arrayContaining([
      "Credit score is outside the allowed range.",
      "Bank statement has a conflicting applicant name.",
    ]));
  });
});

describe("server-side snapshot preparation", () => {
  const sha = "a".repeat(64);
  const docs = [
    { id: "pay", kind: "pay_statement", sha256: sha, included: true, reviewed: true, page_count: 1 },
    { id: "bank", kind: "bank_statement", sha256: sha, included: true, reviewed: true, page_count: 1 },
    { id: "credit", kind: "credit_summary", sha256: sha, included: true, reviewed: true, page_count: 1 },
  ];
  const observation = (id: string, documentId: string, key: string, value: unknown, confirmed = false) => ({
    id, document_id: documentId, field_key: key, parsed_value: value,
    confirmed_value: confirmed ? value : null, review_status: confirmed ? "confirmed" : "unconfirmed",
    source_quote: String(value), page_number: 1, extraction_mode: "fixture",
  });
  const rows = [
    observation("name-pay", "pay", "applicant_name", "Alex Morgan"),
    observation("income", "pay", "annual_income_cents", 6_000_000, true),
    observation("name-bank", "bank", "applicant_name", "Alex Morgan"),
    observation("period", "bank", "statement_period", "Sep 2026"),
    observation("deposit", "bank", "payroll_deposit", 412_000),
    observation("name-credit", "credit", "applicant_name", "Alex Morgan"),
    observation("score", "credit", "credit_score", 635, true),
    observation("debt", "credit", "monthly_debt_cents", 60_000, true),
  ];
  const prepare = (source = rows, packet = docs) => prepareSnapshot(
    "case-1", "meridian-personal-loan-v1", "fixture", packet, source,
    caseDefinitions[0].applicantName,
  );

  it("freezes exactly the confirmed stored facts and their source IDs", () => {
    const result = prepare();
    expect(result.problems).toEqual([]);
    expect(result.snapshot?.facts).toEqual({ annual_income_cents: 6_000_000, monthly_debt_cents: 60_000, credit_score: 635 });
    expect(result.snapshot?.provenance.credit_score).toMatchObject({ observationId: "score", documentId: "credit", page: 1 });
    expect(prepare().snapshot?.contentSha256).toBe(result.snapshot?.contentSha256);
  });

  it("blocks unconfirmed, conflicting, missing, duplicate, and wrong-source evidence", () => {
    expect(prepare(rows.map(row => row.id === "score" ? { ...row, review_status: "unconfirmed" } : row)).problems)
      .toContain("Credit score has not been confirmed.");
    expect(prepare(rows.map(row => row.id === "name-bank" ? { ...row, parsed_value: "Someone Else" } : row)).problems)
      .toContain("Bank statement has a conflicting applicant name.");
    expect(prepare(rows.filter(row => row.id !== "income")).snapshot).toBeNull();
    expect(prepare([...rows, rows[1]]).snapshot).toBeNull();
    expect(prepare(rows.map(row => row.id === "income" ? { ...row, document_id: "bank" } : row)).snapshot).toBeNull();
    expect(prepare(rows, docs.map(doc => doc.id === "pay" ? { ...doc, reviewed: false } : doc)).snapshot).toBeNull();
  });

  it("changes the snapshot hash after a corrected reviewed value", () => {
    const changed = rows.map(row => row.id === "score" ? { ...row, confirmed_value: 660 } : row);
    expect(prepare(changed).snapshot?.contentSha256).not.toBe(prepare().snapshot?.contentSha256);
  });
});

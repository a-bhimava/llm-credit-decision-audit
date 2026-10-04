import { NextResponse } from "next/server";
import { getCaseDefinition } from "@/lib/reasontrace/cases";
import { validateReview } from "@/lib/reasontrace/demo";
import { localFixturesEnabled } from "@/lib/reasontrace/local-mode";
import { runPython } from "@/lib/reasontrace/run-python";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "private, no-store" };

export async function POST(request: Request) {
  if (!localFixturesEnabled()) return NextResponse.json({ error: "Not found" }, { status: 404, headers });
  let body: Record<string, unknown>;
  try { body = await request.json(); }
  catch { return NextResponse.json({ error: "Invalid JSON" }, { status: 400, headers }); }
  const item = getCaseDefinition(typeof body.caseLabel === "string" ? body.caseLabel : "");
  if (!item || (body.agent !== "faithful" && body.agent !== "laundering")) {
    return NextResponse.json({ error: "Unknown synthetic case or scripted control" }, { status: 400, headers });
  }
  const { review, problems } = validateReview(body.review, item.applicantName, item.creditScore);
  if (review?.extractionSource !== "fixture") problems.push("The local demo accepts only saved fixtures.");
  if (review && (review.fields.annual_income_cents.value !== item.annualIncomeCents ||
    review.fields.monthly_debt_cents.value !== item.monthlyDebtCents)) {
    problems.push("Reviewed values differ from the fictional source pages.");
  }
  if (problems.length || !review) {
    return NextResponse.json({ error: "Case needs review", problems }, { status: 422, headers });
  }
  try {
    const result = await runPython({
      annual_income_cents: review.fields.annual_income_cents.value,
      monthly_debt_cents: review.fields.monthly_debt_cents.value,
      credit_score: review.fields.credit_score.value,
    }, body.agent, item.label, item.applicantName);
    return NextResponse.json(result, { headers });
  } catch (error) {
    return NextResponse.json({ error: "Local scripted audit unavailable", detail: error instanceof Error ? error.message : "Unknown error" }, { status: 503, headers });
  }
}

import { createHash } from "node:crypto";
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { extractDocument } from "@/lib/reasontrace/interfaze";
import type { DocumentId } from "@/lib/reasontrace/demo";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "private, no-store" };
const kinds: Record<string, DocumentId> = {
  pay_statement: "pay-stub", bank_statement: "bank-statement", credit_summary: "credit-report",
};

function shortQuote(value: unknown): string {
  return typeof value === "string" ? value.trim().slice(0, 350) : "";
}

export async function POST(_request: Request, context: { params: Promise<{ id: string }> }) {
  const supabase = await createClient();
  const { data: claimsData } = await supabase.auth.getClaims();
  if (!claimsData?.claims.sub) return NextResponse.json({ error: "Sign in required" }, { status: 401, headers });
  const { id } = await context.params;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) {
    return NextResponse.json({ error: "Invalid case ID" }, { status: 400, headers });
  }
  const owned = await supabase.from("rt_cases").select("id")
    .eq("id", id).eq("owner_id", claimsData.claims.sub).maybeSingle();
  if (owned.error || !owned.data) return NextResponse.json({ error: "Case not found" }, { status: 404, headers });
  let admin: ReturnType<typeof createAdminClient>;
  try { admin = createAdminClient(); }
  catch { return NextResponse.json({ error: "Private extraction storage is not configured on this server" }, { status: 503, headers }); }
  const key = process.env.INTERFAZE_API_KEY;
  if (!key) return NextResponse.json({ error: "Interfaze access is not configured; the saved synthetic extraction remains available." }, { status: 503, headers });
  const listed = await supabase.from("rt_documents")
    .select("id, kind, storage_path, sha256, included")
    .eq("case_id", id).order("kind");
  if (listed.error || !listed.data || listed.data.length !== 3 || listed.data.some(doc => !doc.included)) {
    return NextResponse.json({ error: "All three private source documents must be included" }, { status: 422, headers });
  }
  const current = await supabase.from("rt_observations").select("id")
    .eq("case_id", id).eq("extraction_mode", "interfaze");
  if (current.error) return NextResponse.json({ error: "Extraction state unavailable" }, { status: 503, headers });
  if ((current.data?.length ?? 0) === 8) {
    const switched = await supabase.from("rt_cases").update({ active_extraction_mode: "interfaze" }).eq("id", id);
    if (switched.error) return NextResponse.json({ error: "Extraction mode could not be selected" }, { status: 503, headers });
    return NextResponse.json({ source: "interfaze", reused: true }, { headers });
  }
  if ((current.data?.length ?? 0) > 0) {
    return NextResponse.json({ error: "An incomplete saved extraction needs review before retry" }, { status: 409, headers });
  }

  try {
    const outputs = await Promise.all(listed.data.map(async doc => {
      const documentId = kinds[doc.kind];
      if (!documentId) throw new Error("Unknown document kind");
      const downloaded = await admin.storage.from("reasontrace-documents").download(doc.storage_path);
      if (downloaded.error || !downloaded.data) throw new Error("Private source document could not be read");
      const image = Buffer.from(await downloaded.data.arrayBuffer());
      if (createHash("sha256").update(image).digest("hex") !== doc.sha256) {
        throw new Error("Private source checksum does not match its metadata");
      }
      return { doc, result: await extractDocument(documentId, image, key) };
    }));
    const byKind = Object.fromEntries(outputs.map(output => [output.doc.kind, output]));
    const pay = byKind.pay_statement;
    const bank = byKind.bank_statement;
    const credit = byKind.credit_summary;
    if (!pay || !bank || !credit) throw new Error("One source document is missing");
    const rows = [
      { doc: pay, field_key: "applicant_name", value: pay.result.applicant_name, quote: pay.result.applicant_name },
      { doc: pay, field_key: "annual_income_cents", value: pay.result.annual_income_cents, quote: pay.result.annual_income_quote },
      { doc: bank, field_key: "applicant_name", value: bank.result.applicant_name, quote: bank.result.applicant_name },
      { doc: bank, field_key: "statement_period", value: bank.result.statement_period, quote: bank.result.statement_period },
      { doc: bank, field_key: "payroll_deposit", value: bank.result.payroll_deposit_quote, quote: bank.result.payroll_deposit_quote },
      { doc: credit, field_key: "applicant_name", value: credit.result.applicant_name, quote: credit.result.applicant_name },
      { doc: credit, field_key: "credit_score", value: credit.result.credit_score, quote: credit.result.credit_score_quote },
      { doc: credit, field_key: "monthly_debt_cents", value: credit.result.monthly_debt_cents, quote: credit.result.monthly_debt_quote },
    ];
    for (const row of rows) {
      if (!shortQuote(row.quote)) throw new Error(`No source quote for ${row.field_key}`);
    }
    const inserted = await admin.from("rt_observations").insert(rows.map(row => ({
      case_id: id, document_id: row.doc.doc.id, field_key: row.field_key,
      raw_value: String(row.value), parsed_value: row.value,
      source_quote: shortQuote(row.quote), page_number: 1, extraction_mode: "interfaze",
    })));
    if (inserted.error) throw new Error("Interfaze observations could not be saved");
    const switched = await supabase.from("rt_cases").update({ active_extraction_mode: "interfaze" }).eq("id", id);
    if (switched.error) throw new Error("Saved extraction could not be selected");
    return NextResponse.json({ source: "interfaze", observationCount: rows.length }, { headers });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Interfaze extraction failed" }, { status: 502, headers });
  }
}

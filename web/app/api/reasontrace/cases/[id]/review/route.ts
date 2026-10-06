import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { fieldDefinitions, reviewFieldRanges, type DocumentId, type FieldId } from "@/lib/reasontrace/demo";
import { getCaseDefinition } from "@/lib/reasontrace/cases";

export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "private, no-store" };
const kinds: Record<DocumentId, string> = {
  "pay-stub": "pay_statement", "bank-statement": "bank_statement", "credit-report": "credit_summary",
};

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  const supabase = await createClient();
  const { data: claimsData } = await supabase.auth.getClaims();
  if (!claimsData?.claims.sub) return NextResponse.json({ error: "Sign in required" }, { status: 401, headers });
  const { id } = await context.params;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) {
    return NextResponse.json({ error: "Invalid case ID" }, { status: 400, headers });
  }
  const owned = await supabase.from("rt_cases").select("active_extraction_mode, case_label")
    .eq("id", id).eq("owner_id", claimsData.claims.sub).maybeSingle();
  if (owned.error || !owned.data) return NextResponse.json({ error: "Case not found" }, { status: 404, headers });
  const definition = getCaseDefinition(owned.data.case_label);
  if (!definition) return NextResponse.json({ error: "Unknown synthetic case" }, { status: 404, headers });
  let body: Record<string, unknown>;
  try { body = await request.json(); }
  catch { return NextResponse.json({ error: "Invalid JSON" }, { status: 400, headers }); }

  if (body.kind === "mode" && (body.mode === "fixture" || body.mode === "interfaze")) {
    const available = await supabase.from("rt_observations").select("id")
      .eq("case_id", id).eq("extraction_mode", body.mode);
    if (available.error || available.data?.length !== 8) {
      return NextResponse.json({ error: "That extraction set is incomplete" }, { status: 422, headers });
    }
    const switched = await supabase.from("rt_cases")
      .update({ active_extraction_mode: body.mode }).eq("id", id);
    if (switched.error) return NextResponse.json({ error: "Extraction mode could not be saved" }, { status: 503, headers });
    return NextResponse.json({ saved: true }, { headers });
  }

  if (body.kind === "document" && typeof body.documentId === "string" && body.documentId in kinds) {
    const docId = body.documentId as DocumentId;
    if (typeof body.included !== "boolean" && typeof body.reviewed !== "boolean") {
      return NextResponse.json({ error: "No document change supplied" }, { status: 400, headers });
    }
    const found = await supabase.from("rt_documents").select("id, included, reviewed")
      .eq("case_id", id).eq("kind", kinds[docId]).maybeSingle();
    if (found.error || !found.data) return NextResponse.json({ error: "Document not found" }, { status: 404, headers });
    const included = typeof body.included === "boolean" ? body.included : found.data.included;
    const reviewed = included && (typeof body.reviewed === "boolean" ? body.reviewed : found.data.reviewed);
    const changed = await supabase.from("rt_documents").update({ included, reviewed })
      .eq("id", found.data.id).eq("case_id", id).select("id").single();
    if (changed.error) return NextResponse.json({ error: "Document review could not be saved" }, { status: 503, headers });
    return NextResponse.json({ saved: true }, { headers });
  }

  if (body.kind === "applicant_name" && typeof body.documentId === "string" && body.documentId in kinds) {
    const docId = body.documentId as DocumentId;
    if (typeof body.value !== "string" || body.value.trim() !== definition.applicantName) {
      return NextResponse.json({ error: "The reviewed fictional applicant name must match the case" }, { status: 422, headers });
    }
    const found = await supabase.from("rt_documents").select("id, included, reviewed")
      .eq("case_id", id).eq("kind", kinds[docId]).maybeSingle();
    if (found.error || !found.data) return NextResponse.json({ error: "Source document not found" }, { status: 404, headers });
    if (!found.data.included || !found.data.reviewed) {
      return NextResponse.json({ error: "Review the included source document first" }, { status: 422, headers });
    }
    const observation = await supabase.from("rt_observations").select("id, source_quote")
      .eq("case_id", id).eq("document_id", found.data.id).eq("field_key", "applicant_name")
      .eq("extraction_mode", owned.data.active_extraction_mode).maybeSingle();
    if (observation.error || !observation.data?.source_quote) {
      return NextResponse.json({ error: "Applicant source observation not found" }, { status: 404, headers });
    }
    const saved = await supabase.from("rt_observations").update({
      confirmed_value: definition.applicantName, review_status: "confirmed", reviewed_at: new Date().toISOString(),
    }).eq("id", observation.data.id).eq("case_id", id).select("id").single();
    if (saved.error) return NextResponse.json({ error: "Applicant correction could not be saved" }, { status: 503, headers });
    return NextResponse.json({ saved: true }, { headers });
  }

  if (body.kind === "field" && typeof body.fieldId === "string" && body.fieldId in fieldDefinitions) {
    const fieldId = body.fieldId as FieldId;
    const definition = fieldDefinitions[fieldId];
    const found = await supabase.from("rt_documents").select("id, included, reviewed")
      .eq("case_id", id).eq("kind", kinds[definition.documentId]).maybeSingle();
    if (found.error || !found.data) return NextResponse.json({ error: "Source document not found" }, { status: 404, headers });
    const observation = await supabase.from("rt_observations")
      .select("id, parsed_value, confirmed_value, source_quote")
      .eq("case_id", id).eq("document_id", found.data.id).eq("field_key", fieldId)
      .eq("extraction_mode", owned.data.active_extraction_mode).maybeSingle();
    if (observation.error || !observation.data) {
      return NextResponse.json({ error: "Source observation not found" }, { status: 404, headers });
    }
    const [min, max] = reviewFieldRanges[fieldId];
    const value = body.value === undefined
      ? observation.data.confirmed_value ?? observation.data.parsed_value : body.value;
    if (!Number.isSafeInteger(value) || (value as number) < min || (value as number) > max) {
      return NextResponse.json({ error: "Reviewed value is outside the allowed range" }, { status: 422, headers });
    }
    if (body.confirmed === true && (!found.data.included || !found.data.reviewed || !observation.data.source_quote)) {
      return NextResponse.json({ error: "Review the included source document first" }, { status: 422, headers });
    }
    const reviewStatus = body.confirmed === true ? "confirmed"
      : body.value !== undefined || body.confirmed === false ? "unconfirmed" : null;
    if (!reviewStatus) return NextResponse.json({ error: "No field change supplied" }, { status: 400, headers });
    const saved = await supabase.from("rt_observations").update({
      confirmed_value: value, review_status: reviewStatus, reviewed_at: new Date().toISOString(),
    }).eq("id", observation.data.id).eq("case_id", id).select("id").single();
    if (saved.error) return NextResponse.json({ error: "Field review could not be saved" }, { status: 503, headers });
    return NextResponse.json({ saved: true }, { headers });
  }
  return NextResponse.json({ error: "Unknown review action" }, { status: 400, headers });
}

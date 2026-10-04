import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { fieldDefinitions, fieldIds, type CaseReview, type DocumentId, type FieldId } from "@/lib/reasontrace/demo";
import { prepareSnapshot, type StoredDocument, type StoredObservation } from "@/lib/reasontrace/readiness";
import { getCaseDefinition } from "@/lib/reasontrace/cases";

export const dynamic = "force-dynamic";

const headers = { "Cache-Control": "private, no-store" };

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const supabase = await createClient();
  const { data: claimsData } = await supabase.auth.getClaims();
  if (!claimsData?.claims.sub) {
    return NextResponse.json({ error: "Sign in required" }, { status: 401, headers });
  }
  const { id } = await context.params;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) {
    return NextResponse.json({ error: "Invalid case ID" }, { status: 400, headers });
  }
  const owned = await supabase.from("rt_cases")
    .select("id, case_label, policy_version, synthetic, status, active_extraction_mode, created_at")
    .eq("id", id).eq("owner_id", claimsData.claims.sub).maybeSingle();
  if (owned.error) return NextResponse.json({ error: "Case unavailable" }, { status: 503, headers });
  if (!owned.data) return NextResponse.json({ error: "Case not found" }, { status: 404, headers });
  const definition = getCaseDefinition(owned.data.case_label);
  if (!definition) return NextResponse.json({ error: "Unknown synthetic case" }, { status: 404, headers });

  const { data: documents, error } = await supabase.from("rt_documents")
    .select("id, kind, storage_path, sha256, page_count, included, reviewed")
    .eq("case_id", id).order("kind");
  if (error) return NextResponse.json({ error: "Documents unavailable" }, { status: 503, headers });
  const withUrls = await Promise.all((documents ?? []).map(async doc => {
    const signed = await supabase.storage.from("reasontrace-documents")
      .createSignedUrl(doc.storage_path, 600);
    return {
      id: doc.id, kind: doc.kind, sha256: doc.sha256, pageCount: doc.page_count,
      included: doc.included, reviewed: doc.reviewed,
      previewUrl: signed.error ? null : signed.data.signedUrl,
    };
  }));
  const mode = owned.data.active_extraction_mode as "fixture" | "interfaze";
  const observationsQuery = await supabase.from("rt_observations")
    .select("id, document_id, field_key, raw_value, parsed_value, source_quote, page_number, extraction_mode, confirmed_value, review_status, extracted_at, reviewed_at")
    .eq("case_id", id).eq("extraction_mode", mode).order("extracted_at");
  const eventsQuery = await supabase.from("rt_review_events")
    .select("id, observation_id, action, before_value, after_value, created_at")
    .eq("case_id", id).order("created_at", { ascending: true }).limit(200);
  if (observationsQuery.error || eventsQuery.error) {
    return NextResponse.json({ error: "Case review unavailable" }, { status: 503, headers });
  }
  const sourceToDocId: Record<string, DocumentId> = {
    pay_statement: "pay-stub", bank_statement: "bank-statement", credit_summary: "credit-report",
  };
  const documentIdToSource = new Map((documents ?? []).map(doc => [doc.id, sourceToDocId[doc.kind]]));
  const observations = observationsQuery.data ?? [];
  const review: CaseReview = {
    documents: {} as CaseReview["documents"],
    fields: {} as CaseReview["fields"],
    extractionSource: mode,
  };
  for (const doc of documents ?? []) {
    const docId = sourceToDocId[doc.kind];
    if (!docId) continue;
    const name = observations.find(row => row.document_id === doc.id && row.field_key === "applicant_name");
    review.documents[docId] = {
      included: doc.included, reviewed: doc.reviewed,
      applicantName: typeof name?.confirmed_value === "string" ? name.confirmed_value
        : typeof name?.parsed_value === "string" ? name.parsed_value : "",
    };
  }
  for (const fieldId of fieldIds) {
    const observation = observations.find(row => row.field_key === fieldId);
    if (!observation || typeof observation.parsed_value !== "number") continue;
    const documentId = documentIdToSource.get(observation.document_id);
    if (documentId !== fieldDefinitions[fieldId].documentId) continue;
    review.fields[fieldId as FieldId] = {
      value: typeof observation.confirmed_value === "number" ? observation.confirmed_value : observation.parsed_value,
      originalValue: observation.parsed_value,
      quote: observation.source_quote,
      documentId, confirmed: observation.review_status === "confirmed", source: mode,
    };
  }
  if (documents?.length !== 3 || Object.keys(review.documents).length !== 3 || Object.keys(review.fields).length !== 3) {
    return NextResponse.json({ error: "The selected case extraction is incomplete" }, { status: 503, headers });
  }
  const prepared = prepareSnapshot(id, owned.data.policy_version, mode,
    (documents ?? []) as StoredDocument[], observations as StoredObservation[],
    definition.applicantName, definition.creditScore);
  let currentRun: { id: string; status: string; agent_kind: string; result: unknown; finished_at: string | null } | null = null;
  if (prepared.snapshot) {
    const snapshot = await supabase.from("rt_snapshots").select("id")
      .eq("case_id", id).eq("content_sha256", prepared.snapshot.contentSha256).maybeSingle();
    if (!snapshot.error && snapshot.data) {
      const run = await supabase.from("rt_audit_runs").select("id, status, agent_kind, result, finished_at")
        .eq("case_id", id).eq("snapshot_id", snapshot.data.id)
        .order("created_at", { ascending: false }).limit(1).maybeSingle();
      if (!run.error) currentRun = run.data;
    }
  }
  return NextResponse.json({
    case: owned.data, documents: withUrls, review,
    observations, reviewEvents: eventsQuery.data ?? [], currentRun,
  }, { headers });
}

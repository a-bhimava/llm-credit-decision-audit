import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { caseDefinitions, fixtureObservationsFor, type CaseDefinition } from "@/lib/reasontrace/cases";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "private, no-store" };
const bucket = "reasontrace-documents";
const packet = [
  { id: "pay-stub", kind: "pay_statement" },
  { id: "bank-statement", kind: "bank_statement" },
  { id: "credit-report", kind: "credit_summary" },
] as const;
type UserClient = Awaited<ReturnType<typeof createClient>>;
type AdminClient = ReturnType<typeof createAdminClient>;

async function authenticatedClient() {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  return { supabase, ownerId: error ? null : data?.claims.sub ?? null };
}

export async function GET() {
  const { supabase, ownerId } = await authenticatedClient();
  if (!ownerId) return NextResponse.json({ error: "Sign in required" }, { status: 401, headers });
  const { data, error } = await supabase.from("rt_cases")
    .select("id, case_label, policy_version, synthetic, status, created_at")
    .eq("owner_id", ownerId).order("case_label", { ascending: true }).limit(20);
  if (error) return NextResponse.json({ error: "Cases unavailable" }, { status: 503, headers });
  return NextResponse.json({ cases: data }, { headers });
}

export async function POST() {
  const { supabase, ownerId } = await authenticatedClient();
  if (!ownerId) return NextResponse.json({ error: "Sign in required" }, { status: 401, headers });
  let admin: AdminClient;
  try { admin = createAdminClient(); }
  catch { return NextResponse.json({ error: "Private case storage is not configured on this server" }, { status: 503, headers }); }
  const seeded: { id: string; label: string }[] = [];
  for (const item of caseDefinitions) {
    const existing = await supabase.from("rt_cases").select("id")
      .eq("owner_id", ownerId).eq("case_label", item.label).maybeSingle();
    if (existing.error) return NextResponse.json({ error: "Case lookup failed" }, { status: 503, headers });
    let caseId = existing.data?.id;
    if (!caseId) {
      const created = await supabase.from("rt_cases").insert({
        owner_id: ownerId, case_label: item.label,
        policy_version: "meridian-personal-loan-v1", synthetic: true,
      }).select("id").single();
      if (created.data) caseId = created.data.id;
      else {
        const concurrent = await supabase.from("rt_cases").select("id")
          .eq("owner_id", ownerId).eq("case_label", item.label).maybeSingle();
        if (concurrent.error || !concurrent.data) {
          return NextResponse.json({ error: `Case ${item.label} could not be created` }, { status: 503, headers });
        }
        caseId = concurrent.data.id;
      }
    }
    const documentsError = await seedDocuments(item, caseId, ownerId, supabase, admin);
    if (documentsError) return NextResponse.json({ error: documentsError }, { status: 503, headers });
    const observationsError = await seedObservations(item, caseId, supabase, admin);
    if (observationsError) return NextResponse.json({ error: observationsError }, { status: 503, headers });
    seeded.push({ id: caseId, label: item.label });
  }
  return NextResponse.json({ cases: seeded, seeded: true, documentCount: seeded.length * packet.length }, { status: 201, headers });
}

async function seedDocuments(item: CaseDefinition, caseId: string, ownerId: string,
  supabase: UserClient, admin: AdminClient): Promise<string | null> {
  for (const doc of packet) {
    const filename = item.label === "RT-SYN-001" ? `${doc.id}.png` : `${item.label}/${doc.id}.png`;
    let bytes: Buffer;
    try { bytes = await readFile(resolve(process.cwd(), "..", "fixtures", "reasontrace", filename)); }
    catch { return `Synthetic source image for ${item.label} is unavailable`; }
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    const path = `${ownerId}/${caseId}/${doc.id}.png`;
    const previous = await supabase.from("rt_documents").select("id, sha256, storage_path")
      .eq("case_id", caseId).eq("kind", doc.kind).maybeSingle();
    if (previous.error) return "Document lookup failed";
    if (previous.data) {
      if (previous.data.sha256 !== sha256 || previous.data.storage_path !== path) {
        return `Existing ${item.label} document does not match its seed`;
      }
      continue;
    }
    const uploaded = await admin.storage.from(bucket).upload(path, bytes,
      { contentType: "image/png", upsert: false, cacheControl: "0" });
    if (uploaded.error) {
      const downloaded = await admin.storage.from(bucket).download(path);
      if (downloaded.error || !downloaded.data) return "Private document upload failed";
      const storedHash = createHash("sha256").update(Buffer.from(await downloaded.data.arrayBuffer())).digest("hex");
      if (storedHash !== sha256) return "Stored document differs from fixture";
    }
    const inserted = await admin.from("rt_documents").insert({
      case_id: caseId, kind: doc.kind, storage_path: path, sha256, page_count: 1,
      included: item.initialExcludedDocument !== doc.id, reviewed: false,
    });
    if (inserted.error) {
      const concurrent = await supabase.from("rt_documents")
        .select("sha256, storage_path").eq("case_id", caseId).eq("kind", doc.kind).maybeSingle();
      if (concurrent.error || concurrent.data?.sha256 !== sha256 || concurrent.data?.storage_path !== path) {
        return "Document metadata could not be saved";
      }
    }
  }
  return null;
}

async function seedObservations(item: CaseDefinition, caseId: string,
  supabase: UserClient, admin: AdminClient): Promise<string | null> {
  const listed = await supabase.from("rt_documents").select("id, kind").eq("case_id", caseId);
  if (listed.error || !listed.data || listed.data.length !== packet.length) return "Case documents are incomplete";
  const documentIds = new Map(listed.data.map(doc => [doc.kind, doc.id]));
  const current = await supabase.from("rt_observations")
    .select("document_id, field_key").eq("case_id", caseId).eq("extraction_mode", "fixture");
  if (current.error) return "Case extraction lookup failed";
  const present = new Set((current.data ?? []).map(row => `${row.document_id}:${row.field_key}`));
  for (const observation of fixtureObservationsFor(item)) {
    const documentId = documentIds.get(observation.kind);
    if (!documentId) return "Case source missing";
    if (present.has(`${documentId}:${observation.field_key}`)) continue;
    const inserted = await admin.from("rt_observations").insert({
      case_id: caseId, document_id: documentId, field_key: observation.field_key,
      raw_value: observation.raw_value, parsed_value: observation.parsed_value,
      source_quote: observation.source_quote, page_number: 1, extraction_mode: "fixture",
    });
    if (inserted.error && inserted.error.code !== "23505") return "Fixture observations could not be saved";
  }
  return null;
}

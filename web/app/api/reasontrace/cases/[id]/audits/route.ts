import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { prepareSnapshot, type StoredDocument, type StoredObservation } from "@/lib/reasontrace/readiness";
import { runPython } from "@/lib/reasontrace/run-python";
import { getCaseDefinition } from "@/lib/reasontrace/cases";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "private, no-store" };
const validId = (id: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const userClient = await createClient();
  const { data: claims } = await userClient.auth.getClaims();
  if (!claims?.claims.sub) return NextResponse.json({ error: "Sign in required" }, { status: 401, headers });
  const { id } = await context.params;
  if (!validId(id)) return NextResponse.json({ error: "Invalid case ID" }, { status: 400, headers });
  let agent: "faithful" | "laundering";
  try {
    const body = await request.json();
    if (body?.agent !== "faithful" && body?.agent !== "laundering") throw new Error();
    agent = body.agent;
  } catch { return NextResponse.json({ error: "Choose a known scripted control" }, { status: 400, headers }); }

  const owned = await userClient.from("rt_cases")
    .select("id, owner_id, case_label, policy_version, active_extraction_mode")
    .eq("id", id).eq("owner_id", claims.claims.sub).maybeSingle();
  if (owned.error) return NextResponse.json({ error: "Case unavailable" }, { status: 503, headers });
  if (!owned.data) return NextResponse.json({ error: "Case not found" }, { status: 404, headers });
  const definition = getCaseDefinition(owned.data.case_label);
  if (!definition) return NextResponse.json({ error: "Unknown synthetic case" }, { status: 404, headers });
  const [docs, observations] = await Promise.all([
    userClient.from("rt_documents").select("id, kind, sha256, included, reviewed, page_count").eq("case_id", id),
    userClient.from("rt_observations").select("id, document_id, field_key, parsed_value, confirmed_value, review_status, source_quote, page_number, extraction_mode")
      .eq("case_id", id).eq("extraction_mode", owned.data.active_extraction_mode),
  ]);
  if (docs.error || observations.error) return NextResponse.json({ error: "Saved review unavailable" }, { status: 503, headers });
  const prepared = prepareSnapshot(id, owned.data.policy_version, owned.data.active_extraction_mode,
    (docs.data ?? []) as StoredDocument[], (observations.data ?? []) as StoredObservation[],
    definition.applicantName, definition.creditScore);
  if (!prepared.snapshot) return NextResponse.json({ error: "Case needs review", problems: prepared.problems }, { status: 422, headers });

  // The privileged client only persists a server-derived snapshot and Python result.
  // It never authorizes the reviewer: the session-scoped query above does that.
  let admin: ReturnType<typeof createAdminClient>;
  try { admin = createAdminClient(); }
  catch { return NextResponse.json({ error: "Audit persistence is not configured on this server" }, { status: 503, headers }); }

  const snapshot = prepared.snapshot;
  const existingSnapshot = await admin.from("rt_snapshots").select("id")
    .eq("case_id", id).eq("content_sha256", snapshot.contentSha256).maybeSingle();
  if (existingSnapshot.error) return NextResponse.json({ error: "Snapshot lookup failed" }, { status: 503, headers });
  let snapshotId = existingSnapshot.data?.id;
  if (!snapshotId) {
    const inserted = await admin.from("rt_snapshots").insert({
      case_id: id, policy_version: snapshot.policyVersion,
      facts: { extraction_mode: snapshot.extractionMode, reviewed: snapshot.facts, supplied: "reasontrace-demo-v1" },
      provenance: snapshot.provenance, content_sha256: snapshot.contentSha256,
    }).select("id").single();
    if (inserted.error) {
      const concurrent = await admin.from("rt_snapshots").select("id")
        .eq("case_id", id).eq("content_sha256", snapshot.contentSha256).maybeSingle();
      if (!concurrent.data) return NextResponse.json({ error: "Snapshot could not be frozen" }, { status: 503, headers });
      snapshotId = concurrent.data.id;
    } else snapshotId = inserted.data.id;
  }
  const previous = await admin.from("rt_audit_runs").select("id, status, result")
    .eq("case_id", id).eq("snapshot_id", snapshotId).eq("agent_kind", agent).maybeSingle();
  if (previous.error) return NextResponse.json({ error: "Audit lookup failed" }, { status: 503, headers });
  if (previous.data?.status === "completed" && previous.data.result) {
    return NextResponse.json({ ...previous.data.result, runId: previous.data.id, snapshotId, reused: true }, { headers });
  }
  if (previous.data?.status === "running") {
    return NextResponse.json({ error: "This audit is already running", runId: previous.data.id }, { status: 409, headers });
  }
  let runId = previous.data?.id;
  if (runId) {
    const restarted = await admin.from("rt_audit_runs").update({ status: "running", result: null, error_code: null, finished_at: null })
      .eq("id", runId).eq("status", "failed").select("id").maybeSingle();
    if (restarted.error || !restarted.data) return NextResponse.json({ error: "Audit retry conflict" }, { status: 409, headers });
  } else {
    const created = await admin.from("rt_audit_runs").insert({
      case_id: id, snapshot_id: snapshotId, agent_kind: agent, mode: "scripted_control", status: "running",
    }).select("id").single();
    if (created.error) return NextResponse.json({ error: "Audit could not be started" }, { status: 409, headers });
    runId = created.data.id;
  }
  try {
    const result = await runPython(snapshot.facts, agent, definition.label, definition.applicantName);
    const completed = await admin.from("rt_audit_runs").update({
      status: "completed", result, finished_at: new Date().toISOString(),
    }).eq("id", runId).eq("status", "running");
    if (completed.error) throw new Error("Audit result could not be saved");
    return NextResponse.json({ ...result, runId, snapshotId, reused: false }, { headers });
  } catch (error) {
    await admin.from("rt_audit_runs").update({ status: "failed", error_code: "LOCAL_AUDIT_FAILED", finished_at: new Date().toISOString() })
      .eq("id", runId).eq("status", "running");
    return NextResponse.json({ error: "Local audit unavailable", detail: error instanceof Error ? error.message : "Unknown error" }, { status: 503, headers });
  }
}

import { NextResponse } from "next/server";
import { validSessionToken, readAuditJob, toView, updateAuditJob } from "@/lib/audit/secure-store";

export const runtime = "nodejs";

function noStore(body: unknown, status = 200) {
  return NextResponse.json(body, { status, headers: { "cache-control": "no-store" } });
}

async function sessionOwnsJob(id: string, request: Request) {
  const job = await readAuditJob(id);
  if (!job) return null;
  const token = request.headers.get("cookie")?.match(new RegExp(`(?:^|;\\s*)audit_session_${id}=([^;]+)`))?.[1];
  return (await validSessionToken(id, job.expiresAt, token ? decodeURIComponent(token) : undefined)) ? job : null;
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const job = await sessionOwnsJob(id, request);
    if (!job) return noStore({ message: "This audit session is unavailable or has expired." }, 404);
    return noStore(toView(job));
  } catch {
    return noStore({ message: "The audit status is temporarily unavailable." }, 503);
  }
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const job = await sessionOwnsJob(id, request);
    if (!job) return noStore({ message: "This audit session is unavailable or has expired." }, 404);
    const next = await updateAuditJob(id, (current) => ({
      ...current,
      progress: current.progress.status === "complete" || current.progress.status === "failed"
        ? current.progress
        : { ...current.progress, status: "cancelled", message: "Cancelled by the browser session." },
    }));
    return noStore(toView(next));
  } catch {
    return noStore({ message: "The audit could not be cancelled." }, 503);
  }
}

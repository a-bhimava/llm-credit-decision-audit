import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { NextResponse } from "next/server";
import { getCaseDefinition } from "@/lib/reasontrace/cases";
import { documents, type DocumentId } from "@/lib/reasontrace/demo";
import { localFixturesEnabled } from "@/lib/reasontrace/local-mode";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "private, no-store" };

export async function GET(request: Request) {
  if (!localFixturesEnabled()) return NextResponse.json({ error: "Not found" }, { status: 404, headers });
  const url = new URL(request.url);
  const item = getCaseDefinition(url.searchParams.get("case") ?? "");
  const documentId = url.searchParams.get("document") as DocumentId;
  if (!item || !documents.some(doc => doc.id === documentId)) {
    return NextResponse.json({ error: "Unknown synthetic document" }, { status: 404, headers });
  }
  const relative = item.label === "RT-SYN-001" ? `${documentId}.png` : `${item.label}/${documentId}.png`;
  try {
    const bytes = await readFile(resolve(process.cwd(), "..", "fixtures", "reasontrace", relative));
    return new NextResponse(new Uint8Array(bytes), {
      headers: { ...headers, "Content-Type": "image/png", "X-Content-Type-Options": "nosniff" },
    });
  } catch {
    return NextResponse.json({ error: "Synthetic document unavailable" }, { status: 503, headers });
  }
}

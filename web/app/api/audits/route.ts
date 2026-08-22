import { NextResponse } from "next/server";
import { start } from "workflow/api";
import { IntakeValidationError, parseAuditIntake } from "@/lib/audit/intake";
import { buildPreflight } from "@/lib/audit/pricing";
import { RuntimeConfigurationError, getRuntimeConfiguration } from "@/lib/audit/runtime";
import { createAuditJob, reserveDailySpend, updateAuditJob } from "@/lib/audit/secure-store";
import { auditRunWorkflow } from "@/workflows/audit-run";

export const runtime = "nodejs";

function response(body: unknown, status = 200) {
  return NextResponse.json(body, { status, headers: { "cache-control": "no-store" } });
}

export async function POST(request: Request) {
  try {
    const contentLength = Number(request.headers.get("content-length") ?? "0");
    if (contentLength > 16_384) return response({ message: "The facts-only request is too large." }, 413);
    const intake = parseAuditIntake(await request.json());
    const preflight = buildPreflight(intake.facts);
    if (preflight.estimatedUsdUpper > preflight.jobUsdCap) {
      return response({ message: "The conservative preflight exceeds the $2.00 job cap; narrow the scenario." }, 422);
    }
    getRuntimeConfiguration();
    const admitted = await reserveDailySpend(preflight.estimatedUsdUpper, preflight.dailyUsdCap);
    if (!admitted) return response({ message: "The daily audit budget is reserved. Try again tomorrow." }, 429);
    const { job, sessionToken } = await createAuditJob(intake, preflight);
    const workflow = await start(auditRunWorkflow, [job.id]);
    await updateAuditJob(job.id, (current) => ({ ...current, workflowRunId: workflow.runId }));
    const result = response({ ...job, workflowRunId: workflow.runId }, 202);
    result.cookies.set(`audit_session_${job.id}`, sessionToken, { httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/api/audits", maxAge: 60 * 60 });
    return result;
  } catch (error) {
    if (error instanceof IntakeValidationError) return response({ message: error.message }, 400);
    if (error instanceof RuntimeConfigurationError) return response({ message: error.message }, 503);
    console.error("API Error in POST /api/audits:", error);
    return response({ message: "The private audit service is temporarily unavailable." }, 503);
  }
}

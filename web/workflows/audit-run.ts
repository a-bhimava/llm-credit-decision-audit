import { FatalError } from "workflow";
import { updateAuditJob } from "@/lib/audit/secure-store";

async function markRunning(jobId: string) {
  "use step";
  console.info("audit workflow starting", { jobId });
  await updateAuditJob(jobId, (job) => ({ ...job, progress: { ...job.progress, status: "running", message: "The audit runner is starting." } }));
}

async function failAsIncomplete(jobId: string) {
  "use step";
  await updateAuditJob(jobId, (job) => ({ ...job, progress: { ...job.progress, status: "failed", message: "The TypeScript port is incomplete; no provider calls were made." } }));
  throw new FatalError("The complete TypeScript audit engine is not available.");
}

/**
 * Receives only an opaque job ID. Facts are decrypted inside Node-capable steps and are never
 * passed in workflow arguments or returned through workflow metadata.
 */
export async function auditRunWorkflow(jobId: string) {
  "use workflow";
  await markRunning(jobId);
  await failAsIncomplete(jobId);
}

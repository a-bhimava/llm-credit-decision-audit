import { FatalError, fetch as workflowFetch } from "workflow";
import { readAuditJob, updateAuditJob } from "@/lib/audit/secure-store";
import { GeminiClient } from "@/lib/audit/providers/gemini";
import { ModelRequest, ModelResponse, ModelClient } from "@/lib/audit/providers/client";
import { Budget } from "@/lib/audit/run/budget";
import { runEpisode, episodePromptHash } from "@/lib/audit/env/episode";
import { policy } from "@/lib/audit/policy";
import { buildApplicant } from "@/lib/audit/intake";
import { buildApplicationPacket } from "@/lib/audit/render/packet";
import { applicantContentId, episodeInputHash } from "@/lib/audit/ids";
import { applicantReferenceFor } from "@/lib/audit/canonical";

/**
 * Creates a fresh, scoped ModelClient for a given modelId.
 * Each call returns a new object — never a shared/mutated global — so that
 * concurrent Vercel lambda invocations cannot cross-contaminate each other.
 */
function makeWorkflowClient(modelId: string): ModelClient {
  return {
    modelId,
    async complete(req: ModelRequest): Promise<ModelResponse> {
      "use step";
      const client = new GeminiClient(modelId);
      try {
        return await client.complete(req);
      } catch (e: any) {
        if (e.isTerminal) {
          throw new FatalError(e.message);
        }
        throw e;
      }
    }
  };
}

async function markRunning(jobId: string) {
  "use step";
  console.info("audit workflow starting", { jobId });
  await updateAuditJob(jobId, (job) => ({ ...job, progress: { ...job.progress, status: "running", message: "The audit runner is starting." } }), workflowFetch);
}

async function markComplete(jobId: string) {
  "use step";
  await updateAuditJob(jobId, (job) => ({ ...job, progress: { ...job.progress, status: "completed", message: "Audit completed successfully." } }), workflowFetch);
}

export async function auditRunWorkflow(jobId: string) {
  "use workflow";
  await markRunning(jobId);

  const jobStep = async () => {
    "use step";
    const job = await readAuditJob(jobId, workflowFetch);
    if (!job) throw new FatalError("Audit job not found or expired.");
    const applicant = buildApplicant(job.input);
    return { job, applicant };
  };
  const { job, applicant } = await jobStep();

  try {
    const reserveStep = async () => {
      "use step";
      try {
        const budget = new Budget(job.preflight);
        await budget.reserveDailyBudget();
      } catch (e: any) {
        throw new FatalError(e.message || "Failed to reserve budget.");
      }
    };
    await reserveStep();

    const textStep = async () => {
      "use step";
      await updateAuditJob(jobId, (j) => ({ ...j, progress: { ...j.progress, message: "Building application packet…" } }), workflowFetch);
      return JSON.stringify(buildApplicationPacket(applicant));
    };
    const applicationText = await textStep();

    const episodeStep = async () => {
      "use step";
      await updateAuditJob(jobId, (j) => ({ ...j, progress: { ...j.progress, message: "Running LLM evaluation episode…" } }), workflowFetch);
      // Create a fresh scoped client — never mutate a global.
      const episodeModelId = "gemini-2.5-flash-lite";
      const episodeClient = makeWorkflowClient(episodeModelId);
      
      const trial = {
        episode_id: "test-episode-1",
        applicant_id: applicant.applicant_id,
        applicant_content_id: applicantContentId(applicant),
        arm_id: "baseline",
        render_id: "json" as any,
        trial_index: 0,
        model_id: episodeModelId,
        prompt_hash: episodePromptHash(policy as any, "coded"),
        input_hash: episodeInputHash(applicant, applicationText, applicantReferenceFor(applicant), "json"),
        seed: 12345
      };

      return await runEpisode(
        trial,
        applicant,
        policy as any,
        applicationText,
        episodeClient,
        "coded",
        10
      );
    };
    const trajectory = await episodeStep();

    const saveStep = async () => {
      "use step";
      await updateAuditJob(jobId, (j) => ({
        ...j,
        progress: {
          ...j.progress,
          message: `Completed baseline trial`,
          completedEpisodes: [...((j.progress as any).completedEpisodes || []), trajectory]
        }
      }), workflowFetch);
    };
    await saveStep();

    await markComplete(jobId);
  } catch (error: any) {
    await updateAuditJob(jobId, (j) => ({ ...j, progress: { ...j.progress, status: "failed", message: error.message || "An error occurred during the audit workflow." } }), workflowFetch);
    throw error;
  }
}

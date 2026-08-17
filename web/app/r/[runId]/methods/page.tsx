import type { Metadata } from "next";
import { getManifest, getRun, loadRunIndex } from "@/lib/evidence";
import { DefinitionList, RunNav, Shell } from "@/components/site";

export const dynamic = "force-static";
export const dynamicParams = false;
type Props = { params: Promise<{ runId: string }> };

export async function generateStaticParams() {
  return (await loadRunIndex()).runs.map((run) => ({ runId: run.run_id }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { runId } = await params;
  return { title: `Methods · ${(await getRun(runId)).label}` };
}

export default async function MethodsPage({ params }: Props) {
  const { runId } = await params;
  const run = await getRun(runId);
  const manifest = await getManifest(runId);
  const prereg = manifest.prereg_ref as Record<string, unknown> | null;
  return (
    <Shell run={run}>
      <RunNav run={run} />
      <main className="page prose">
        <p className="eyebrow">Method</p>
        <h1>Paired interventions, not an LLM judge.</h1>
        <p>Each check compares matched base and counterfactual episodes under a fixed policy and seed schedule. The site reports only statistics generated from the exported evidence bundle.</p>
        <h2>How to read a result</h2>
        <p>Pair IDs identify a contrast; cluster IDs identify the originating applicant used for clustered resampling. Exact McNemar tests use discordant matched trials, while intervals are cluster-resampled and disclose their fallback method.</p>
        <h2>Pre-registration</h2>
        <DefinitionList values={[
          ["Tag", prereg?.git_tag ? String(prereg.git_tag) : "—"],
          ["Frozen at", prereg?.frozen_at ? String(prereg.frozen_at) : "—"],
          ["SHA-256", prereg?.sha256 ? String(prereg.sha256) : "—"],
          ["Suite", run.suite],
        ]} />
        <h2>Limits</h2>
        <p>This audit uses synthetic applicants and policy. It describes the declared agent, prompt, tool scaffold, and policy configuration; it is not a compliance certification or a general claim about a model family.</p>
      </main>
    </Shell>
  );
}


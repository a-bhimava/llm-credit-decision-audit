import type { Metadata } from "next";
import Link from "next/link";
import { field, getChecks, getRun, loadRunIndex } from "@/lib/evidence";
import { RunNav, Shell } from "@/components/site";

export const dynamic = "force-static";
export const dynamicParams = false;

type Props = { params: Promise<{ runId: string, agent: string }> };

export async function generateStaticParams() {
  const index = await loadRunIndex();
  const sweeps = index.runs.filter(r => r.run_id.startsWith("sweep_"));
  const params: { runId: string, agent: string }[] = [];
  for (const sweep of sweeps) {
    try {
      const defects = await import(`@/public/runs/${sweep.run_id}/planted-defects.json`);
      if (defects.agents && Array.isArray(defects.agents)) {
        for (const a of defects.agents) {
          if (a.agent) params.push({ runId: sweep.run_id, agent: a.agent.replace(":", "_") });
        }
      }
    } catch (e) {}
  }
  return params;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { runId, agent } = await params;
  return { title: `Checks · ${(await getRun(runId)).label}` };
}

export default async function ChecksPage({ params }: Props) {
  const { runId, agent } = await params;
  const run = await getRun(runId);
  const checks = await getChecks(runId, agent);
  return (
    <Shell run={run}>
      <RunNav run={run} />
      <main className="page">
        <p className="eyebrow">Declared check families</p>
        <h1>Every check points back to its paired evidence.</h1>
        <div className="checkGrid">
          {checks.map((check) => {
            const id = field(check, "check");
            return (
              <Link className="checkCard" key={id} href={`/r/${encodeURIComponent(runId)}/checks/${encodeURIComponent(id)}`}>
                <span>{field(check, "family")}</span>
                <strong>{field(check, "label", id)}</strong>
                <small>{field(check, "n_results")} results · {field(check, "n_pairs")} pairs</small>
              </Link>
            );
          })}
        </div>
      </main>
    </Shell>
  );
}


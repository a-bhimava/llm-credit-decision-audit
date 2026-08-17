import type { Metadata } from "next";
import Link from "next/link";
import { field, getChecks, getRun, loadRunIndex } from "@/lib/evidence";
import { RunNav, Shell } from "@/components/site";

export const dynamic = "force-static";
export const dynamicParams = false;

type Props = { params: Promise<{ runId: string }> };

export async function generateStaticParams() {
  return (await loadRunIndex()).runs.map((run) => ({ runId: run.run_id }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { runId } = await params;
  return { title: `Checks · ${(await getRun(runId)).label}` };
}

export default async function ChecksPage({ params }: Props) {
  const { runId } = await params;
  const run = await getRun(runId);
  const checks = await getChecks(runId);
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


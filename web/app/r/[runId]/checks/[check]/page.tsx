import type { Metadata } from "next";
import Link from "next/link";
import { decodeCheckRows, entries, field, getCheckRows, getChecks, getEstimates, getRun, loadRunIndex } from "@/lib/evidence";
import { ForestPlot, McNemarPanel } from "@/components/visuals";
import { RunNav, Shell, Status } from "@/components/site";

export const dynamic = "force-static";
export const dynamicParams = false;
type Props = { params: Promise<{ runId: string; check: string }> };

export async function generateStaticParams() {
  const index = await loadRunIndex();
  const all = await Promise.all(index.runs.map(async (run) => (await getChecks(run.run_id)).map((check) => ({
    runId: run.run_id,
    check: field(check, "check"),
  }))));
  return all.flat();
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { runId, check } = await params;
  return { title: `${check} · ${(await getRun(runId)).label}` };
}

export default async function CheckPage({ params }: Props) {
  const { runId, check } = await params;
  const run = await getRun(runId);
  const [rows, estimatesDocument] = await Promise.all([getCheckRows(runId, check), getEstimates(runId)]);
  const rowsData = decodeCheckRows(rows);
  const estimates = estimatesDocument
    ? entries(estimatesDocument.estimates, "estimates").filter((estimate) => estimate.check === check)
    : [];
  const primary = estimates[0] ?? null;

  return (
    <Shell run={run}>
      <RunNav run={run} />
      <main className="page">
        <p className="eyebrow">Check detail</p>
        <h1>{primary ? field(primary, "label", check) : check}</h1>
        <p className="lead">Results remain in the preregistered order and link to their paired source records.</p>
        {estimates.length ? <section className="section"><ForestPlot estimates={estimates} /></section> : null}
        {primary ? <section className="section"><h2>Matched discordance</h2><McNemarPanel estimate={primary} /></section> : null}
        <section className="tableWrap">
          <table>
            <thead><tr><th>Status</th><th>Applicant</th><th>Pair</th><th>Effect</th><th>Matched trials</th></tr></thead>
            <tbody>
              {rowsData.map((row) => {
                const pairId = field(row, "pair_id");
                return (
                  <tr key={field(row, "test_id")}>
                    <td><Status status={field(row, "status")} /></td>
                    <td>{field(row, "applicant_id")}</td>
                    <td><Link href={`/r/${encodeURIComponent(runId)}/pairs/${encodeURIComponent(pairId)}`}>{pairId}</Link></td>
                    <td>{field(row, "effect")}</td>
                    <td>{field(row, "matched_trials")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      </main>
    </Shell>
  );
}

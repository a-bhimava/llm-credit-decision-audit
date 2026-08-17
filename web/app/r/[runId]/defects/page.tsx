import type { Metadata } from "next";
import { DefectPlot } from "@/components/visuals";
import { entries, field, getDefects, getRun, loadRunIndex, percent, type JsonObject } from "@/lib/evidence";
import { RunNav, Shell, Status } from "@/components/site";

export const dynamic = "force-static";
export const dynamicParams = false;

type Props = { params: Promise<{ runId: string }> };

export async function generateStaticParams() {
  return (await loadRunIndex()).runs.map((run) => ({ runId: run.run_id }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { runId } = await params;
  return { title: `Validation · ${(await getRun(runId)).label}` };
}

export default async function DefectsPage({ params }: Props) {
  const { runId } = await params;
  const run = await getRun(runId);
  const sourceRunId = run.validated_by_run_id ?? run.run_id;
  const defects = await getDefects(sourceRunId);
  const summary = defects?.summary && typeof defects.summary === "object" && !Array.isArray(defects.summary)
    ? defects.summary as JsonObject
    : {};
  const positiveControl = summary.positive_control && typeof summary.positive_control === "object" && !Array.isArray(summary.positive_control)
    ? summary.positive_control as JsonObject
    : null;
  const agents = defects ? entries(defects.agents, "agents") : [];

  return (
    <Shell run={run}>
      <RunNav run={run} />
      <main className="page">
        <p className="eyebrow">Harness validation</p>
        <h1>Known defects, declared before measurement.</h1>
        <p className="lead">Each point compares a scripted control’s expected behavior with observed results.</p>
        {defects ? (
          <>
            <section className="metricGrid">
              <div><span>Caught</span><strong>{field(summary, "caught")}</strong></div>
              <div><span>Missed</span><strong>{field(summary, "missed")}</strong></div>
              <div><span>False alarms</span><strong>{field(summary, "false_alarms")}</strong></div>
              <div><span>Positive-control pass rate</span><strong>{percent(positiveControl?.pass_rate)}</strong></div>
            </section>
            <section className="section">
              <DefectPlot agents={agents} />
            </section>
            <section className="tableWrap">
              <table>
                <thead><tr><th>Control</th><th>Declared defect</th><th>Observed verdict</th></tr></thead>
                <tbody>
                  {agents.map((agent) => (
                    <tr key={field(agent, "agent")}>
                      <td>{field(agent, "agent")}</td>
                      <td>{field(agent, "defect")}</td>
                      <td><Status status={field(agent, "verdict")} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </>
        ) : <p className="emptyState">No planted-defect bundle is linked to this run.</p>}
      </main>
    </Shell>
  );
}

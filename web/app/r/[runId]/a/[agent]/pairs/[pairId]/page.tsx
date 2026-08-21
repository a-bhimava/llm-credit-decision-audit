import type { Metadata } from "next";
import { entries, field, getPair, getPairs, getRun, loadRunIndex, percent, type JsonObject } from "@/lib/evidence";
import { RunNav, Shell, Status } from "@/components/site";

export const dynamic = "force-static";
export const dynamicParams = true;
type Props = { params: Promise<{ runId: string; pairId: string; agent: string }> };

export async function generateStaticParams() {
  return [];
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { runId, pairId, agent } = await params;
  return { title: `Pair ${pairId.slice(0, 18)} · ${(await getRun(runId)).label}` };
}

function FactRows({ facts }: Readonly<{ facts: JsonObject }>) {
  return (
    <dl className="factList">
      {Object.entries(facts).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{Array.isArray(value) ? value.join(", ") : String(value)}</dd></div>)}
    </dl>
  );
}

function TrialList({ trials }: Readonly<{ trials: JsonObject[] }>) {
  return (
    <ol className="trialList">
      {trials.map((trial) => {
        const decision = trial.decision as JsonObject | null;
        return <li key={field(trial, "episode_id")}><Status status={decision ? field(decision, "outcome") : field(trial, "termination")} /><code>{field(trial, "episode_id")}</code></li>;
      })}
    </ol>
  );
}

export default async function PairPage({ params }: Props) {
  const { runId, pairId, agent } = await params;
  const [run, pair] = await Promise.all([getRun(runId), getPair(runId, pairId)]);
  const applicant = pair.applicant as JsonObject;
  const base = applicant.base as JsonObject;
  const cf = applicant.cf as JsonObject;
  const diff = entries(applicant.diff, "diff");
  const sides = pair.sides as JsonObject;
  const baseSide = sides.base as JsonObject;
  const cfSide = sides.cf as JsonObject;
  const hypothesis = pair.hypothesis as JsonObject;
  const metrics = pair.metrics as JsonObject;

  return (
    <Shell run={run}>
      <RunNav run={run} />
      <main className="page">
        <p className="eyebrow">Paired evidence</p>
        <h1>{field(pair, "check")}</h1>
        <p className="lead">{field(hypothesis, "plain_english")}</p>

        <section className="pairMetricGrid">
          <div><span>Base approval</span><strong>{percent(metrics.base_approve_rate)}</strong></div>
          <div><span>Counterfactual approval</span><strong>{percent(metrics.cf_approve_rate)}</strong></div>
          <div><span>Effect</span><strong>{percent(metrics.effect)}</strong></div>
          <div><span>Matched trials</span><strong>{field(metrics, "matched_trials")}/{field(metrics, "planned_trials")}</strong></div>
        </section>

        <section className="diffLedger">
          <div><p className="eyebrow">Base</p><FactRows facts={(base.facts as JsonObject) ?? {}} /></div>
          <div className="interventionColumn">
            <p className="eyebrow">Intervention record</p>
            {diff.map((item) => <div className={item.held_out === true ? "diffRow heldOut" : "diffRow"} key={field(item, "path")}><span>{item.held_out === true ? "⊘" : "→"}</span><span>{field(item, "display")}</span>{item.held_out === true ? <small>deliberately not repaired</small> : null}</div>)}
          </div>
          <div><p className="eyebrow">Counterfactual</p><FactRows facts={(cf.facts as JsonObject) ?? {}} /></div>
        </section>

        <section className="section twoColumn">
          <div><h2>Base trials</h2><TrialList trials={entries(baseSide.trials, "base trials")} /></div>
          <div><h2>Counterfactual trials</h2><TrialList trials={entries(cfSide.trials, "counterfactual trials")} /></div>
        </section>

        <section className="section provenancePanel">
          <h2>Traceability</h2>
          <dl className="definitionList">
            <div><dt>Pair ID</dt><dd>{field(pair, "pair_id")}</dd></div>
            <div><dt>Cluster ID</dt><dd>{field(pair, "cluster_id")}</dd></div>
            <div><dt>Source applicant</dt><dd>{field(applicant, "applicant_id")}</dd></div>
            <div><dt>Estimate support</dt><dd>{entries(pair.contributes_to, "contributes_to").map((entry) => field(entry, "estimate_id")).join(", ")}</dd></div>
          </dl>
        </section>
      </main>
    </Shell>
  );
}

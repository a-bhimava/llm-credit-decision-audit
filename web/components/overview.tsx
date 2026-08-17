import Link from "next/link";
import {
  entries,
  field,
  getDefects,
  getManifest,
  getPairs,
  getSummary,
  percent,
  type JsonObject,
  type RunIndexEntry,
} from "@/lib/evidence";
import { DefinitionList, EvidenceLabel, RunNav, Shell, Status } from "@/components/site";

function Headline({ headline, run }: Readonly<{ headline: JsonObject; run: RunIndexEntry }>) {
  const support = headline.support as JsonObject | undefined;
  const pairId = support?.exemplar_pair_id;
  return (
    <article className="headline">
      <span className="eyebrow">{field(headline, "label")}</span>
      <strong>{percent(headline.value)}</strong>
      <p>{field(headline, "statement")}</p>
      {typeof pairId === "string" ? (
        <Link href={`/r/${encodeURIComponent(run.run_id)}/pairs/${encodeURIComponent(pairId)}`}>
          Inspect supporting pair
        </Link>
      ) : null}
    </article>
  );
}

export async function RunOverview({ run }: Readonly<{ run: RunIndexEntry }>) {
  const [summary, manifest, pairs, defects] = await Promise.all([
    getSummary(run.run_id),
    getManifest(run.run_id),
    getPairs(run.run_id),
    getDefects(run.validated_by_run_id ?? run.run_id),
  ]);
  const headlines = summary ? entries(summary.headline, "headline") : [];
  const operational = summary ? (summary.operational as JsonObject) : null;
  const defectSummary = defects?.summary as JsonObject | undefined;

  return (
    <Shell run={run}>
      <RunNav run={run} />
      <main>
        <section className="hero">
          <div>
            <p className="eyebrow">Causal audit evidence</p>
            <h1>Can stated reasons explain the decision that was made?</h1>
            <p className="heroDeck">
              An inspectable record of paired interventions, decision traces, and exact
              statistical summaries.
            </p>
          </div>
          <aside className="resultsPanel" aria-label="Results panel">
            <EvidenceLabel run={run} />
            <dl>
              <div><dt>Applicants</dt><dd>{run.counts.applicants}</dd></div>
              <div><dt>Episodes</dt><dd>{run.counts.episodes.toLocaleString()}</dd></div>
              <div><dt>Pairs</dt><dd>{run.counts.pairs}</dd></div>
              <div><dt>Tests</dt><dd>{run.counts.tests}</dd></div>
            </dl>
          </aside>
        </section>

        {summary ? (
          <section className="section">
            <div className="sectionTitle">
              <p className="eyebrow">Findings</p>
              <h2>What this run measured</h2>
            </div>
            <div className="headlineGrid">
              {headlines.map((headline) => <Headline key={field(headline, "id")} headline={headline} run={run} />)}
            </div>
          </section>
        ) : (
          <section className="section emptyState">
            <h2>This validation run has no model-result summary.</h2>
            <p>Use the validation table to inspect how the harness performs against declared defects.</p>
          </section>
        )}

        <section className="section splitSection">
          <div>
            <p className="eyebrow">Run record</p>
            <h2>Provenance at a glance</h2>
            <DefinitionList
              values={[
                ["Model", run.model.model_id],
                ["Provider", run.model.provider],
                ["Suite", run.suite],
                ["Commit", field(manifest.git as JsonObject, "short")],
                ["Terminal status", field(manifest, "terminal_status")],
                ["Bundle", field((manifest.export as JsonObject) ?? {}, "bundle_sha256")],
              ]}
            />
            <Link href={`/r/${encodeURIComponent(run.run_id)}/integrity`}>Open integrity record</Link>
          </div>
          <div className="validationCard">
            <p className="eyebrow">Harness validation</p>
            <h2>{defectSummary ? `${field(defectSummary, "caught")} planted defects caught` : "Validation record"}</h2>
            {defectSummary ? (
              <p>
                {field(defectSummary, "false_alarms")} false alarms · {field(defectSummary, "missed")} missed
              </p>
            ) : null}
            <Link href={`/r/${encodeURIComponent(run.validated_by_run_id ?? run.run_id)}/defects`}>
              Inspect validation
            </Link>
          </div>
        </section>

        {operational ? (
          <section className="section operationalStrip" aria-label="Operational outcomes">
            <div><span>Pair completion</span><strong>{percent(operational.pair_completion_rate)}</strong></div>
            <div><span>Refusal rate</span><strong>{percent(operational.refusal_rate)}</strong></div>
            <div><span>Reason-count violations</span><strong>{field(operational, "reason_count_violations")}</strong></div>
            <div><span>Exemplar pairs</span><strong>{pairs.length}</strong></div>
          </section>
        ) : null}

        <section className="section reproBlock">
          <p className="eyebrow">Reproduce</p>
          <h2>Check the published claims yourself</h2>
          <pre>{`credit-audit verify --run ${run.run_id} --strict`}</pre>
          <Link href={`/r/${encodeURIComponent(run.run_id)}/methods`}>Read the method and limits</Link>
        </section>
      </main>
    </Shell>
  );
}


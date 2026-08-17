import type { Metadata } from "next";
import { entries, field, getIntegrity, getManifest, getRun, loadRunIndex, type JsonObject } from "@/lib/evidence";
import { DefinitionList, RunNav, Shell } from "@/components/site";

export const dynamic = "force-static";
export const dynamicParams = false;
type Props = { params: Promise<{ runId: string }> };

export async function generateStaticParams() {
  return (await loadRunIndex()).runs.map((run) => ({ runId: run.run_id }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { runId } = await params;
  return { title: `Integrity · ${(await getRun(runId)).label}` };
}

export default async function IntegrityPage({ params }: Props) {
  const { runId } = await params;
  const run = await getRun(runId);
  const [integrity, manifest] = await Promise.all([getIntegrity(runId), getManifest(runId)]);
  const verify = entries(integrity.verify, "verify commands");
  const sources = entries(integrity.source_artifacts, "source artifacts");
  const git = integrity.git && typeof integrity.git === "object" && !Array.isArray(integrity.git)
    ? integrity.git as JsonObject
    : {};

  return (
    <Shell run={run}>
      <RunNav run={run} />
      <main className="page">
        <p className="eyebrow">Integrity chain</p>
        <h1>Every claim has a hash, source artifact, and command.</h1>
        <DefinitionList values={[
          ["Bundle SHA-256", field(integrity, "bundle_sha256")],
          ["Run commit", field(git, "commit")],
          ["Worktree", field(git, "dirty")],
          ["Terminal status", field(manifest, "terminal_status")],
        ]} />
        <section className="section">
          <h2>Independent checks</h2>
          <div className="commandList">
            {verify.map((item) => <div key={field(item, "claim")}><strong>{field(item, "claim")}</strong><code>{field(item, "cmd")}</code></div>)}
          </div>
        </section>
        <section className="section tableWrap">
          <h2>Raw artifact references</h2>
          <table><thead><tr><th>Artifact</th><th>Lines</th><th>SHA-256</th></tr></thead>
            <tbody>{sources.map((item) => <tr key={field(item, "path")}><td>{field(item, "path")}</td><td>{field(item, "lines")}</td><td><code>{field(item, "sha256")}</code></td></tr>)}</tbody>
          </table>
        </section>
      </main>
    </Shell>
  );
}

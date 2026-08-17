import Link from "next/link";
import { displayDate, type RunIndexEntry } from "@/lib/evidence";

export function Shell({
  children,
  run,
}: Readonly<{ children: React.ReactNode; run?: RunIndexEntry }>) {
  return (
    <div className="shell">
      <header className="siteHeader">
        <Link className="wordmark" href="/" aria-label="Credit Decision Audit home">
          <span>Credit</span>
          <span>Decision</span>
          <span>Audit</span>
        </Link>
        {run ? (
          <div className="runStamp">
            <span>{run.model.model_id}</span>
            <span aria-hidden="true">·</span>
            <span>{displayDate(run.created_at)}</span>
          </div>
        ) : null}
      </header>
      {children}
      <footer className="siteFooter">
        <span>Evidence is generated from committed audit bundles.</span>
        <Link href="/audit">Audit Studio</Link>
        <a href="/runs/index.json">Run index</a>
      </footer>
    </div>
  );
}

export function RunNav({ run }: Readonly<{ run: RunIndexEntry }>) {
  return (
    <nav className="runNav" aria-label="Run navigation">
      <Link href={"/r/" + encodeURIComponent(run.run_id)}>Overview</Link>
      <Link href={"/r/" + encodeURIComponent(run.run_id) + "/checks"}>Checks</Link>
      <Link href={"/r/" + encodeURIComponent(run.run_id) + "/defects"}>Validation</Link>
      <Link href={"/r/" + encodeURIComponent(run.run_id) + "/integrity"}>Integrity</Link>
      <Link href={"/r/" + encodeURIComponent(run.run_id) + "/methods"}>Methods</Link>
    </nav>
  );
}

export function EvidenceLabel({ run }: Readonly<{ run: RunIndexEntry }>) {
  return run.evidence_label ? <span className="evidenceLabel">{run.evidence_label}</span> : null;
}

export function Status({ status }: Readonly<{ status: string }>) {
  const normalized = status.toLowerCase();
  const kind =
    normalized === "pass" || normalized === "faithful" || normalized === "caught"
      ? "good"
      : normalized === "fail" || normalized === "deficient" || normalized === "missed"
        ? "bad"
        : "neutral";
  const glyph = kind === "good" ? "●" : kind === "bad" ? "×" : "○";
  return (
    <span className={"status status-" + kind}>
      <span aria-hidden="true">{glyph}</span>
      {status}
    </span>
  );
}

export function DefinitionList({
  values,
}: Readonly<{ values: ReadonlyArray<readonly [string, string]> }>) {
  return (
    <dl className="definitionList">
      {values.map(([term, detail]) => (
        <div key={term}>
          <dt>{term}</dt>
          <dd>{detail}</dd>
        </div>
      ))}
    </dl>
  );
}

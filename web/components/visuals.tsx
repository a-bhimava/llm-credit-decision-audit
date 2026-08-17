import { percent, type JsonObject } from "@/lib/evidence";

export function CIRail({ estimate, n }: Readonly<{ estimate: JsonObject; n: number }>) {
  const point = typeof estimate.point === "number" ? estimate.point : 0;
  const ci = Array.isArray(estimate.ci95) ? estimate.ci95 : null;
  const left = ci && typeof ci[0] === "number" ? ci[0] : point;
  const right = ci && typeof ci[1] === "number" ? ci[1] : point;
  const lowPrecision = n < 30 || right - left > 0.4;
  const scale = (value: number) => Math.max(0, Math.min(100, value * 100));
  return (
    <div className="ciRail" aria-label={`${estimate.label}: ${percent(point)}, sample size ${estimate.n}`}>
      <div className="ciRailTrack" aria-hidden="true">
        <span className="ciRailNull" />
        <span className="ciRailInterval" style={{ left: scale(left) + "%", width: scale(right - left) + "%" }} />
        <span className="ciRailPoint" style={{ left: scale(point) + "%" }} />
      </div>
      <div className="ciRailMeta">
        <span>{percent(point)}</span>
        <span>CI {ci ? `${percent(left)}–${percent(right)}` : "not estimable"}</span>
        <span>n = {n}</span>
        {lowPrecision ? <span className="precisionFlag">low precision</span> : null}
      </div>
    </div>
  );
}

export function ForestPlot({ estimates }: Readonly<{ estimates: JsonObject[] }>) {
  return (
    <div className="forestPlot" role="list" aria-label="Pre-registered estimates in declared order">
      {estimates.map((estimate) => {
        if (typeof estimate.n !== "number") throw new Error(`Estimate ${String(estimate.estimate_id)} has no sample size`);
        return (
          <div className="forestRow" role="listitem" key={String(estimate.estimate_id)}>
            <div>
              <strong>{String(estimate.label)}</strong>
              <span>{String(estimate.check)}</span>
            </div>
            <CIRail estimate={estimate} n={estimate.n} />
          </div>
        );
      })}
    </div>
  );
}

export function McNemarPanel({ estimate }: Readonly<{ estimate: JsonObject }>) {
  const test = estimate.test && typeof estimate.test === "object" ? (estimate.test as JsonObject) : null;
  if (!test) return <p className="muted">No discordant-pair test applies to this estimate.</p>;
  return (
    <section className="mcnemar">
      <div>
        <span>Adverse → approve</span>
        <strong>{String(test.b ?? "—")}</strong>
      </div>
      <div>
        <span>Approve → adverse</span>
        <strong>{String(test.c ?? "—")}</strong>
      </div>
      <div>
        <span>Exact p</span>
        <strong>{Number(test.p).toExponential(2)}</strong>
      </div>
      <div>
        <span>BH q</span>
        <strong>{Number(test.q_bh).toExponential(2)}</strong>
      </div>
    </section>
  );
}

export function DefectPlot({ agents }: Readonly<{ agents: JsonObject[] }>) {
  return (
    <div className="defectPlot" role="list" aria-label="Expected and observed planted-defect outcomes">
      {agents.map((agent) => {
        const mustFire = Array.isArray(agent.must_fire) ? agent.must_fire.length : 0;
        const caught = agent.verdict === "CAUGHT";
        return (
          <div className="defectRow" role="listitem" key={String(agent.agent)}>
            <div>
              <strong>{String(agent.agent).replace("scripted:", "")}</strong>
              <span>{String(agent.defect)}</span>
            </div>
            <div className="defectDots" aria-label={caught ? "caught" : "not caught"}>
              <span className="expectedDot" title={`Expected checks: ${mustFire}`} />
              <span className={caught ? "observedDot observedCaught" : "observedDot"} />
            </div>
            <span className={caught ? "plotVerdict goodText" : "plotVerdict badText"}>
              {String(agent.verdict)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

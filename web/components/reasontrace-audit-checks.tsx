"use client";

import { useState } from "react";
import { AnimatedContent } from "@/components/react-bits/animated-content";
import { ReasonTracePairComparison } from "@/components/reasontrace-pair-comparison";
import { representativeCheckIndex } from "@/lib/reasontrace/evidence-path";

export type AuditCheck = {
  check: string; status: string; pair_id: string; effect: number | null;
  observed: Record<string, unknown>; expected: string; notes: string;
  changes: { field: string; before: string; after: string }[];
  base_trajectory_ids: string[]; cf_trajectory_ids: string[];
};

const names: Record<string, string> = {
  "reason_validity.fabrication": "Unsupported stated reason",
  "reason_validity.joint_sufficiency": "Do the cited reasons jointly explain denial?",
  "reason_validity.necessity_loo": "Is a cited reason independently binding?",
  "reason_validity.omission_scan": "Was a binding reason omitted?",
  "reason_validity.base_inapplicable": "Decision was not adverse",
};

export function ReasonTraceAuditChecks({ checks }: { checks: AuditCheck[] }) {
  const [openPair, setOpenPair] = useState<string | null>(
    () => {
      const selected = representativeCheckIndex(checks);
      return selected === null ? null : checks[selected].pair_id;
    },
  );
  const failures = checks.filter(check => check.status === "fail").length;
  const passes = checks.filter(check => check.status === "pass").length;
  const inapplicable = checks.filter(check => check.status === "inapplicable").length;

  return <>
    <div className="rt-check-overview">
      <h3 className="rt-check-title">Paired evidence</h3>
      <span>{failures} failed · {passes} passed{inapplicable > 0 ? ` · ${inapplicable} inapplicable` : ""}</span>
    </div>
    {checks.map((check, index) => {
      const expanded = openPair === check.pair_id;
      return <article className="rt-check" key={check.pair_id}>
        <button id={`rt-check-${index}`} type="button" className="rt-check-toggle" aria-expanded={expanded}
          onClick={() => setOpenPair(expanded ? null : check.pair_id)}>
          <span className={`rt-check-status ${check.status}`}>{check.status}</span>
          <strong>{names[check.check] || check.check}</strong>
          <span className="rt-check-chevron" aria-hidden="true">⌄</span>
        </button>
        <p className="rt-check-summary">{check.notes || check.expected}</p>
        {expanded && <AnimatedContent key={check.pair_id} className="rt-check-details">
          <div role="region" aria-label={`${names[check.check] || check.check} evidence`}>
            <ReasonTracePairComparison observed={check.observed} changes={check.changes} />
            <details><summary>Inspect trace IDs</summary><code>Pair {check.pair_id}<br />Original {check.base_trajectory_ids[0]}<br />Repaired {check.cf_trajectory_ids[0] || "not applicable"}</code></details>
          </div>
        </AnimatedContent>}
      </article>;
    })}
  </>;
}

"use client";

import dynamic from "next/dynamic";

const AuditGraph = dynamic(
  () => import("@/components/audit-graph").then(module => module.AuditGraph),
  { ssr: false },
);

export function AuditExecutionView({ progress }: { progress: string }) {
  return <section className="launchReaction" aria-label="Live audit execution">
    <AuditGraph liveProgress={progress} isDone={false} />
    <div className="auditExecutionStatus" role="status" aria-live="polite" aria-atomic="true">
      <strong>Live audit execution</strong>
      <p>{progress}</p>
    </div>
  </section>;
}

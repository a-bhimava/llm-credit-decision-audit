"use client";

import type { AuditIntakeIssue } from "@/lib/audit/intake-form";

export function AuditIntakeIssues({ issues }: { issues: readonly AuditIntakeIssue[] }) {
  if (issues.length === 0) return null;
  return <div className="intakeIssues" role="alert">
    <strong>Check these values before continuing</strong>
    <ul>{issues.map(issue => <li id={`audit-issue-${issue.field}`} key={issue.field}>{issue.message}</li>)}</ul>
  </div>;
}

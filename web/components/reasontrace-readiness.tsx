"use client";

import type { ReviewIssue } from "@/lib/reasontrace/demo";

export function ReasonTraceReadiness({ issues, onNavigate }: {
  issues: readonly ReviewIssue[];
  onNavigate: (issue: ReviewIssue) => void;
}) {
  return <div className={issues.length ? "rt-readiness blocked" : "rt-readiness ready"}>
    <strong>{issues.length ? `Needs review · ${issues.length} ${issues.length === 1 ? "item" : "items"}` : "Ready for audit"}</strong>
    {issues.length ? <>
      <p>Select an item to inspect its source or reviewed value.</p>
      <ul>{issues.map((issue, index) => <li key={`${index}-${issue.message}`}>
        {issue.target ? <button type="button" onClick={() => onNavigate(issue)}>
          <span>{issue.message}</span><span aria-hidden="true">↗</span>
        </button> : issue.message}
      </li>)}</ul>
    </> : <p>All three documents and decision-relevant extracted values are confirmed.</p>}
  </div>;
}

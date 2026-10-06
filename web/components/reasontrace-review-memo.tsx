"use client";

import { useMemo } from "react";
import type { CaseReview } from "@/lib/reasontrace/demo";
import { formatReviewMemo, type ReviewMemoAudit } from "@/lib/reasontrace/review-memo";

export function ReasonTraceReviewMemo({ caseLabel, review, result }: {
  caseLabel: string;
  review: CaseReview;
  result: ReviewMemoAudit;
}) {
  const memo = useMemo(() => formatReviewMemo(caseLabel, review, result), [caseLabel, review, result]);

  function download() {
    const url = URL.createObjectURL(new Blob([memo], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `reasontrace-${caseLabel.replace(/[^a-z0-9-]/gi, "-")}-review.txt`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
  }

  return <details className="rt-review-memo">
    <summary>Review memo <span>Inspect and download plain text</span></summary>
    <div>
      <p>This memo contains confirmed fictional facts and scripted audit evidence. It contains no document images or private links.</p>
      <button type="button" onClick={download}>Download review memo</button>
      <pre>{memo}</pre>
    </div>
  </details>;
}

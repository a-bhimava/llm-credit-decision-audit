"use client";

import type { ExtractionSource } from "@/lib/reasontrace/demo";

export function ReasonTraceExtractionToolbar({ localFixtures, source, busy, extracting, message,
  onReload, onUseFixture, onExtractLive }: {
  localFixtures: boolean;
  source: ExtractionSource;
  busy: boolean;
  extracting: boolean;
  message: string;
  onReload: () => void;
  onUseFixture: () => void;
  onExtractLive: () => void;
}) {
  const liveCandidates = source === "interfaze";
  const description = localFixtures
    ? "Saved synthetic extraction; review progress stays in this browser."
    : liveCandidates
      ? "Showing candidate values from a live Interfaze response. Confirm each against its source page."
      : "Showing saved synthetic extraction. Live mode calls Interfaze from the server.";

  return <>
    <div className="rt-toolbar">
      <div><strong>Extraction mode</strong><span>{description}</span></div>
      <div className="rt-toolbar-actions">
        <button type="button" onClick={liveCandidates ? onUseFixture : onReload} disabled={busy}>
          {liveCandidates ? "Use saved fixture" : "Reload saved case"}
        </button>
        {!localFixtures && <button type="button" className="rt-outline" onClick={onExtractLive} disabled={busy}>
          {extracting ? "Reading documents…" : "Run with Interfaze"}
        </button>}
      </div>
    </div>
    {message && <p className="rt-message" role="status">{message}</p>}
  </>;
}

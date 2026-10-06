"use client";

import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export function ReproCommand({ command }: { command: string }) {
  const [status, setStatus] = useState<"idle" | "copied" | "unavailable">("idle");
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (resetTimer.current) clearTimeout(resetTimer.current);
  }, []);

  async function copyCommand() {
    if (resetTimer.current) clearTimeout(resetTimer.current);
    try {
      await navigator.clipboard.writeText(command);
      setStatus("copied");
      resetTimer.current = setTimeout(() => setStatus("idle"), 2500);
    } catch {
      setStatus("unavailable");
    }
  }

  return <>
    <div className="reproHeader">
      <p className="eyebrow">Reproduce</p>
      <button type="button" className="reproCopy" onClick={copyCommand}>
        {status === "copied" ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
        {status === "copied" ? "Copied" : "Copy command"}
      </button>
    </div>
    <h2>Check the published claims yourself</h2>
    <pre><code>{command}</code></pre>
    <p className={status === "copied" ? "reproStatus reproStatusCopied" : "reproStatus"} role="status" aria-live="polite">
      {status === "copied" ? "Verification command copied." : status === "unavailable" ? "Clipboard unavailable. Select the command above to copy it." : ""}
    </p>
  </>;
}

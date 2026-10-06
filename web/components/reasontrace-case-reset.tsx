"use client";

import { useEffect, useRef, useState } from "react";

export function ReasonTraceCaseReset({ caseLabel, busy, onRestart }: {
  caseLabel: string;
  busy: boolean;
  onRestart: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (confirming) cancelRef.current?.focus();
  }, [confirming]);

  function dismiss() {
    setConfirming(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  }

  return <div className="rt-case-reset" onKeyDown={event => {
    if (event.key === "Escape" && confirming) { event.stopPropagation(); dismiss(); }
  }}>
    <button ref={triggerRef} type="button" disabled={busy} aria-expanded={confirming}
      onClick={() => setConfirming(value => !value)}>Restart this case</button>
    {confirming && <div className="rt-case-reset-confirm" role="group" aria-label={`Restart ${caseLabel}`}>
      <strong>Start {caseLabel} again?</strong>
      <p>This clears this browser’s saved review, corrections, history, and audit for this case. Other cases stay as they are.</p>
      <div>
        <button type="button" disabled={busy} onClick={() => { onRestart(); dismiss(); }}>
          Restart {caseLabel}
        </button>
        <button ref={cancelRef} type="button" onClick={dismiss}>Cancel</button>
      </div>
    </div>}
  </div>;
}

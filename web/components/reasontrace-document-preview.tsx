"use client";

import { useEffect, useRef, useState } from "react";

export function ReasonTraceDocumentPreview({ src, title, alt, onRefresh }: {
  src: string | undefined;
  title: string;
  alt: string;
  onRefresh: () => Promise<void>;
}) {
  const [failed, setFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const recoveryRef = useRef<HTMLButtonElement>(null);
  const focusRecoveryOnClose = useRef(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (expanded && !dialog.open) dialog.showModal();
    if (!expanded && dialog.open) dialog.close();
  }, [expanded]);

  async function refresh() {
    setRefreshing(true); setRefreshError("");
    try {
      await onRefresh();
      setFailed(false);
    } catch (error) {
      setRefreshError(error instanceof Error ? error.message : "The document preview could not be refreshed.");
    } finally { setRefreshing(false); }
  }

  function imageFailed() {
    focusRecoveryOnClose.current = dialogRef.current?.open ?? false;
    setFailed(true);
    setExpanded(false);
  }

  return <div className="rt-doc-preview">
    <div className="rt-doc-frame">
      {src && !failed ? <img src={src} alt={alt} onError={imageFailed} /> :
        <div className="rt-doc-preview-error" role="alert">
          <strong>Document preview unavailable</strong>
          <p>The source image could not be loaded. Refresh the case to try again.</p>
          <button ref={recoveryRef} type="button" disabled={refreshing} onClick={() => { void refresh(); }}>
            {refreshing ? "Refreshing…" : "Refresh document preview"}
          </button>
          {refreshError && <p>{refreshError}</p>}
        </div>}
    </div>
    {src && !failed && <div className="rt-doc-preview-actions">
      <button ref={triggerRef} type="button" onClick={() => { setZoomed(false); setExpanded(true); }}>
        Enlarge source page ↗
      </button>
    </div>}
    <dialog ref={dialogRef} className="rt-doc-dialog" aria-labelledby="rt-doc-dialog-title"
      onClose={() => {
        setExpanded(false);
        if (focusRecoveryOnClose.current) {
          focusRecoveryOnClose.current = false;
          requestAnimationFrame(() => recoveryRef.current?.focus());
        } else triggerRef.current?.focus();
      }}>
      <div className="rt-doc-dialog-header">
        <div><strong id="rt-doc-dialog-title">{title}</strong><span>Fictional source page · inspect the original text</span></div>
        <div className="rt-doc-dialog-actions">
          <button type="button" onClick={() => setZoomed(value => !value)}>
            {zoomed ? "Fit page" : "Zoom to 200%"}
          </button>
          <button type="button" onClick={() => dialogRef.current?.close()}>Close</button>
        </div>
      </div>
      <div className={`rt-doc-dialog-page${zoomed ? " is-zoomed" : ""}`}>
        {src && !failed && <img src={src} alt={alt} onError={imageFailed} />}
      </div>
    </dialog>
  </div>;
}

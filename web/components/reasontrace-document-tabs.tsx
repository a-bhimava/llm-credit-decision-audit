"use client";

import { useLayoutEffect, useRef, type KeyboardEvent } from "react";
import type { DocumentId } from "@/lib/reasontrace/demo";

type DocumentTab = {
  id: DocumentId;
  title: string;
  status: "missing" | "reviewed" | "to-review";
};

export const documentTabId = (id: DocumentId) => `rt-document-tab-${id}`;

export function ReasonTraceDocumentTabs({ items, selectedId, onSelect }: {
  items: readonly DocumentTab[];
  selectedId: DocumentId;
  onSelect: (id: DocumentId) => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const list = listRef.current;
    const active = document.getElementById(documentTabId(selectedId));
    if (!list || !active) return;
    const bounds = list.getBoundingClientRect();
    const tabBounds = active.getBoundingClientRect();
    if (tabBounds.left < bounds.left) list.scrollLeft += tabBounds.left - bounds.left - 4;
    else if (tabBounds.right > bounds.right) list.scrollLeft += tabBounds.right - bounds.right + 4;
  }, [selectedId]);

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % items.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + items.length) % items.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = items.length - 1;
    else return;

    event.preventDefault();
    const id = items[next].id;
    onSelect(id);
    requestAnimationFrame(() => document.getElementById(documentTabId(id))?.focus());
  }

  return <div ref={listRef} className="rt-doc-tabs" role="tablist" aria-label="Synthetic documents">
    {items.map((item, index) => <button key={item.id} type="button" role="tab"
      id={documentTabId(item.id)} aria-controls="rt-document-panel"
      aria-selected={item.id === selectedId} tabIndex={item.id === selectedId ? 0 : -1}
      className={item.id === selectedId ? "is-active" : ""}
      onClick={() => onSelect(item.id)} onKeyDown={event => onTabKeyDown(event, index)}>
      <span>{item.title}</span>
      <small className={`rt-doc-tab-status ${item.status}`}>
        {item.status === "missing" ? "Missing" : item.status === "reviewed" ? "Reviewed" : "To review"}
      </small>
    </button>)}
  </div>;
}

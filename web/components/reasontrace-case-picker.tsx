"use client";

import { useLayoutEffect, useRef, type KeyboardEvent } from "react";
import { caseDefinitions } from "@/lib/reasontrace/cases";
import { SpotlightCard } from "@/components/react-bits/spotlight-card";

type AvailableCase = { id: string; label: string };

export function ReasonTraceCasePicker({ currentLabel, availableCases, busy, onSelect }: {
  currentLabel: string;
  availableCases: readonly AvailableCase[];
  busy: boolean;
  onSelect: (id: string) => void;
}) {
  const listRef = useRef<HTMLElement>(null);
  const currentIndex = Math.max(0, caseDefinitions.findIndex(item => item.label === currentLabel));

  useLayoutEffect(() => {
    const list = listRef.current;
    const active = list?.querySelectorAll<HTMLButtonElement>("button")[currentIndex];
    if (!list || !active) return;
    const bounds = list.getBoundingClientRect();
    const cardBounds = active.getBoundingClientRect();
    if (cardBounds.left < bounds.left) list.scrollLeft += cardBounds.left - bounds.left - 4;
    else if (cardBounds.right > bounds.right) list.scrollLeft += cardBounds.right - bounds.right + 4;
  }, [currentIndex]);

  function onCaseKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % caseDefinitions.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + caseDefinitions.length) % caseDefinitions.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = caseDefinitions.length - 1;
    else return;

    event.preventDefault();
    const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>("button");
    buttons?.[next]?.focus();
  }

  return <div className="rt-case-picker-wrap">
    <div className="rt-case-picker-meta"><strong>Choose a synthetic case</strong><span>Case {currentIndex + 1} of {caseDefinitions.length}</span></div>
    <nav ref={listRef} className="rt-case-picker" aria-label="Select a synthetic interview case">
      {caseDefinitions.map((item, index) => {
        const match = availableCases.find(entry => entry.label === item.label);
        return <SpotlightCard key={item.label} className={`rt-case-tile${item.label === currentLabel ? " is-active" : ""}`}>
          <button type="button" disabled={!match || busy}
            aria-current={item.label === currentLabel ? "page" : undefined}
            onKeyDown={event => onCaseKeyDown(event, index)}
            onClick={() => { if (match) onSelect(match.id); }}>
            <span>CASE {index + 1} / {item.label}</span><strong>{item.title}</strong><small>{item.summary}</small>
          </button>
        </SpotlightCard>;
      })}
    </nav>
  </div>;
}

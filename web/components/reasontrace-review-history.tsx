"use client";

import { useState } from "react";
import { documents, displayValue, fieldDefinitions, type FieldId } from "@/lib/reasontrace/demo";

export type ReviewEvent = {
  id: string;
  observation_id: string | null;
  action: string;
  before_value: unknown;
  after_value: unknown;
  created_at: string;
  subject?: string;
  fieldId?: FieldId;
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function localSubject(after: Record<string, unknown>) {
  if (typeof after.fieldId === "string" && after.fieldId in fieldDefinitions) {
    return fieldDefinitions[after.fieldId as FieldId].label;
  }
  if (typeof after.documentId === "string") {
    return documents.find(doc => doc.id === after.documentId)?.title;
  }
  return undefined;
}

function describe(event: ReviewEvent): { title: string; detail: string | null } {
  const before = record(event.before_value);
  const after = record(event.after_value);
  const subject = event.subject || localSubject(after) || (event.observation_id ? "Source value" : "Source document");
  const fieldId = event.fieldId || (typeof after.fieldId === "string" && after.fieldId in fieldDefinitions ? after.fieldId as FieldId : undefined);

  if (event.action === "document") {
    if (after.included === false) return { title: `${subject} marked missing`, detail: null };
    if (after.included === true && before.included === false) return { title: `${subject} restored to packet`, detail: null };
    if (after.included === true && before.included === undefined && after.kind === "document") {
      return { title: `${subject} restored to packet`, detail: null };
    }
    return { title: after.reviewed === true ? `${subject} marked reviewed` : `${subject} review reopened`, detail: null };
  }
  if (event.action === "include_document") return { title: `${subject} restored to packet`, detail: null };
  if (event.action === "exclude_document") return { title: `${subject} marked missing`, detail: null };
  if (event.action === "review_document") return { title: after.reviewed === true ? `${subject} marked reviewed` : `${subject} review reopened`, detail: null };
  if (event.action === "applicant_name") return { title: "Applicant name correction saved", detail: null };

  const oldValue = before.confirmed_value;
  const newValue = after.confirmed_value ?? after.value;
  const changed = typeof oldValue === "number" && typeof newValue === "number" && oldValue !== newValue;
  const action = event.action === "field"
    ? changed ? after.confirmed === true ? "corrected and confirmed" : "corrected"
      : after.confirmed === true ? "confirmed"
        : before.confirmed === true && after.confirmed === false ? "unconfirmed" : "updated"
    : event.action === "confirm" ? "confirmed"
      : event.action === "unconfirm" ? "unconfirmed"
        : event.action === "correct" ? "corrected"
          : event.action === "reject" ? "rejected" : event.action.replaceAll("_", " ");
  const title = `${subject} ${action}`;
  if (fieldId && typeof oldValue === "number" && typeof newValue === "number" && oldValue !== newValue) {
    return { title, detail: `${displayValue(fieldId, oldValue)} → ${displayValue(fieldId, newValue)}` };
  }
  if (fieldId && typeof newValue === "number" && (event.action === "correct" || event.action === "field")) {
    return { title, detail: `Reviewed value: ${displayValue(fieldId, newValue)}` };
  }
  if (typeof before.status === "string" && typeof after.status === "string" && before.status !== after.status) {
    return { title, detail: `${before.status} → ${after.status}` };
  }
  return { title, detail: null };
}

export function ReasonTraceReviewHistory({ events }: { events: readonly ReviewEvent[] }) {
  const [showAll, setShowAll] = useState(false);
  const recent = [...events].reverse();
  const visible = showAll ? recent : recent.slice(0, 5);

  return <details className="rt-review-history">
    <summary>Review history <span>{events.length} {events.length === 1 ? "change" : "changes"}</span></summary>
    {events.length === 0 ? <p>No review changes saved yet.</p> : <>
      <ol>{visible.map(event => {
        const item = describe(event);
        const date = new Date(event.created_at);
        return <li key={event.id}>
          <strong>{item.title}</strong>
          {item.detail && <span>{item.detail}</span>}
          <time dateTime={event.created_at}>{Number.isNaN(date.getTime()) ? "Time unavailable" : date.toLocaleString()}</time>
        </li>;
      })}</ol>
      {recent.length > 5 && <button type="button" onClick={() => setShowAll(value => !value)}>
        {showAll ? "Show recent five" : `Show all ${recent.length} changes`}
      </button>}
    </>}
  </details>;
}

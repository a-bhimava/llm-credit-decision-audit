"use client";

import type { CaseDefinition } from "@/lib/reasontrace/cases";

export type ScriptedAgent = CaseDefinition["agent"];

const choices: readonly { id: ScriptedAgent; title: string; detail: string }[] = [
  {
    id: "laundering", title: "Planted defect",
    detail: "A known-answer control designed to expose reason laundering.",
  },
  {
    id: "faithful", title: "Faithful control",
    detail: "A known-answer control that follows the synthetic policy.",
  },
];

export function ReasonTraceAgentChoice({ value, disabled, onChange }: {
  value: ScriptedAgent;
  disabled: boolean;
  onChange: (value: ScriptedAgent) => void;
}) {
  return <fieldset className="rt-agent-choice" disabled={disabled}>
    <legend>Scripted agent control</legend>
    <div className="rt-agent-options">
      {choices.map(choice => <label key={choice.id} className={value === choice.id ? "is-selected" : ""}>
        <input type="radio" name="rt-scripted-agent" value={choice.id}
          checked={value === choice.id} onChange={() => onChange(choice.id)} />
        <span><strong>{choice.title}</strong><small>{choice.detail}</small></span>
      </label>)}
    </div>
    <p>Switching controls hides the current result. Run the selected control to compare outcomes.</p>
  </fieldset>;
}

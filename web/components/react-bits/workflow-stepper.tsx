"use client";

// Adapted from React Bits Stepper (MIT + Commons Clause):
// https://github.com/DavidHDev/react-bits/tree/main/src/ts-default/Components/Stepper
// The original moves between hidden form steps. ReasonTrace keeps its three
// evidence panels visible and derives each step from the reviewed case state.
import "./workflow-stepper.css";

type WorkflowStepperProps = {
  reviewedDocuments: number;
  confirmedFields: number;
  ready: boolean;
  audited: boolean;
};

const stages = [
  { label: "Source documents", target: "rt-doc-heading" },
  { label: "Confirm facts", target: "rt-fact-heading" },
  { label: "Test stated reasons", target: "rt-audit-heading" },
] as const;

export function WorkflowStepper({ reviewedDocuments, confirmedFields, ready, audited }: WorkflowStepperProps) {
  const currentStep = reviewedDocuments < 3 ? 1 : ready ? 3 : 2;
  const details = [
    `${reviewedDocuments} of 3 reviewed`,
    `${confirmedFields} of 3 confirmed`,
    audited ? "Audit complete" : ready ? "Ready to test" : "Awaiting review",
  ];
  const complete = [reviewedDocuments === 3, ready, audited];

  function moveTo(target: string) {
    const heading = document.getElementById(target);
    if (!heading) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    heading.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
    heading.focus({ preventScroll: true });
  }

  return <nav className="rt-workflow-stepper" aria-label="Case workflow">
    {stages.map((stage, index) => <div className="rt-step-group" key={stage.target}>
      {index > 0 && <span className={`rt-step-connector${complete[index - 1] ? " is-complete" : ""}`} aria-hidden="true"><span /></span>}
      <button type="button" className={`rt-step${complete[index] ? " is-complete" : index + 1 === currentStep ? " is-current" : ""}`}
        aria-current={index + 1 === currentStep ? "step" : undefined}
        aria-label={`${stage.label}, ${details[index]}`}
        onClick={() => moveTo(stage.target)}>
        <span className="rt-step-indicator" aria-hidden="true">{complete[index] ? "✓" : index + 1}</span>
        <span className="rt-step-copy"><strong>{stage.label}</strong><small>{details[index]}</small></span>
      </button>
    </div>)}
  </nav>;
}

"use client";

// Adapted from the ReasonTrace React Bits Stepper treatment. Intake stages are
// informational: the Back and Continue controls own navigation and validation.
import "./audit-intake-stepper.css";

const labels = [
  "Income & request",
  "Credit profile",
  "Record & inquiries",
  "Employment",
  "Confirm scope",
] as const;

export function AuditIntakeStepper({ currentStep }: { currentStep: number }) {
  return <nav className="audit-intake-stepper" aria-label="Intake progress">
    <p className="audit-intake-count">Step {currentStep + 1} of {labels.length}</p>
    <div className="audit-intake-track" aria-hidden="true"><span style={{ width: `${((currentStep + 1) / labels.length) * 100}%` }} /></div>
    <ol>
      {labels.map((label, index) => <li key={label}
        className={index === currentStep ? "active" : index < currentStep ? "complete" : ""}
        aria-current={index === currentStep ? "step" : undefined}>
        <span aria-hidden="true">{index < currentStep ? "✓" : String(index + 1).padStart(2, "0")}</span>{label}
      </li>)}
    </ol>
  </nav>;
}

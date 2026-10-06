import { WorkflowStepper } from "@/components/react-bits/workflow-stepper";

export function ReasonTraceIntro({ caseLabel, localFixtures, reviewedDocuments, confirmedFields,
  ready, audited }: {
  caseLabel: string;
  localFixtures: boolean;
  reviewedDocuments: number;
  confirmedFields: number;
  ready: boolean;
  audited: boolean;
}) {
  return <section className="rt-hero rt-hero-loaded" aria-labelledby="rt-page-title">
    <div className="rt-hero-copy">
      <div className="rt-kicker"><span className="rt-live-dot" /> ReasonTrace / synthetic case {caseLabel}</div>
      <h1 id="rt-page-title">Can we trust the reason behind this credit decision?</h1>
    </div>
    <div className="rt-hero-context">
      <p>Trace three reviewed values from fictional documents into a real paired reason-validity test. The audit engine uses the repository’s unchanged <strong>Meridian Personal Loan</strong> policy.</p>
      {localFixtures && <p className="rt-local-notice">Local saved-fixture mode · no Supabase sign-in or Interfaze request</p>}
    </div>
    <WorkflowStepper reviewedDocuments={reviewedDocuments} confirmedFields={confirmedFields}
      ready={ready} audited={audited} />
  </section>;
}

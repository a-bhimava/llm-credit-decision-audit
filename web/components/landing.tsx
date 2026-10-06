import Link from "next/link";
import { AuditFlowDiagram } from "@/components/audit-flow-diagram";
import { ProductShell } from "@/components/product-shell";
import { SpotlightCard } from "@/components/react-bits/spotlight-card";

export function Landing() {
  return (
    <ProductShell>
      <main className="productMain landing">
        <section className="landingHero">
          <div className="heroCopy">
            <h1>When an AI gives a credit decision, we make its explanation auditable and testable.</h1>
            <p className="landingLead">
              Credit Decision Audit turns a model’s explanation into a testable claim. It holds fictional financial facts fixed, changes one controlled condition at a time, and preserves the decision traces needed to inspect the result.
            </p>
            <div className="landingActions">
              <Link className="primaryAction" href="/audit">Open Audit Studio <span aria-hidden="true">↗</span></Link>
              <Link className="textAction" href="/evidence">Read the evidence ledger</Link>
            </div>
          </div>
          
          <div className="heroSystem">
            <AuditFlowDiagram />
          </div>
        </section>

        <SpotlightCard className="reasontraceCallout" spotlightColor="rgba(142, 169, 255, 0.2)">
          <section aria-labelledby="reasontrace-callout-heading">
            <div>
              <p className="reasontraceCalloutEyebrow">Interview demo / five synthetic cases</p>
              <h2 id="reasontrace-callout-heading">Follow a document fact to a tested decision reason.</h2>
              <p>Review fictional source pages, confirm the facts, then inspect paired reason-validity checks in ReasonTrace.</p>
            </div>
            <Link className="reasontraceCalloutLink" href="/reasontrace">Open ReasonTrace <span aria-hidden="true">↗</span></Link>
          </section>
        </SpotlightCard>

        <section className="problemBand">
          <p className="productEyebrow"><span /> The problem</p>
          <div>
            <h2>An explanation is not evidence just because it sounds plausible.</h2>
            <p>Language models can produce a decision, a list of reasons, and a polished rationale in one breath. None of that establishes that those reasons actually caused the decision—or that irrelevant presentation details did not.</p>
          </div>
        </section>

        <section className="methodGrid" aria-label="How the audit works">
          <article>
            <span className="stepNumber">01</span>
            <h3>Construct a controlled case</h3>
            <p>Use a facts-only fictional applicant. Names, contact details, account identifiers, uploads, and free text are deliberately excluded.</p>
          </article>
          <article>
            <span className="stepNumber">02</span>
            <h3>Run paired interventions</h3>
            <p>Test policy adherence, monotonicity, invariance, serialization, demographic presentation, and reason validity with five trials per configuration.</p>
          </article>
          <article>
            <span className="stepNumber">03</span>
            <h3>Inspect the causal record</h3>
            <p>Review traces, tool use, exact inputs, paired outcomes, and the limits of what one synthetic scenario can support.</p>
          </article>
        </section>

        <section className="comparisonSection">
          <div>
            <p className="productEyebrow"><span /> Configuration comparison</p>
            <h2>Same scenario. Two ways of asking the model to decide.</h2>
          </div>
          <div className="comparisonCards">
            <article>
              <span>01 / baseline</span>
              <h3>Structured submission</h3>
              <p>Policy and application together; one schema-constrained decision with no audit tools.</p>
            </article>
            <article className="platformCard">
              <span>02 / platform</span>
              <h3>Tool-guided decision</h3>
              <p>Same policy and facts, plus observable tools and required-tool checks. It is a configuration comparison—not a general claim about a model.</p>
            </article>
          </div>
        </section>
      </main>
    </ProductShell>
  );
}

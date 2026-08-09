# Related Work — `llm-credit-decision-audit`

> Research date **2026-08-09**. This document's job is to make the novelty claim
> **defensible** — every claim names the nearest prior work and states precisely what that
> work does not do.
>
> **Rule for this document:** prefer *"we combine X, Y, Z; prior work does each separately"*
> over *"first ever."* Understating the delta reads as more credible than overstating it, and
> the exhaustive-search claim cannot be supported.

---

## 1. What is commodity in 2026

Anything in this table is table stakes. Building it is not a contribution.

| Capability | Ships in | Commodity? |
|---|---|---|
| Hallucination / groundedness / faithfulness | RAGAS `faithfulness`, DeepEval `Hallucination`/`Faithfulness`, TruLens RAG Triad, Arize Phoenix, Patronus **Lynx**, Bedrock Evaluations, Giskard, MLflow | **Yes** |
| Semantic similarity via embedding cosine | RAGAS `SemanticSimilarity` + `AnswerCorrectness`, promptfoo `similar` | **Yes — and unsound, §5** |
| Custom policy/rubric judge | DeepEval **G-Eval** + **DAG**, promptfoo `llm-rubric` + Policy plugin, Braintrust autoevals, Inspect Scorers, LangSmith evaluators | **Yes** |
| Counterfactual demographic swap | **LangFair** `CounterfactualMetrics` + `AdversarialGenerator` | **Yes**, as a dedicated OSS library |
| Basic red-teaming / jailbreak scanning | garak, PyRIT, promptfoo red team | **Yes** |
| Finance red-teaming | promptfoo's 12 `financial:*` plugins | **Yes for markets/advisory — no for lending** |
| Agent tracing / observability | Langfuse, Phoenix, LangSmith | **Yes** |
| **CIs + power analysis on eval results** | Effectively nobody | **No — gap** |
| **Paired hypothesis testing on decision flips** | Research papers only, not shipped tools | **No — gap** |
| **Adverse-action reason-code validity** | **Nothing, open or closed** | **No — gap** |
| **Monotonicity/metamorphic testing of LLM decisions** | Classical ML only | **No — gap** |

> **A nuance worth leading with:** DeepEval's `BiasMetric` is *referenceless* — it extracts
> opinions from a single output and classifies each as biased, scoring
> `biased_opinions / total_opinions`. It does **not** compare two counterfactual runs, and it
> cannot detect the thing that actually matters in lending: *the same applicant getting a
> different decision under a different name.*
> — https://deepeval.com/docs/metrics-bias

---

## 2. Nearest prior work — cite these by name

Ordered by how close they sit to this project.

### 2.1 LangFair — CVS Health
https://github.com/cvs-health/langfair · [arXiv:2501.03112](https://arxiv.org/abs/2501.03112) · [methodology arXiv:2407.10853](https://arxiv.org/abs/2407.10853)

Use-case-level LLM bias/fairness assessment, bring-your-own-prompts, with off-the-shelf
gender/race/age counterfactual templates plus toxicity and stereotype metrics. Built by a
Fortune-5 regulated enterprise, so it is credible and it is maintained.

**Does not:** structured *decision* semantics (approve/deny/limit/APR) · statistical
significance testing on flip rates · finance or lending domain · policy adherence · anything
about adverse-action reasons.

**Closest overlap of anything found.** The counterfactual-bias arm of this project should be
framed as *complementary* to LangFair, not competitive with it — and the README should say so.

### 2.2 MortarBench — mortgage loan origination agents
[arXiv:2606.19416](https://arxiv.org/abs/2606.19416) (Jun 2026)

Benchmark for AI agents doing mortgage application review → underwriting → approval → funding,
with a synthesis-and-mutation pipeline for loan data. Frontier LLMs reach only **77.1%
exact-match accuracy**; explicitly finds *"systematic biases in LLM perception of foreignness
related to non-English names."* Proposes CRIT calibration → 80.5%.

**Does not:** it is a *benchmark* (fixed dataset, single exact-match metric), not a harness you
point at your own pipeline. No reason validity, no policy-adherence grading, no paired
statistics.

⚠️ Public code availability **could not be verified** from the arXiv abstract page. Check before
claiming anything about its implementation.

### 2.3 AgentFairBench — "Do LLM Agents Discriminate When They Act?"
[arXiv:2606.16723](https://arxiv.org/pdf/2606.16723) (2026, CC-BY-4.0)

Agentic — not static-output — fairness, with lending among its domains. Notably uses **BCa
bootstrap CIs + Benjamini-Hochberg correction + significance testing**.

**Does not:** correctness, policy compliance, adverse-action validity, monotonicity, or judge
meta-evaluation. Fairness only.

**This is the strongest statistical reference point and a competitor on rigor.** Match its
methods and exceed its scope; do not claim to have invented paired-counterfactual statistics.

### 2.4 Bowen, Price, Stein & Yang — LLM mortgage underwriting
[SSRN 4812158](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4812158) · https://lukestein.com/bowen-price-stein-yang-llmmortgage

The reference audit study in this exact domain: real loan application data with experimentally
manipulated race and credit scores. Finds LLMs recommend more denials and higher rates for Black
applicants, largest at low credit scores and riskier loans, persisting across model generations
from three leading firms — **and that instructing the LLM to be unbiased eliminates the approval
gap.**

**Does not:** ship reusable tooling. It is a paper.

That last finding deserves prominence rather than burial: a disparity that a prompt instruction
can eliminate is a materially different problem from one that cannot, and any tool reporting
such disparities should say which kind it found.

### 2.5 τ²-bench — Sierra Research
https://github.com/sierra-research/tau2-bench (MIT)

Dual-control agent benchmark whose central idea is **policy adherence: an agent that completes
the task but violates a stated policy fails.** Domains include `banking_knowledge`.

**Does not:** document statistical significance testing or CIs. Not credit decisioning.

**This is the transferable design pattern** — "approved the loan but violated the underwriting
policy = fail" is τ²-bench's framing applied to lending. Credit it explicitly; the
`policy_adherence` check is an application of their idea, not an invention.

### 2.6 Metamorphic and monotonicity testing
- **"Higher income, larger loan? Monotonicity testing of machine learning models"**, ISSTA 2020
  — [10.1145/3395363.3397352](https://dl.acm.org/doi/10.1145/3395363.3397352)
- **CheckList** (Ribeiro et al., ACL 2020) — [arXiv:2005.04118](https://arxiv.org/abs/2005.04118)
  — the capability × test-type matrix (MFT / **INV** / **DIR**), still the canonical citation
- **Metamorphic testing + LLM survey (2026)** — [arXiv:2605.13898](https://arxiv.org/html/2605.13898v1)
- **Metamorphic testing for fairness in LLMs** — [arXiv:2504.07982](https://arxiv.org/abs/2504.07982)

The ISSTA 2020 work is the direct ancestor of the monotonicity check. **It is classical ML;
there is no LLM equivalent.** Frame the contribution as *applying an established software-testing
method to LLM decision systems*, which is honest and still novel.

### 2.7 Judge reliability — why we minimize judge use
- **"Reliability without Validity"** (2026) — [arXiv:2606.19544](https://arxiv.org/html/2606.19544v1)
  — 21 judges, 9 providers, ~541,000 judgments. **Exact-match agreement overstates chance-corrected
  discrimination by 33–41 percentage points**; judge rankings shift by up to 14 positions across
  benchmarks; position bias >0.10 in two production judges despite test-retest reliability >0.95
  (the "consistency–bias paradox").
- **"Replacing Judges with Juries"** (Cohere) — [arXiv:2404.18796](https://arxiv.org/abs/2404.18796)
  — a panel of smaller diverse models beats a single large judge, cheaper, less intra-model bias.
- **"How to Correctly Report LLM-as-a-Judge Evaluations"** — [arXiv:2511.21140](https://arxiv.org/abs/2511.21140)
  — bias-corrects for judge sensitivity/specificity, builds CIs reflecting uncertainty from both
  test and calibration sets.
- **Temperature control and reproducibility** — [arXiv:2606.26185](https://arxiv.org/abs/2606.26185)
  — items remain non-reproducible even under forced greedy decoding.

**This literature is why the design is judge-free wherever possible.** Cite it as the
*justification for the architecture*, not as background.

### 2.8 Statistical rigor in evals
- **Miller (Anthropic), "Adding Error Bars to Evals"** — [arXiv:2411.00640](https://arxiv.org/abs/2411.00640)
  — the eval literature "has largely ignored the literature from other sciences on experiment
  analysis and planning." Clustered SEs, paired analysis, variance reduction, power analysis.
- **"Don't Use the CLT in LLM Evals With Fewer Than a Few Hundred [samples]"** —
  [arXiv:2503.01747](https://arxiv.org/pdf/2503.01747)
- **Resolution diagnostics for paired LLM evaluation** — [arXiv:2605.30315](https://arxiv.org/html/2605.30315)
  — paired analysis needs 30–60% fewer items for the same power; **discordance, not accuracy, is
  the binding quantity.**

### 2.9 The counterfactual-fairness methodology trap
**Barocas, Hardt & Narayanan, "Testing Discrimination in Practice"** —
https://fairmlbook.org/testing.html

The sharpest statement of the problem, and citing it correctly is a credibility marker:
*"Attribute flipping does not generally produce counterfactuals that we care about."* Two named
failure modes — **ontological instability** (holding attributes fixed while varying race treats
race as a stable upstream causal node, but those features partly *constitute* the category) and
**mechanism ambiguity** (a name-swap disparity could be race inference, a preference for common
names, or an SES proxy — very different moral implications). Their conclusion: audit studies are
best framed as **attempts to test blindness**, not as generalizable causal estimates.

**Design consequence, and it belongs in `docs/limitations.md`:** frame the fairness arms as
**blindness/invariance tests under a stated causal assumption**, never as "measuring
discrimination."

Related: Kusner et al., Counterfactual Fairness — [arXiv:1703.06856](https://arxiv.org/abs/1703.06856)
· Counterfactual fairness in mortgage lending via matching and randomization —
[arXiv:2112.02170](https://arxiv.org/abs/2112.02170).

### 2.10 What actually biases finance decisions
**ICE-Guard, "When Names Change Verdicts"** — [arXiv:2603.18530](https://arxiv.org/abs/2603.18530)
— 3,000 vignettes, 10 domains, 11 LLMs, 8 families. **Authority bias averages 5.8% and framing
bias 5.0%, both substantially exceeding demographic bias at 2.2% — and in finance specifically,
authority bias reaches 22.6%.** Real COMPAS data showed higher bias than synthetic benchmarks.

This paper is the direct justification for building the **authority** and **framing** arms, and
for not treating the demographic arm as the headline.

Related: serialization sensitivity — **"Accept or Deny?"**
[arXiv:2508.21512](https://arxiv.org/abs/2508.21512) — across loan datasets from Ghana, Germany
and the US, the table-to-text serialization format changes both accuracy *and* fairness, with
some formats improving F1 while *worsening* disparities.

### 2.11 Governance tooling
| Project | Status | Maps evals → regulation? |
|---|---|---|
| **COMPL-AI** (ETH Zurich SRI + LatticeFlow + INSAIT) — https://github.com/compl-ai/COMPL-AI, [arXiv:2410.07959](https://arxiv.org/abs/2410.07959) | OSS, 202★, active | **Yes — the only serious one.** But GPAI/model-level only, EU AI Act only, no US regs, no lending, no auditor-facing artifact |
| NIST **Dioptra** — https://github.com/usnistgov/dioptra | OSS, active | No — adversarial ML testbed |
| **AI Verify** (Singapore IMDA) | OSS, active | Partially |
| **Credo AI Lens** — https://github.com/credo-ai/credoai_lens | **ARCHIVED July 2024** | Dead |
| AIF360 / Fairlearn / Aequitas | OSS, active | No — tabular classifiers only; per the LangFair paper, *"not tailored to the generative and context-dependent nature of LLMs"* |
| Credo AI · Holistic AI · Monitaur · IBM watsonx.governance · ModelOp · ValidMind · Fiddler | **Commercial**, reportedly $100K–$500K/yr | Policy/doc-centric; eval integration thin |
| **Zest AI** (FairBoost) · **FairPlay AI** · **Solas AI** | **Commercial** | Fair-lending disparity + LDA search + reason-code *generation* — for **classical scorecards, not LLMs** |

### 2.12 Finance benchmarks
**FinBen** ([arXiv:2402.12659](https://arxiv.org/abs/2402.12659), NeurIPS 2024 D&B) — 42
datasets, 36 tasks. **No fairness, bias, or safety dimension whatsoever**; its "risk management"
tasks are classical credit-scoring datasets framed as classification. This hole is a clean piece
of white-space evidence.

**FinTrust** ([arXiv:2510.15232](https://arxiv.org/abs/2510.15232), code
https://github.com/HughieHu/FinTrust) — finance trustworthiness including personal-level fairness
in credit scoring. Static QA, not agentic; no paired statistics; no policy adherence.

**FinanceBench** (Patronus AI) — 10k QA pairs on SEC filings. Capability, not governance.

**FinTrace** ([arXiv:2604.10015](https://arxiv.org/pdf/2604.10015)) — trajectory-level tool-calling
eval for long-horizon financial tasks. Closest existing "trajectory eval in finance"; not credit
decisioning, not fairness.

**Name collision:** `SUFE-AIFLM-Lab/FinEval` (283★) + NAACL 2025 + a live ACL SIG-FinTech shared
task. The project was renamed away from an earlier working title for this reason.

### 2.13 Adverse-action reasons — the empty quadrant
Searched hard across academic, commercial, and open-source sources. **Nothing evaluates
LLM-generated adverse-action reasons.**

- Zest AI and FairPlay AI *generate* reason codes via SHAP-style attribution on **tabular
  scorecards**, not LLM outputs. Commercial.
- GitHub searches for `adverse action reason codes ECOA`, `reason codes credit denial SHAP`
  returned only 0-star personal/demo repos.
- The failure mode is named in the literature — **"reason-code laundering"**: back-fitting a
  plausible reason when the model gives no genuine per-feature attribution.
- **"Fair outputs, Biased Internals"** — [arXiv:2605.15217](https://arxiv.org/abs/2605.15217)
  (May 2026) — Gemma-3-12B-IT on mortgage underwriting with matched applications differing only
  in racially-associated names. **Output parity can coexist with biased internal
  representations**, directly undermining output-only audit frameworks. Worth reading and
  citing in limitations.

⚠️ Two independent research passes reached this conclusion, but **neither did an exhaustive
GitHub search.** Run direct `github.com/search` passes for `credit`+`eval`+`fairness`+`agent`
and for `adverse action` before publishing any novelty language, and phrase the claim as *"we
found no tool that…"* rather than *"no tool exists."*

---

## 3. The novelty delta, stated precisely

**What is not new:** LLM-as-judge · counterfactual name swapping (LangFair) · policy-adherence
grading (τ²-bench) · metamorphic/monotonicity testing (ISSTA 2020, CheckList) · paired bootstrap
+ FDR in fairness auditing (AgentFairBench) · LLM mortgage bias as a finding
(Bowen/Price/Stein/Yang, MortarBench) · agent trajectory logging.

**What we claim is new — four things:**

1. **The causal repair-and-rerun test for statutory reason validity.** Repair the cited factor,
   re-run, check whether the decision flips. No tool found does this, open or closed.
2. **The leave-one-out necessity formulation.** The naive single-repair test produces false
   violations on multi-constraint applicants — the common case, and where laundering lives. LOO
   necessity plus joint sufficiency plus an oracle-driven omission scan is the correct
   formulation and, as far as we found, has not been stated.
3. **Two zero-cost statutory violation detectors** derived directly from §1002.9:
   `NON_SPECIFIC_INTERNAL_POLICY` and `OUT_OF_SCHEMA_FACTOR` — falsifiable without a single API
   call.
4. **Scripted-agent ground-truth validation of an audit checker.** Planting agents whose true
   decision driver is known (`LaunderingAgent` decides on score, always says income) and showing
   the harness recovers it. This is what makes it a *harness* rather than another benchmark, and
   no comparable project publishes a planted-defect table.

**And the combination itself:** nothing found combines agentic credit adjudication with tool use
+ τ²-style policy-adherence grading + paired-counterfactual fairness with proper statistics +
statute-derived judge-free checks + a reproducible cassette. Prior work does each separately.

---

## 4. Where we deliberately follow rather than innovate

Saying this out loud costs nothing and buys credibility:

- Statistics follow **AgentFairBench** and **Miller (arXiv:2411.00640)**
- Policy-adherence grading follows **τ²-bench**
- The metamorphic frame follows **CheckList** and **ISSTA 2020**
- Judge design (if v0.2 ships it) follows **Cohere's PoLL** and **arXiv:2511.21140**
- The fairness-test caveat follows **Barocas, Hardt & Narayanan**
- Bias arm selection follows **ICE-Guard**

---

## 5. Design decisions taken *against* prior art

Two things every comparable project does that this one deliberately refuses:

**No embedding cosine as an accuracy metric.** Steck, Ekanadham & Kallus (Netflix), WWW '24 —
[arXiv:2403.05440](https://arxiv.org/abs/2403.05440) — show cosine on learned embeddings *"can
yield arbitrary and therefore meaningless similarities,"* implicitly determined by regularization
rather than semantics. Domain-fatal here: *"DENIED due to insufficient income"* and *"APPROVED
due to sufficient income"* score near-identically. **Blind to negation and decision polarity.**
Replaced with structured extraction + exact match on the decision field, and numeric-tolerance
checks on APR/limit/term. Cosine is retained only as a diagnostic, never as a score.

**No single-run bias percentages.** Measured demographic flip rates run ~2.2% (ICE-Guard).
Detecting a 2-point binomial difference at 80% power requires thousands of paired trials. Every
disparity ships with McNemar, a pair-clustered CI, and a BH-adjusted q — and the power analysis
is published *before* the run.

---

## 6. Unverified — check before publishing

1. **MortarBench public code/dataset availability** — not stated on the arXiv abstract page.
2. **Exhaustive novelty search** — not performed. Do direct GitHub repo/code searches before any
   "first" language, and prefer *"we found no tool that…"*.
3. **EU AI Act Annex III timing** — one research pass read Annex III obligations as live from
   2026-08-02; another verified deferral to **2027-12-02** via the Digital Omnibus, Reg (EU)
   2026/1744. The second had stronger primary sourcing. **Confirm against the regulation text.**
4. **"CFPB Circular 2026-03" (May 2026)** — asserted on SEO/AI-generated sites, **not on the CFPB
   circulars index. Believed fabricated. Never cite.**
5. **HUD FHA disparate-impact rescission** — proposed 2026-01-14, comments closed 2026-02-13,
   final status unknown.
6. **Reg B final-rule effective date** (reported 2026-07-21) — verify at federalregister.gov.
7. **SolasAI library license** — their blog says "free to use but not open-sourced" while the code
   is on GitHub. Read the LICENSE file before depending on it.
8. **Some 2026 arXiv IDs** were verified via abstract pages only, not full PDFs.

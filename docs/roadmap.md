# Roadmap — `llm-credit-decision-audit`

> The build plan. Twelve phases, dependency-ordered. Every phase has an **exit criterion** that
> is checked by running something — no phase is "done" because it looks done.
>
> Companion docs: [`architecture.md`](./architecture.md) · [`related-work.md`](./related-work.md)

---

## Current status — 2026-08-14

Phases 0–9 are implemented. Phase 5 was hardened before Phase 6 so that every later check
inherits matched-trial completion semantics and trustworthy evidence identities. Phase 7 added
the preregistration and the inference layer. Phase 8 makes a run a first-class artifact: a
`credit-audit` CLI, three suites, a budgeted run pipeline, a byte-deterministic export whose
every published statistic re-derives from raw evidence, and the known-answer sweep that
publishes the harness catching all 14 planted defects while firing nothing else. Phase 9 adds provider adapters and cassettes, and
crossed the live boundary once to record real responses.

**The scripted evidence is unchanged and remains the published claim.** The recorded
cassettes exist to validate the adapters, not to report on a model: six episodes is not a
finding, and the export lint would refuse to let it ship as one.

`PREREGISTRATION.yaml` is **frozen and git-tagged `prereg-v1`**. The manifest and the
integrity chain both carry the freeze time, and the chain derives `frozen_before_run` from
actual git ancestry rather than from the presence of a tag string.

Framing is deliberately deferred. Phases 10–11 below remain plans, not implemented claims.

---

## Ordering principle

**Prove the reason-validity engine against scripted agents before spending a dollar on a real
model.** Phases 0–8 make zero API calls. The site (Phase 10) ships on scripted-agent data,
which is not a compromise — a known-answer test is a *stronger* claim than any rate about a
real model.

## Two corrections carried in from the Gemini research (2026-08-09)

1. **No two-stage screening.** `gemini-2.5-flash-lite` at $0.10/$0.40 per 1M makes a
   5,000-episode run ~$18. The k=1-screen → k=5-confirm design existed only as a cost control
   and biased every rate upward without a control stratum. **Run k=5 everywhere.** Simpler,
   unbiased, no caveat.
2. **Prefix caching is not the cost lever on Gemini.** The ~4KB shared prefix is ~1,000 tokens,
   below every published implicit-cache minimum (2,048–4,096). Keep prefix stability — it's free
   and other providers reward it — but never claim it as the mechanism. Measure
   `usage.total_cached_tokens` instead of asserting a hit rate.

---

## Phase 0 — Contract and scaffold

**Goal:** the type system and a versioned pre-release export contract, before anything depends
on them.

- `pyproject.toml`, `.gitignore`, `LICENSE`, CI skeleton
- `src/credit_audit/types.py` — every core record as frozen pydantic v2. Money as `int` cents,
  ratios as `Decimal` quantized to 4dp, **never float** (repairs do exact threshold arithmetic)
- `src/credit_audit/ids.py` — canonical JSON + blake2b-128 + **hierarchical seed derivation**
- `src/credit_audit/io/jsonl.py` — the single serialization boundary
- `schemas/export/*.schema.json` — eleven versioned pre-release file types. They are updated in
  place through Phase 6 because no published run exists to migrate; Phase 8 freezes the first
  published contract.

**Non-obvious requirements**

- `FinancialFacts` stores **primitives only**; `dti`/`cltv`/`utilization` are `@property`. An
  introspection test asserts no derived quantity is a stored field. This kills the bug class
  where repairing income leaves a stale DTI and the agent notices an incoherent record.
- `Applicant.facts` vs `Applicant.presentation` split, with `InterventionSpec.layer` naming
  which one an intervention may touch. Enforced at apply time.
- `seed(run_seed, pair_plan.seed_group, trial_index)` gives corresponding arms common random
  numbers; the seed group is explicit so serialization pairs can reuse one TABLE anchor. Arm ID
  remains in `EpisodeKey`, so episode and cache identities stay arm-specific. A global RNG would
  make adding profile #226 shift profiles 1–225 and destroy cross-run comparability.
- Evidence mappings and arrays are recursively immutable and hashable; JSON is thawed only at
  provider and JSON Schema boundaries.
- `applicant_id` names the stable selected experimental unit. A separate content hash names
  each facts-and-presentation variant.
- `TestResult.pair_id` names a contrast, while required `cluster_id` names its originating
  source applicant. Sibling generator profiles therefore remain in one future resampling
  cluster.
- Python 3.11–3.14 are exercised in CI.

**Exit:** `pytest tests/unit/test_types.py` green — nested mutation fails, every evidence record
is hashable, no derived fields are stored, canonical JSON round-trips, identities are separated,
and IDs remain stable across `PYTHONHASHSEED`.

---

## Phase 1 — Policy and oracle

**Goal:** the deterministic reference underwriter. Build it first; it makes everything
downstream testable and the omission scan depends on it.

- `policy/policy.md` — the human-readable underwriting policy the agent is given
- `policy/policy.yaml` — machine mirror: thresholds, required tools, prohibited factors
- `policy/loader.py` — parse, validate, hash, **assert md↔yaml consistency**
- `policy/oracle.py` — `facts -> GroundTruthDecision` with the set of breached thresholds

**Exit:** oracle unit tests across boundary cases; `oracle.breached(facts)` returns exactly the
right code set for hand-written fixtures on both sides of every threshold.

---

## Phase 2 — Environment and scripted agents

**Goal:** an episode runs end to end with zero API calls.

- `env/state.py` — `CreditEnvState` frozen; **reset is object construction**, not process restart
- `env/tools.py` — five real tools + one trap:
  `get_application` · `fetch_credit_report` · `verify_income` ·
  `check_policy` (**exact section lookup**, not BM25, not embeddings) ·
  `submit_decision` (terminal, schema-validated) ·
  `lookup_neighborhood_stats` (**trap** — returns prohibited-basis-correlated data; calling it
  is a policy violation)
- `env/episode.py` — the loop, with `max_steps=12` and immediate provider-terminal handling;
  run-wide token and budget caps land with the Phase 8 runner
- `model/client.py` — `ModelClient` protocol
- `model/scripted.py` — the ground-truth agents
- `model/cache.py` — response cache

**Non-obvious requirements**

- `submit_decision` **allows up to 10 reasons, not 4.** "Agent emitted 6 principal reasons" is
  itself a §1002.9 finding; capping it in the schema hides the finding.
- Two reason modes through the runner's `reason_mode` parameter: `coded` (enum + detail) vs
  `freetext`. Running both on the same profiles separates *selection error* from *articulation
  error*. A CLI is intentionally deferred to Phase 8.
- `episode_id` hashes the planned `EpisodeKey`; `trajectory_id` hashes the realized semantic
  message/tool/decision history.
- Preserve provider call IDs, assistant tool-call messages, correlated tool results, turn
  indices, arguments, results, errors, cached/thought tokens, and cache/replay provenance.
- Cache keys include the complete episode context. Atomic writes use collision-safe temporary
  files. Replayed responses have zero cost in the current run.
- `stop`, `refusal`, `max_tokens`, and `error` terminate immediately rather than drifting to
  `MAX_STEPS`.
- The runner centrally derives the application reference, prompt hash, model/render identity,
  trial seed, and initial user task, and rejects inconsistent caller-supplied identity fields.

**Exit:** environment and scripted-agent tests produce correlated, content-addressed
trajectories with zero API calls. A console entry point is intentionally deferred to Phase 8.

---

## Phase 3 — Profiles and renderers

**Goal:** a seeded synthetic population, deliberately including the cases that matter.

- `profiles/generate.py`, `profiles/creditfile.py`, `profiles/fixtures/` (+ `.sha256`)
- `render/packet.py`, `render/table.py`, `render/prose.py`, `render/json_.py`

**Non-obvious requirements**

- **Synthetic only in this phase.** HMDA is a later offline step, deliberately, so the data layer
  can never block the checks layer.
- Deliberately generate **multi-constraint applicants** (2–3 breached thresholds). That is where
  laundering lives and where the naive single-repair test fails.
- Table, prose, and JSON serialize one common semantic application packet. Visible presentation
  fields include name, employer, school, referral cue, pronouns, graduation year, notes, and
  statement lines. Demographic tags, employer prestige tier, narrative-tone label, and ordering
  seed never render as control labels.

**Exit:** 225 profiles regenerate byte-identically from the seed; the fixture hash is committed;
oracle reports a healthy spread of 0/1/2/3-constraint denials.

---

## Phase 4 — Reason engine

**Goal:** map stated reasons to codes, and derive each code's mechanical repair.

- `reasons/codes.py` — Reg B Appendix C vocabulary + metadata (`repairable`, `target_field`,
  `repair_kind`, `severity`)
- `reasons/lexicon.yaml`, `reasons/map.py` — three extraction tiers, `mapping_method` **always
  recorded**, LLM remap **never silent**
- `reasons/repairs.py` + `interventions/repair.py` — `RepairSpec` per code

**Non-obvious requirements**

- Repairs **overshoot 20% past** the threshold, never sit on it — the boundary is where agent
  noise dominates.
- Repairs set **primitives only**; derived recompute. Raising income lowers DTI automatically.
- `INSUFFICIENT_INCOME` raises income; `EXCESSIVE_OBLIGATIONS_DTI` lowers debt. Both clear DTI,
  but only one moves income, so the two reasons stay experimentally distinguishable.
- `CREDIT_SCORE_TOO_LOW` is the hard one — score is a composite of the primitives being
  repaired. Treat it as a generator-calibrated primitive plus a `--coherence-check` flag.
  Defining it as a deterministic scorecard is more elegant and costs three days.
- `NON_SPECIFIC_INTERNAL_POLICY` and `OUT_OF_SCHEMA_FACTOR` fail **with zero API calls**.
- Freetext parse status records lexicon-only mapping as `HEURISTIC`, embedding/LLM mapping as
  `REMAPPED`, and any remaining unmapped clause as `UNPARSEABLE`.

**Exit:** for every repairable code, `repair(code)` makes the oracle stop citing that code, and
the repaired applicant stays inside plausibility bounds.

---

## Phase 5 — The flagship check

**Goal:** `checks/reason_validity.py`. This is the contribution; it gets the most care.

The hardening gate replaces independent-leg rates with trial-index-aligned matched scoring.
Only explicit approval is `APPROVE`; denial and a demonstrably worse counteroffer are `ADVERSE`;
referral, missing decision, refusal, and an unclassifiable counteroffer are `NO_DECISION`.
One-sided incompletion makes the pair `ERROR`. Two-sided incompletions are excluded from rates
and disclosed through `pair_completion_rate`.

Three constructions apply to a denied applicant:

| Test | Construction | Failure means |
|---|---|---|
| **Joint sufficiency** | Original applicant → all cited, reachable policy reasons repaired | The cited set does not account for the adverse decision |
| **Cited-reason necessity** (per `rᵢ`) | Only oracle breach `rᵢ` remains → all oracle breaches repaired | Cited `rᵢ` was not shown to be binding |
| **Omission** (per uncited `rᵢ`) | Reuse that same isolation pair and reverse the verdict | Binding principal `rᵢ` was omitted |

**Non-obvious requirements**

- **Do not implement the naive single-repair test.** It produces false violations whenever two
  constraints bind at once — the common case, and exactly where laundering hides.
- The all-oracle-breaches-repaired arm must establish isolation. If it remains incomplete or
  adverse, the isolation result is `INAPPLICABLE`, never a false pass.
- “Principal” is the oracle's ranked unique breached codes truncated at the synthetic policy's
  configured maximum. Fifth-and-later breaches cannot become false omissions against an agent
  that faithfully reports the allowed principal set.
- Zero/many-reason, vague, unmapped, unreachable, out-of-schema, and out-of-policy findings are
  policy-adherence results. `reason_validity.fabrication` is reserved for a cited, reachable,
  rule-backed code the applicant did not breach.
- Four is the **synthetic policy maximum**, not a statutory cap. The
  [official interpretation](https://www.consumerfinance.gov/rules-policy/regulations/1002/interp-9/)
  does not mandate a number and says that disclosure of more than four reasons is unlikely to
  be helpful.
- Full edge-case table from `architecture.md` §4.5: APPROVE base → `inapplicable`; COUNTEROFFER
  with worse terms → adverse action; referral/refusal → no decision; unilateral incompletion →
  `error`; bilateral incompletion → disclosed exclusion.

**Exit — the make-or-break tests:** the three-breach/one-cited fixture produces two omission
failures; all 225 committed profiles give `FaithfulAgent` zero reason-validity failures,
including the profiles with more than four oracle breaches; unilateral refusal is `ERROR`;
`REFER` never enters the approval denominator; and structural reason findings are not mislabeled
as fabrication.

---

## Phase 6 — Remaining checks

Every paired family uses immutable `ArmPlan`/`PairPlan` records, one intervention registry, and
one shared trial runner. Corresponding arms receive the same trial seed while their episode and
cache identities remain arm-specific. Interventions use absolute targets, validate their
declared `FACTS`, `PRESENTATION`, or `RENDER` layer, append lineage, and are idempotent.

1. **Policy adherence** emits separate results for globally required tools completed in an
   earlier model turn, code-specific required tools, any prohibited-tool attempt, prohibited
   basis/presentation aliases in structured or free text, each invalid-reason category, the
   synthetic policy's minimum/maximum reason count, and oracle decision consistency. Approval
   of a breached applicant and denial of an oracle-approved applicant both fail. A completed
   task can still fail adherence.
2. **Monotonicity** constructs clean, oracle-validated, absolute threshold-straddling facts
   pairs: income and credit-score increases are approval-nondecreasing; DTI increases through
   monthly debt and minor/major-delinquency increases are approval-nonincreasing. Impossible or
   confounded isolation is `INAPPLICABLE`. The `$30k → $40k` fixture plants an exact 100%
   violation in `NonMonotoneAgent`.
3. **Invariance** compares a deterministic permutation of the same six-transaction multiset,
   canonical versus seeded JSON field order, and a committed hand-authored paraphrase. It uses
   the normalized decision signature: outcome class, terms, risk grade, and ordered reason
   codes. Raw wording and formatting are not compared.
4. **Serialization** reuses a TABLE anchor for TABLE→PROSE and TABLE→JSON, with every renderer
   consuming the same complete semantic packet. `FormatSensitiveAgent` fails only TABLE→PROSE
   and passes TABLE→JSON.
5. **Authority and demographic proxy signals** keep financial facts fixed. The authority arm
   changes a high/low synthetic bundle together and uses oracle-approved credit-score-boundary
   profiles for an analytically exact planted penalty. Separate surname, recorded-sex, and age
   signal contrasts rotate committed Census/SSA-backed templates deterministically. Protected
   class labels remain hidden; results are described as proxy-signal blindness/invariance, not
   proof of discrimination. The middle-age race×sex grid is diagnostic only.

Framing remains deferred.

**Exit:** shortcut, trap, prohibited-reason, over-reason, wrong-decision, non-monotone,
format-sensitive, visible order/paraphrase-sensitive, authority-sensitive, and demographic-
signal controls fire only their intended checks. `FaithfulAgent` is `must_not_fire` across every
family. Every paired result carries planned/matched trials, both leg completion rates,
pair-completion rate, approval rates, effect, discordant transitions, reason-signature changes,
`pair_id`, and `cluster_id`. Full pytest, Ruff lint/format, export-schema validation, fixture
hashes, `git diff --check`, and cross-`PYTHONHASHSEED` stability are the final gate.

---

## Phase 7 — Statistics

**Goal:** every number ships with uncertainty.

- `stats/PREREGISTRATION.yaml` — families, hypotheses, α, δ, BH grouping. It lives inside the
  package, next to the code that loads it, for the same reason `policy.yaml` does: a research
  artifact the runtime must resolve from an installed wheel, not a path guess.
- `stats/families.py` — loads it and **hard-refuses to score an undeclared family**
- `stats/mcnemar.py` — exact test on paired flips; estimand is the **discordant-pair rate**
- `stats/bootstrap.py` — BCa, resampled at the **`cluster_id` source-applicant level**
- `stats/fdr.py` — Benjamini-Hochberg across pre-declared families
- `stats/power.py` — MDE, published *before* the run · `stats/passk.py` — pass^k over k=5
- `stats/estimates.py` — joins scored `TestResult` records to the declaration and emits the
  `credit-audit/estimates@1` payload, validated against the frozen export schema with zero
  Phase 8 code

**Decisions this phase made concrete**

- **An undeclared family raises; an undeclared check does not.** A family is the unit BH is
  defined over, so inventing one after the fact is the exact failure preregistration prevents.
  An undeclared check inside a declared family is scored but permanently marked
  `exploratory` and excluded from every BH group. `FRAMING` is deliberately absent from the
  document, so a framing result raises rather than acquiring a hypothesis retroactively.
- **Exact p-values, not chi-square, and two conventions reported.** `p` is the exact
  two-sided value — valid but conservative on a discrete statistic, and the value BH
  consumes. `p_mid` is reported alongside it for calibration diagnostics only, because a
  calibration plot drawn from exact p-values looks broken when it is merely conservative.
- **Two-sided everywhere.** A one-sided test chosen after seeing which way the flips went is
  the oldest trick in the book; the harness removes the option.
- **The estimand follows the declared relation.** Monotone checks report the rate of the one
  forbidden transition, not net movement — a forbidden flip is not excused by an equal number
  of permitted ones. Invariance checks report the decision-signature change rate against zero
  and declare *no* paired test, because McNemar tests asymmetry, which is not the quantity of
  interest there.
- **pass^k only where a per-trial pass is unambiguous.** Monotone and invariance relations
  give one; `FLIP_TO_APPROVE` does not, because a trial where the repaired arm stayed adverse
  is the finding itself rather than an inconsistency. Reason repair therefore reports no
  pass^k.

**Exit — met:** simulation-based calibration passes. Under the null the exact test's size is
0.0065 / 0.0300 / 0.0703 at α = 0.01 / 0.05 / 0.10 — valid at every level, conservative as a
discrete test must be — and mid-p is approximately uniform (mean 0.506, P(p ≤ 0.05) = 0.045).
BH holds FDR at q over 1,000 simulated runs while still recovering the planted effects.
Clustered BCa intervals cover the truth 94.5% of the time against a nominal 95%. A test
asserts source-applicant-clustered bootstrap gives **wider** CIs than response-level
resampling — 2.13× wider on clustered data, in 60 of 60 simulated datasets — so it fails
loudly if anyone later "simplifies" the clustering away. `pair_id` remains the contrast
identifier used for pair-level discordance; it is not the resampling cluster.

*Cut line, and it fires routinely:* BCa's bias correction is undefined whenever the bootstrap
distribution is degenerate, which is the **normal** case for a deterministic scripted control
where every cluster returns the identical value. The interval then falls back to cluster-level
percentile and sets `ci.fallback_used`, which the export contract carries to the site, so the
README and the site can never disagree about which method actually ran.

---

## Phase 8 — Run, report, export

**Goal:** a real scripted run and a byte-deterministic bundle.

- `cli.py` (`run` · `sweep` · `export` · `verify`) + `suites/{smoke,core,full}.yaml`
- `run/{plan,budget,execute,gitmeta,sweep}.py` — dry-run planner, run-wide caps, the executor
  that persists trajectories, results, applicant variants, and a manifest, and the
  known-answer sweep
- `model/expectations.py` — each control's true driver and the rates its rule implies
- `report/{manifest,markdown,export,bundle,summary,checks,pairs,integrity,catalog,verify}.py`
  — **no `html.py`**, the site is the drill-down UI
- `docs/{method,statistics,reason-codes,limitations,related-work}.md` in the repo

**Three rules the exporter enforces in code, not by discipline**

1. Every `summary.headline[]` must carry a `support.estimate_id` resolving in
   `stats/estimates.json` with `n_test_ids > 0`. **Export fails hard otherwise.** No number
   reaches the site without a pointer to the tests behind it.
2. When `kind == "scripted"`, lint headline strings against model-claim phrasings ("the model",
   "GPT", "Claude", "LLMs are…") and **fail the export**.
3. Secret scan before writing: `sk-…`, `AKIA…`, `ghp_…`, private keys, `$HOME`.

**Size budgets:** ≤15 MB/run, ≤40 MB total, ≤2 MB/file, ≤800 files. Prompt dedup into
`prompts/<hash>.json` is the biggest win (~4 MB → ~4 KB). Raw JSONL **never** enters git.

**Decisions this phase made concrete**

- **Trajectory capture lives in `checks/runner.py`**, already the single execution path for
  every check. A `ContextVar` sink records each episode and its materialized applicant there,
  so no check signature grows an output parameter and nothing can execute without being
  recorded. A duplicate `episode_id` with a differing `trajectory_id` raises — that is an
  identity bug, not a duplicate to drop.
- **`run_id` excludes the git commit.** It is content-addressed over the experiment definition
  (suite, model, seed, k, modes, and the policy/profiles/prereg hashes), so the same experiment
  lands at the same bundle path across commits instead of accumulating a directory per push.
  The commit is recorded *inside* the manifest as provenance.
- **`created_at` defaults to the commit timestamp**, not wall clock, for the same reason
  `SOURCE_DATE_EPOCH` exists. `--stamp-now` opts into real time and marks the run
  non-deterministic, which the site surfaces as a warning.
- **`portable_json` joins `canonical_json`.** The canonical form encodes floats as IEEE-754
  hex — perfect for hashing, unreadable as a number. Artifacts and the bundle use the portable
  form so `verify` can re-derive from them. Both are byte-deterministic.
- **Every row of every check is exported; only pair drill-down detail is sampled**, failures
  first, by a stated deterministic rule, with `n_detail_exported` recorded next to `n`.
- **`verify` re-derives rather than only re-hashing.** Re-exporting and diffing proves the
  exporter is deterministic; recomputing the statistics from raw JSONL proves it is correct.
  A doctored file with rebuilt hashes passes the sums check and fails re-derivation.

**Exit — met:** `credit-audit run --suite core --model scripted --seed 1729` executes 5,630
episodes into 913 results at $0.00 (the planner's 5,280–6,080 bound held). `export` produces
142 files / 6.9 MB, inside every budget. Exporting again to a second directory is
**byte-identical**, same bundle sha256, `diff -r` clean. `credit-audit verify --strict`
re-derives all 65 estimates, the summary, and all 39 check-row tables from raw JSONL and
passes. `FaithfulAgent` scores 762 FAITHFUL / 0 DEFICIENT end to end.

**The planted-defect table**

`credit-audit sweep` runs every declared scripted control over one **stratified** cohort and
`export` turns it into `planted-defects.json`. Stratified rather than sampled: several defects
are only expressible where their trigger exists — the authority penalty crosses a decision
boundary for just four of the 225 profiles, and the omission scan needs denials with several
binding breaches. A random cohort would omit them and report MISSED for a harness that was
working.

Expectations are declared in `model/expectations.py`, next to the agents whose rules they
describe, and **every rate is derived from the rule rather than read off a run**. A test
asserts each declared rate is 0.0 or 1.0: a fitted fraction like 0.333 is a property of a
cohort, not of a decision rule, and would fail. `must_not_fire` is computed as the
**complement** of what each control may fire, because a hand-written list can quietly omit the
check that would have embarrassed it.

That complement earned its keep immediately. It caught a suite misconfiguration (the sweep had
defaulted to a three-family suite, leaving most expectations unevaluated) and one genuinely
over-broad claim (`invariance.statement_order` at 1.0 over all approved applicants, when the
seeded permutation only reverses the rendered rent/deposit relation for some of them — now
stated over a stratum computed by rendering both arms, where the rate really is 1.0).

Result: **14 of 14 controls CAUGHT**, 0 missed, 0 false alarms, 0 partial, positive control at
100% over 287 scored results, from 31,665 episodes over 9 applicants. Sweep export is
byte-identical across two runs.

**Not emitted yet — 1 of the 11 file types**

- `replay.json`. Phase 9 shipped cassettes without it: the cassette layer records at the
  protocol boundary and nothing consumes a step-through document yet. The schema stays as a
  declared contract awaiting its producer, and the count above says so rather than implying
  eleven kinds of file are published.

*Resolved before Phase 10:* a bundle used to differ depending on the commit it was exported
at, because the git tag and remote were read live at export time. Both now come from the run's
own manifest, and export refuses outright when the working tree is at a different commit than
the run. Phase 11's `git diff --exit-code
web/public/runs/` gate therefore requires the bundle to be regenerated in the same PR that
changes the code — which is the intended workflow, but it is a real constraint rather than a
free one.

---

## Phase 9 — Provider adapters (no live calls)

**Goal:** talk to a real provider, without calling one yet.

- `model/providers/openai_compat.py` — **primary portable adapter**, built on the official
  `openai` SDK. Covers Gemini + OpenRouter + Together + Groq + local vLLM/Ollama for multi-turn
  tool calling.
- `model/providers/gemini.py` — thin native adapter via `google-genai` for cache telemetry and
  provider-specific controls.
- `model/cassette.py` — record / replay / replay-or-record / off, at the **protocol** layer.

### Build-versus-buy, decided deliberately

The standing constraint is that this project's dependency list is a claim about how much of it
a reader has to trust. That argues for few dependencies — but not for hand-rolling solved
problems. The split:

| Concern | Decision | Why |
|---|---|---|
| HTTP, retries, streaming, tool-schema serialization | **Buy** — official `openai` SDK | The de-facto wire standard every compat provider documents against. Hand-rolling httpx here is pure reinvention. |
| Gemini-native calls and cache telemetry | **Buy** — official `google-genai` | Already an optional extra. `google-generativeai` is deprecated. |
| Multi-provider normalization (LiteLLM et al.) | **Skip** | See below. |
| HTTP-level record/replay in adapter tests | **Buy** — `vcrpy` / `pytest-recording` | Mature, filters credentials, `record_mode=none` in CI. The right tool for asserting our wire format against a real provider's bytes. |
| Protocol-level cassettes for runs | **Build** | See below. |

**Why not LiteLLM.** It is the most-used multi-provider abstraction and it genuinely solves
tool-call schema differences across providers. Two reasons it is the wrong fit here. First,
normalization is exactly the risk: Gemini carries `extra_content.google.thought_signature` on
tool calls *through* the OpenAI-compatible endpoint, and an abstraction that smooths provider
differences is an abstraction that can drop the one field whose absence is a hard 400. Second,
this project's central claim is byte-deterministic evidence; inserting a layer that reshapes
responses puts that claim at the mercy of someone else's minor version. The OpenAI-compatible
endpoint is best understood as an escape hatch, not an abstraction — and that is how it is used
here.

**Why cassettes are still ours.** VCR.py records *HTTP*. This harness needs to record at the
`ModelRequest -> ModelResponse` boundary, because replay must be provider-independent, must key
on the same content-addressed episode identity the rest of the pipeline uses, and must produce
the `credit-audit/replay@1` record the bundle already declares — keyed on `episode_id`,
`trajectory_id`, and `pair_id`, none of which exist at the HTTP layer. `model/cache.py` already
does response-keyed storage; the cassette is that mechanism with record modes and provenance.
Using VCR for this would mean re-deriving episode identity from HTTP bodies, which is strictly
worse. Both tools are used, at the layer each is right for.

### What the 2026 landscape changed

- **Thought signatures are now a hard error, not silent breakage.** Gemini 3 returns a signature
  on *every* response containing a function call, and omitting it on the next turn returns 400.
  Sequential calls each carry one and all must be returned. This is an improvement: the failure
  is loud. The roadmap's original warning stands, with the consequence upgraded.
- **The SDK only auto-handles signatures if you append its response objects verbatim.** This
  harness rebuilds history from its own typed `Message`/`ToolCall` records — deliberately, since
  those records are the evidence. That places it squarely in the "manually managing parts"
  category the docs warn about, so signature passthrough must be explicit and tested.
- **Signatures cross the OpenAI-compat boundary too**, as `extra_content.google.thought_signature`
  on tool calls. The portable adapter must round-trip an opaque provider blob rather than assume
  a clean OpenAI shape.
- **`generate_content` is legacy**; the Interactions API is the current surface.
- Compat endpoints **reject or silently drop** unsupported parameters (`store`,
  `stream_options`, `logprobs`, `n > 1`). Never assume a parameter took effect — assert against
  returned usage.

### Non-obvious requirements

- **Do not claim determinism from `temperature=0`.** No provider guarantees it. The honest claim
  is deterministic *given fixed model responses* (cassette replay, CI-asserted); model
  stochasticity is **measured, not suppressed** — which is what `StochasticAgent` and pass^k
  already exist for.
- A real adapter **must never read `ModelRequest.env_state`**. It sees rendered text and tool
  results only, exactly as a real model would. A grep-style static check asserts nothing under
  `model/providers/` references it, mirroring the numeric-lint defence in `policy/loader.py`.
- Cassette records carry the **provider and model id they were recorded against**, so a replay
  cannot silently stand in for a different model.
- Credentials never enter a cassette. The exporter's secret scan already refuses them; the
  cassette writer refuses earlier.

**Exit — met, with one line of this plan deliberately reversed.**

"No live API calls in this phase" was wrong, and changing it was the right call. Cassettes
authored from documented response shapes test our *parsing*, not our fidelity to the wire —
an adapter validated only against fixtures we wrote is validated against our own
understanding, which is the thing most likely to be wrong. Recording cost **$0.0139** and
immediately earned it.

What the recordings settled:

- **`gemini-2.5-flash-lite` with thinking off emits no thought signatures at all**, across
  every episode recorded. The passthrough is insurance for thinking models and other
  providers, not something we needed here. Saying so is more useful than implying we solved
  a problem we never hit.
- **Episode completion was 53%, and both causes were ours.** An early six-episode sample
  suggested 2 of 6; re-measured over the full 62-episode recording the baseline was 33/62.
  Investigation found two harness defects rather than anything about the model, both now
  fixed:

  1. **`check_policy` rejected the form the document displays.** It accepted an anchor
     (`4.1`) or a bare title (`capacity`), but the agent asked for `"4.1 Capacity"` — the
     heading exactly as written in the policy it had just been shown. That failed **171 of
     211 calls**, and the error named what failed without naming what would work, so agents
     guessed until their step budget was gone. Five concluded the tool was broken; one
     reported "authentication issues" for a key-format mismatch. The key set is now derived
     from `policy.doc.sections` and failures return the available headings.
  2. **A null turn was treated as a considered stop.** No content, no tool call, and the
     episode finalized with no decision, discarding the applicant. Silence is not a decision;
     a null turn now consumes a step and continues, bounded by `max_steps`.

  Measured across three recordings of the same suite: **33/62 (53%) → 37/62 (60%) → 57/62
  (92%)**, with `check_policy` failures falling from 171/211 to 14/230.

Three flaws surfaced that hand-built fixtures never would have, each now fixed and tested:

1. **A replay miss was swallowed as a provider failure.** The first cassette-backed run
   finished green having replayed nothing — 62 of 62 episodes recorded as `ERROR`. Provider
   failures are evidence; a misconfigured harness is not. `HarnessConfigurationError`
   propagates out of the episode loop, with `CassetteMiss` as its first member.
2. **Pure replay demanded a credential it could never use**, blocking the CI case cassettes
   exist for. The inner client in replay mode now raises if reached at all, making "no
   network, no credential" structural.
3. **Replayed tokens consumed a cap meant to stop spending.** The budget enforces on billable
   usage only, while still reporting full totals.

The verified chain: `credit-audit run --model gemini:gemini-2.5-flash-lite --cassette …
--cassette-mode replay` with no credential and a zero-dollar cap → `export` → `export` again →
**byte-identical** → `verify --strict` re-derives 23 estimates, the summary, and 20 check-row
tables. PASS.

---

## Phase 10 — The site

`web/` — Next.js 15 App Router SSG (**not `output: 'export'`**; instead `assert-static.mjs` as
`postbuild` fails the build if any route is dynamic, any middleware exists, or function count >
0 — a stronger and more checkable claim).

Build order — **pair viewer first**, while there's energy for it:

1. Scaffold, OKLCH tokens, `StatusChip`, `CIRail`
2. `/r/[runId]/pairs/[pairId]` — the killer screen
3. `/r/[runId]/defects` + expected-vs-observed dot plot
4. `/` — headline tiles, manifest strip, planted-defect table, inlined exemplar pair, repro block
5. `/r/[runId]/checks` + `/checks/[check]` + forest plot + McNemar panel
6. `/r/[runId]/integrity`, `/r/[runId]/methods`

**Exit — met.** `pnpm build` pre-renders the committed evidence routes and `assert-static.mjs`
rejects middleware, route handlers, server actions, and dynamic fallbacks. Every displayed
result is loaded from the committed bundle; compact check rows are decoded clientlessly from
their declared column/dictionary encoding.

**Non-obvious requirements**

- **`CIRail` takes `n` as a required prop.** A CI cannot render without a sample size beside it.
  `n < 30` or CI width > 0.40 auto-appends a `low precision` chip.
- Status uses **three redundant encodings** — glyph + label + border — never color alone, and
  gets its own leading table column so it's readable by position.
- **The diff color language must not overlap pass/fail.** Never red/green diffs on a page that
  also shows FAIL/PASS chips.
- In the pair viewer, the **held-out row** gets its own glyph `⊘`, a dashed border, and the
  literal words "deliberately not repaired." A reader who misses it misunderstands the test.
- The **forest plot sorts by declared prereg order, never by effect size** — sorting by effect
  is a subtle form of cherry-picking that a statistically literate reader will notice.
- `kind: "scripted"` drives the exact visible text `Synthetic` in the overview Results panel.
  Per launch decision, it does not add a second provenance tag, banner, or metadata wording.
- Ship **three charts only**. A chart earns its place if it shows uncertainty or a mechanism.
  Cut pass-rate bars (redundant with the forest plot) and any calibration diagram (category
  error — we produce no probabilistic forecasts).

The site has no external font or image dependency, and the status/diff/held-out encodings stay
legible without color alone.

---

## Phase 11 — CI and deploy config

- `web/vercel.json` — CSP, `Access-Control-Allow-Origin: *` on `/runs/**` so a skeptic can pull
  the bundle into a notebook and recompute the CIs
- `.github/workflows/export.yml` — fresh scripted run → re-export →
  **`git diff --exit-code web/public/runs/`** → `verify --strict` → schema validation → size
  budget → `assert-static`. **This single job permanently kills the stale-data risk.**

**Exit:** full CI green; a verified local build and a committed `vercel.json`.

---

## Cut order, if time runs short

Framing is already deferred after Phase 6. For future phases, cut from the bottom:
`/checks` routes → replay viewer → Gemini native adapter (OpenAI compatibility covers it).

**Never cut:** the oracle · the scripted agents · isolated cited-reason necessity (degrading it
back to naive single-repair destroys the contribution) · source-applicant bootstrap clustering ·
the export determinism gate · the scripted-data banner.

---

## Standing constraints

- **Every number on the site comes from a committed run manifest with a hash.** No illustrative
  figures shaped like results — that is what got the predecessor spec retired.
- Never write that a model "violates ECOA." Write *"produces notices that would be deficient
  under §1002.9 if issued."*
- Frame fairness arms as **blindness/invariance tests under a stated causal assumption**, never
  as "measuring discrimination."
- Prefer *"we combine X, Y, Z; prior work does each separately"* over *"first ever."*

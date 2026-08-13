# Roadmap — `llm-credit-decision-audit`

> The build plan. Twelve phases, dependency-ordered. Every phase has an **exit criterion** that
> is checked by running something — no phase is "done" because it looks done.
>
> Companion docs: [`architecture.md`](./architecture.md) · [`related-work.md`](./related-work.md)

---

## Current status — 2026-08-12

Phases 0–8 are implemented. Phase 5 was hardened before Phase 6 so that every later check
inherits matched-trial completion semantics and trustworthy evidence identities. Phase 7 added
the preregistration and the inference layer. Phase 8 makes a run a first-class artifact: a
`credit-audit` CLI, three suites, a budgeted run pipeline, a byte-deterministic export whose
every published statistic re-derives from raw evidence, and the known-answer sweep that
publishes the harness catching all 14 planted defects while firing nothing else. Everything still uses
deterministic scripted agents and makes zero API calls; there is no provider result.

`PREREGISTRATION.yaml` is written but **not yet frozen**: `frozen_at` and `git_tag` are null,
and both the manifest and the integrity chain report that rather than hiding it. Tagging
`prereg-v1` happens before the first *published* run.

Framing is deliberately deferred. Phases 9–11 below remain plans, not implemented claims.

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
140 files / 6.7 MB, inside every budget. Exporting again to a second directory is
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

- `replay.json` belongs to Phase 9, with cassettes.

*Carried into Phase 11:* the manifest records the git commit, so a bundle exported at commit A
differs from one exported at commit B by that field. Phase 11's `git diff --exit-code
web/public/runs/` gate therefore requires the bundle to be regenerated in the same PR that
changes the code — which is the intended workflow, but it is a real constraint rather than a
free one.

---

## Phase 9 — Provider adapters (no live calls)

- `model/providers/openai_compat.py` — **primary portable adapter.** Verified to cover Gemini +
  OpenRouter + Together + Groq + local vLLM/Ollama for multi-turn tool calling
- `model/providers/gemini.py` — thin native adapter via `google-genai>=2.17` for Flex tier,
  `tool_choice: "validated"`, and cache telemetry
- `model/cassette.py` — record / replay / replay-or-record / off

**Non-obvious requirements**

- `google-generativeai` is **deprecated**; the package is `google-genai`. The **Interactions
  API** is GA and `generate_content` is legacy.
- **Thought signatures must be re-appended verbatim** in stateless mode. This is the documented
  #1 cause of silent breakage in hand-rolled Gemini agent loops.
- Default model `gemini-2.5-flash-lite` — the only current model with **thinking off by
  default**, which matters more for determinism than for cost.
- Unknown params are **silently ignored** by the OpenAI-compat layer. Never assume
  `extra_body: {"service_tier": "flex"}` worked — assert against returned usage.
- **Do not claim determinism from `temperature=0`.** No provider guarantees it. The honest claim
  is: deterministic *given fixed model responses* (cassette replay, CI-asserted); model
  stochasticity is **measured, not suppressed**.

**Exit:** adapters pass against recorded cassettes. No live API calls in this phase.

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
- `kind: "scripted"` drives a **non-dismissible banner on every route**, plus `<title>`, meta
  description, and OG image.
- Ship **three charts only**. A chart earns its place if it shows uncertainty or a mechanism.
  Cut pass-rate bars (redundant with the forest plot) and any calibration diagram (category
  error — we produce no probabilistic forecasts).

**Exit:** `pnpm build` succeeds and `assert-static` passes; every number on every page traces to
`stats/estimates.json`.

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

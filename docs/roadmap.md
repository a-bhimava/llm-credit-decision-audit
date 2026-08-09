# Roadmap — `llm-credit-decision-audit`

> The build plan. Twelve phases, dependency-ordered. Every phase has an **exit criterion** that
> is checked by running something — no phase is "done" because it looks done.
>
> Companion docs: [`architecture.md`](./architecture.md) · [`related-work.md`](./related-work.md)

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

**Goal:** the type system and the frozen export contract, before anything depends on them.

- `pyproject.toml`, `.gitignore`, `LICENSE`, CI skeleton
- `src/credit_audit/types.py` — every core record as frozen pydantic v2. Money as `int` cents,
  ratios as `Decimal` quantized to 4dp, **never float** (repairs do exact threshold arithmetic)
- `src/credit_audit/ids.py` — canonical JSON + blake2b-128 + **hierarchical seed derivation**
- `src/credit_audit/io/jsonl.py` — the single serialization boundary
- `schemas/export/*.schema.json` — eleven file types, versioned, tagged `export-schema-v1`

**Non-obvious requirements**

- `FinancialFacts` stores **primitives only**; `dti`/`cltv`/`utilization` are `@property`. An
  introspection test asserts no derived quantity is a stored field. This kills the bug class
  where repairing income leaves a stale DTI and the agent notices an incoherent record.
- `Applicant.facts` vs `Applicant.presentation` split, with `InterventionSpec.layer` naming
  which one an intervention may touch. Enforced at apply time.
- `seed(run_seed, applicant_id, arm_id, trial_index)` — a global RNG means adding profile #226
  shifts profiles 1–225 and destroys cross-run comparability.
- `TestResult.pair_id` exists so every check author must declare the bootstrap cluster.

**Exit:** `pytest tests/unit/test_types.py` green — no derived stored fields, canonical JSON
round-trips, IDs stable across `PYTHONHASHSEED`, seeds reproduce.

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
- `env/episode.py` — the loop, with `max_steps=12` and token/budget caps
- `model/client.py` — `ModelClient` protocol
- `model/scripted.py` — the ground-truth agents
- `model/cache.py` — response cache

**Non-obvious requirements**

- `submit_decision` **allows up to 10 reasons, not 4.** "Agent emitted 6 principal reasons" is
  itself a §1002.9 finding; capping it in the schema hides the finding.
- Two reason modes by flag: `--reason-mode coded` (enum + detail) vs `freetext`. Running both on
  the same profiles separates *selection error* from *articulation error*.

**Exit:** `credit-audit run --suite smoke --model scripted` produces trajectories. Zero API calls.

---

## Phase 3 — Profiles and renderers

**Goal:** a seeded synthetic population, deliberately including the cases that matter.

- `profiles/generate.py`, `profiles/creditfile.py`, `profiles/fixtures/` (+ `.sha256`)
- `render/table.py`, `render/prose.py`, `render/json_.py`

**Non-obvious requirements**

- **Synthetic only in this phase.** HMDA is a later offline step, deliberately, so the data layer
  can never block the checks layer.
- Deliberately generate **multi-constraint applicants** (2–3 breached thresholds). That is where
  laundering lives and where the naive single-repair test fails.

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

**Exit:** for every repairable code, `repair(code)` makes the oracle stop citing that code, and
the repaired applicant stays inside plausibility bounds.

---

## Phase 5 — The flagship check

**Goal:** `checks/reason_validity.py`. This is the contribution; it gets the most care.

Three tests per denied applicant:

| Test | Construction | Failure means |
|---|---|---|
| **Joint sufficiency** | Repair **all** cited reasons → must flip to approve | Reason set incomplete — omitted principal reason |
| **Leave-one-out necessity** (per `rᵢ`) | Repair every cited reason **except** `rᵢ`; if it still flips, `rᵢ` wasn't binding | `rᵢ` is spurious — laundering |
| **Omission scan** | Repair a breached-but-uncited factor alone (oracle enumerates; typically 0–3) | A principal reason was omitted |

**Non-obvious requirements**

- **Do not implement the naive single-repair test.** It produces false violations whenever two
  constraints bind at once — the common case, and exactly where laundering hides.
- Comparison is **rate-based**: `approve_rate(cf) − approve_rate(base) ≥ δ`, δ pre-declared.
  Never present a rate as a single flip.
- Full edge-case table from `architecture.md` §4.5: APPROVE base → `inapplicable`; COUNTEROFFER
  with worse terms → adverse action; refusal → excluded from denominator but **refusal rate
  reported prominently**; CF-leg-only refusal → `error` with `pair_completion_rate` reported,
  never silently dropped; >4 reasons → `reason_count_violation`, **not conflated with
  laundering**.

**Exit — the make-or-break test:** a golden test asserts `LaunderingAgent` is caught by LOO
necessity at ~100% and flagged by the omission scan for `CREDIT_SCORE_TOO_LOW`, while
`FaithfulAgent` passes at ~100%. Both must hold. The second is the positive control that proves
the repair machinery works.

---

## Phase 6 — Remaining checks

Priority order. Cut from the bottom if time runs short.

1. `checks/policy_adherence.py` — required-tool-before-decision, trap tool called, prohibited
   factor cited, reason-count violation (τ²-bench pattern: task completed + policy violated =
   **FAIL**)
2. `checks/monotonicity.py` + `interventions/monotone.py` — ↑income → non-decreasing approval;
   ↑DTI → non-increasing; ↑FICO → non-decreasing; ↑delinquencies → non-increasing.
   **Boundary-targeted sampling via the oracle** — violations concentrate at thresholds, so this
   raises power *and* cuts episodes.
3. `checks/invariance.py` — reorder statement lines, reword free text, reorder fields
4. `checks/serialization.py` — table / prose / JSON → measure decision variance
5. `checks/counterfactual_bias.py` — demographic + **authority** arms (framing is the first cut).
   The authority arm is the higher-signal one: ICE-Guard measured demographic bias at ~2.2% but
   **authority bias in finance at 22.6%**.

**Exit:** each scripted agent produces its designed signature — `NonMonotoneAgent` violates
monotonicity at its analytically computed rate, `FormatSensitiveAgent` shows exactly the known
serialization variance, and **`must_not_fire` holds**: clean agents stay clean. A harness that
fails everything catches everything; specificity is what a sharp reviewer checks.

---

## Phase 7 — Statistics

**Goal:** every number ships with uncertainty.

- `PREREGISTRATION.yaml` — families, hypotheses, α, δ, BH grouping
- `stats/families.py` — loads it and **hard-refuses to score an undeclared family**
- `stats/mcnemar.py` — exact test on paired flips; estimand is the **discordant-pair rate**
- `stats/bootstrap.py` — BCa, resampled at the **`pair_id` cluster level**
- `stats/fdr.py` — Benjamini-Hochberg across pre-declared families
- `stats/power.py` — MDE, published *before* the run · `stats/passk.py` — pass^k over k=5

**Exit:** simulation-based calibration passes — under the null, McNemar p-values are uniform, BH
holds FDR at α over 1,000 simulated runs, bootstrap CIs achieve ~95% coverage. Plus a test
asserting cluster-level bootstrap gives **wider** CIs than response-level, so it fails loudly if
anyone later "simplifies" the clustering away.

*Cut line:* if BCa fights back, ship cluster-level percentile bootstrap and set
`ci.fallback_used` — the site then automatically says "percentile bootstrap", so the README and
the site can never disagree.

---

## Phase 8 — Run, report, export

**Goal:** a real scripted run and a byte-deterministic bundle.

- `cli.py` + `suites/{smoke,core,full}.yaml`
- `report/manifest.py`, `report/markdown.py`, `report/export.py` — **no `html.py`**, the site is
  the drill-down UI
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

**Exit:** `credit-audit run --suite core --model scripted --seed 1729` → `export` → **`export`
again to a temp dir and `diff -r` is byte-identical** → `credit-audit verify --strict` re-derives
every statistic from raw JSONL and passes.

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

Cut from the bottom: framing bias arm → serialization check → `/checks` routes → replay viewer
→ Gemini native adapter (OpenAI-compat covers it).

**Never cut:** the oracle · the scripted agents · LOO necessity (degrading it back to naive
single-repair destroys the contribution) · pair-level bootstrap clustering · the export
determinism gate · the scripted-data banner.

---

## Standing constraints

- **Every number on the site comes from a committed run manifest with a hash.** No illustrative
  figures shaped like results — that is what got the predecessor spec retired.
- Never write that a model "violates ECOA." Write *"produces notices that would be deficient
  under §1002.9 if issued."*
- Frame fairness arms as **blindness/invariance tests under a stated causal assumption**, never
  as "measuring discrimination."
- Prefer *"we combine X, Y, Z; prior work does each separately"* over *"first ever."*

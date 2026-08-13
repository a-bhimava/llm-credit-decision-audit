# llm-credit-decision-audit

**A causal audit harness for testing whether an underwriting agent's stated adverse-action
reasons are the reasons it actually acted on.**

> ### Status: implementation through Phase 9
>
> The reason-validity engine, the judge-free checks, the statistics, the run/export/verify
> pipeline, and the provider adapters are implemented and validated against deterministic
> scripted agents. A handful of real responses have been recorded to validate the adapters
> against the wire format, and **there are no provider findings to report** — six episodes is
> not a result, the published evidence remains the scripted known-answer run, and the exporter
> refuses to let a scripted run be phrased as a claim about any model.

---

## The problem

An agent denies a loan application and writes: *"Denied — insufficient income."*

Under **[12 CFR §1002.9](https://www.consumerfinance.gov/rules-policy/regulations/1002/9/)**,
an adverse-action notice must state specific principal reasons that reflect the factors
actually considered. A reason can be grounded in the file and fluent while still not being the
reason that drove the decision. This harness tests that causal claim directly rather than
asking another model to judge the explanation.

The policy used here is synthetic and the applicants are synthetic. A finding means that an
agent produced a notice that would be deficient under the tested policy and §1002.9 if issued;
it is not a determination that a model or lender violated ECOA.

## The reason-validity test

Every comparison is a trial-index-aligned pair. Only an explicit approval is `APPROVE`; a
denial or demonstrably worse counteroffer is `ADVERSE`; referrals, refusals, missing decisions,
and unclassifiable counteroffers are `NO_DECISION`. A one-sided incomplete pair is an error.
Two-sided incompletions are excluded from the decision denominator and remain visible in the
pair-completion rate.

The isolation design handles applicants with several simultaneous policy breaches:

| Check | Matched construction | Failure means |
|---|---|---|
| **Joint sufficiency** | Original applicant → all cited, reachable policy reasons repaired | The cited set does not account for the adverse decision |
| **Cited-reason necessity** | Only cited reason `r` remains → all oracle breaches repaired | `r` was not shown to be binding |
| **Omission** | The same isolation pair for an uncited principal reason `r` | A binding principal reason was omitted |

The all-repaired arm is the experimental control. If it does not establish isolation, the
result is `INAPPLICABLE`, never a pass. “Principal” means the oracle's ranked unique breached
codes, truncated at the synthetic policy's configured maximum. The current maximum is four;
that is **not a statutory cap**. The
[official Regulation B interpretation](https://www.consumerfinance.gov/rules-policy/regulations/1002/interp-9/)
does not mandate a number and says that disclosure of more than four reasons is unlikely to be
helpful.

Facially invalid, vague, unmapped, and reason-count findings belong to policy adherence.
`reason_validity.fabrication` is narrower: it covers a cited, reachable, rule-backed code that
the applicant did not breach.

## Phase 6 checks

Phase 6 runs all contrasts through one immutable `PairPlan`/`ArmPlan` execution path with
common trial seeds, arm-specific episode identities, and a normalized decision signature.

- **Policy adherence:** required tools must succeed before submission, code-specific tools are
  enforced, prohibited-tool attempts and prohibited presentation factors are caught, reason
  vocabulary/count rules are separated, and the submitted decision is checked against the
  oracle. Completing the task does not erase a policy failure.
- **Monotonicity:** absolute boundary-straddling interventions test income, credit score, DTI
  through monthly debt, and minor and major delinquency counts in their declared directions.
- **Invariance:** deterministic statement ordering, JSON field ordering, and a committed
  hand-authored note paraphrase preserve the semantic application packet.
- **Serialization:** table, prose, and JSON receive the same complete semantic packet and are
  compared on outcome, terms, risk grade, and ordered reason codes—not wording.
- **Proxy-signal blindness:** authority, surname, first-name/pronoun, and cohort/graduation-year
  contrasts keep financial facts fixed. Protected-class analysis labels never enter the
  rendered packet. These are proxy-signal invariance tests under a stated causal assumption,
  not proof of discrimination.

Framing interventions are deferred.

## Statistics

Every number is scored against
[`PREREGISTRATION.yaml`](src/credit_audit/stats/PREREGISTRATION.yaml), written before any run
and hashed into the estimate document. Declaring a family is mandatory: the scorer **raises**
on an undeclared family rather than inventing a hypothesis after the fact, and a check that
is not declared is computed but permanently marked exploratory and excluded from multiplicity
control. The document is not yet frozen; it is git-tagged `prereg-v1` before the first full
run.

- **Paired test:** McNemar's exact test on the two discordant cells. The exact p-value is
  valid but conservative on a discrete statistic, and it is what Benjamini-Hochberg consumes;
  a mid-p value ships beside it for calibration diagnostics only. Two-sided everywhere.
- **Intervals:** BCa bootstrap resampled at the **originating source applicant**
  (`cluster_id`), never at the pair or the response — sibling variants and repeated trials of
  one applicant are dependent, and resampling them independently reports a standard error
  smaller than the design supports. When BCa's correction terms are undefined, which is the
  normal case for a deterministic control, the interval falls back to cluster-level percentile
  and says so in `ci.fallback_used`.
- **Multiplicity:** Benjamini-Hochberg within each declared family, never pooled across them.
- **Power:** the minimum detectable effect is published before the run, so a null result reads
  as "no effect above this size was detectable" rather than "no effect".
- **pass^k:** the unbiased `C(s, k) / C(n, k)` estimator over k = 5, reported only where a
  per-trial pass is unambiguous.

These procedures are checked by simulation, not assertion
([`tests/stats/test_calibration.py`](tests/stats/test_calibration.py)): the exact test's size
is at or below α at every level tested, BH holds the false-discovery rate at q over 1,000
simulated runs, clustered intervals cover the truth 94.5% of the time against a nominal 95%,
and clustered resampling comes out 2.13× wider than response-level resampling on clustered
data — the last of which fails loudly if anyone later removes the clustering.

## Running it

```bash
credit-audit run --suite core --model scripted --seed 1729   # 5,630 episodes, $0.00
credit-audit export --run <run_id>                            # 140 files, 6.7 MB
credit-audit verify --run <run_id> --strict
```

`run --dry-run` prints the execution plan and its episode bounds without executing anything.
Suites are data ([`suites/*.yaml`](src/credit_audit/suites)), so the configuration a run used
is recorded rather than reconstructed from shell history, and their zero-dollar caps are live
assertions that a scripted run made no paid call.

The exporter enforces three rules in code rather than by discipline:

1. **No number without support.** Every headline must resolve to an estimate in
   `stats/estimates.json` with at least one supporting test, or the export fails.
2. **A scripted run is never phrased as a model finding.** Headline strings are linted against
   model-claim phrasings, so a known-answer validation of the harness cannot ship worded as a
   claim about somebody's model.
3. **Nothing is written until it has been scanned.** Credentials and local absolute paths are
   caught before a byte reaches disk.

Two things make the bundle checkable by a stranger. Exporting the same run twice produces
**byte-identical** output — same bundle sha256, `diff -r` clean — so re-exporting and diffing
is a real test. And `verify --strict` re-derives every estimate, the summary, and every
check-row table from the raw JSONL rather than only re-checking hashes, which is what catches a
doctored file whose hashes were rebuilt.

Raw run artifacts never enter git. A scripted run regenerates them in seconds at zero cost, and
the integrity chain closes through their recorded sha256.

### Talking to a real provider

```bash
credit-audit run --model gemini:gemini-2.5-flash-lite \
    --cassette tests/fixtures/cassettes/smoke_gemini --cassette-mode replay
```

Two adapters implement the same `ModelClient` protocol: a portable one over any
OpenAI-compatible endpoint (Gemini, OpenRouter, Together, Groq, local vLLM/Ollama), and a thin
native Gemini one whose reason for existing is `cached_content_token_count` — prompt-cache
behaviour is **measured from provider-reported usage, never asserted**.

Neither adapter can see `ModelRequest.env_state`; a test parses every file under
`model/providers/` and fails if one does. An adapter that reached into the environment could
consult ground truth and produce a "real model run" that was quietly cheating, and nothing
downstream would notice.

**Cassettes record at the protocol boundary**, not at HTTP, so a recording made through the
compat endpoint replays through the native adapter and keys on the same content-addressed
episode identity as everything else. `replay` mode never calls the provider: a miss raises
rather than falling through to the network, and the run stops rather than accumulating errors
that look like provider trouble. A pure replay needs no credential — the inner client in that
mode raises if it is reached at all.

**Spend is authorized explicitly.** Every suite caps `max_usd` at 0.0, so a provider run is
refused until `--max-usd` says otherwise; `Usage.cost_usd` is computed from returned token
counts against a dated price table, and an unpriced model is flagged rather than assumed free.

The evidence site begins in a later phase.

## Evidence integrity

- Evidence payloads are recursively immutable and hashable; mutable JSON containers appear
  only at schema/provider boundaries.
- `applicant_id` is the stable selected experimental unit. A separate content ID identifies
  each facts-and-presentation variant.
- `episode_id` hashes the plan key; `trajectory_id` hashes the realized semantic message,
  tool-call, tool-result, decision, and termination history.
- Tool evidence retains provider call IDs, assistant requests, correlated results, turn index,
  arguments, success, and errors.
- `pair_id` names one contrast. `cluster_id` names the originating source applicant, and it is
  the unit the bootstrap resamples, so sibling variants stay together.
- Cache identity includes the complete episode context. Cached/replayed responses preserve
  telemetry but have zero cost in the current run.

## Known-answer validation

The controls' true rules are code in this repository. `FaithfulAgent` is the `must_not_fire`
control for every family. Defect agents independently plant laundering, omission, shortcuts,
trap-tool use, prohibited reasons, excessive reasons, wrong decisions, non-monotonic behavior,
serialization sensitivity, visible-order/paraphrase sensitivity, authority sensitivity, and
demographic-proxy sensitivity. This tests both sensitivity and specificity without an LLM
judge or human labels.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Supported Python versions are 3.11–3.14. The simulation-based calibration tests are marked
`slow` and run by default; `pytest -m "not slow"` skips them.

## Documentation

- [`docs/method.md`](docs/method.md) — how a run works end to end, and what a finding means
- [`docs/statistics.md`](docs/statistics.md) — preregistration, paired test, clustered intervals
- [`docs/reason-codes.md`](docs/reason-codes.md) — the vocabulary, the tiers, and the repairs
- [`docs/architecture.md`](docs/architecture.md) — evidence identities, execution, and checks
- [`docs/limitations.md`](docs/limitations.md) — where the data anchoring stops
- [`docs/roadmap.md`](docs/roadmap.md) — completed and deferred phases
- [`docs/related-work.md`](docs/related-work.md) — competitive map and novelty delta

## Disclaimer

Synthetic lender policy, synthetic applicants. This is a research and evaluation tool. It is
**not legal advice or a compliance certification**, and it does not assess a real lender's
underwriting. A result describes one agent, prompt, tool scaffold, and policy configuration—not
a model in general.

## License

Apache-2.0 — see [LICENSE](LICENSE).

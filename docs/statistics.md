# Statistics

> Every number ships with uncertainty, a declaration written before the run, and a simulation
> showing the procedure behaves as advertised.
>
> Companion docs: [`method.md`](./method.md) · [`architecture.md`](./architecture.md) ·
> [`limitations.md`](./limitations.md)

---

## The preregistration

[`PREREGISTRATION.yaml`](../src/credit_audit/stats/PREREGISTRATION.yaml) declares families,
hypotheses, α, δ thresholds, estimands, and BH grouping before any run is scored. Its sha256
travels in every run manifest and every estimates document, so a reader can verify which
declaration the reported numbers were scored against.

**It is frozen and git-tagged `prereg-v1`**, so the hypotheses provably predate every
published run. `frozen_before_run` is not taken on trust: the exporter resolves the tag in
git, confirms its commit is an ancestor of the run's commit, and compares the freeze time to
the run's. It reports `null` when it cannot check, which is deliberately distinct from a
checked `false`. Changing a hypothesis now requires a visible re-freeze.

Two asymmetries are deliberate:

- **An undeclared family raises.** A family is the unit BH multiplicity control is defined
  over, and one invented after seeing results is the specific practice preregistration
  prevents. `FRAMING` is deliberately absent, so a deferred framing result raises rather than
  acquiring a hypothesis retroactively.
- **An undeclared check does not raise.** It is scored, permanently marked `exploratory`,
  rendered below the preregistered estimates, and excluded from every BH group.

Two guards keep the document honest against the code: every `CHECK_*` constant the checks
layer can emit must resolve to a declared hypothesis or a declared operational check, and every
declared δ must equal the threshold the check code actually applies.

---

## The paired test

**McNemar's exact test**, two-sided, on the two discordant cells.

All of the evidence about a matched contrast lives in the pairs that disagreed. Concordant
pairs carry no information about whether the intervention moved anything, so they are not in
the statistic — but they stay in the reported denominator, because a reader needs to know
whether 8 flips came from 10 pairs or from 10,000.

**Exact, not chi-square.** The asymptotic statistic is unusable at the discordant counts this
harness produces, which are often single digits. Under the null the number of flips in one
direction is `Binomial(b + c, 0.5)`, which is symmetric, so doubling the smaller tail is exact
rather than approximate.

**Two conventions, and they are not interchangeable:**

| | Meaning | Used for |
|---|---|---|
| `p` | Exact two-sided. Valid but conservative: on a discrete statistic the guarantee is `P(p ≤ α) ≤ α`, never equality | Multiplicity control |
| `p_mid` | Mid-p variant. Approximately uniform under the null | Calibration diagnostics only |

A calibration plot drawn from exact p-values looks broken when the test is merely being
conservative, which is why the mid-p value ships beside it — and why it is deliberately not
what BH consumes.

**Two-sided everywhere.** A one-sided test at the same α rejects more readily in the declared
direction, and choosing it after seeing which way the flips went is the oldest trick available.
The harness removes the option.

---

## The estimand follows the declared relation

| Relation | Estimand | Paired test |
|---|---|---|
| `FLIP_TO_APPROVE` (reason repair) | paired rate difference `(c − b) / n` | McNemar exact |
| `NONDECREASING` / `NONINCREASING` (monotone) | rate of the **one forbidden** transition | McNemar exact |
| `INVARIANT` (invariance, serialization) | decision-signature change rate | none |
| `INVARIANT` with directional interest (authority, demographic) | paired rate difference | McNemar exact |

Monotone checks report the forbidden transition **alone**, not net movement. A forbidden flip
is not excused by an equal number of permitted flips in the other direction; with `b == c` a
net effect of zero would hide real paired reversals.

Invariance checks declare **no** paired test. Their null is "the decision signature did not
change", and McNemar tests asymmetry between the two flip directions — a different question.
Their inference is the clustered interval against zero.

### Reading `rejected` correctly

For a monotone or reason-repair check, the intervention is *supposed* to move the decision. A
rejected null of symmetry there means the intervention worked, not that the agent failed. The
failure signal is the check's failure rate and its forbidden-transition rate, never the
p-value on its own.

---

## Intervals

**BCa bootstrap, resampled at the originating source applicant (`cluster_id`).**

One source applicant produces sibling profile variants, several contrasts, and k repeated
trials of each. Those observations are dependent by construction: a quirk about that
applicant's file is inherited by everything derived from it. Resampling responses
independently treats one quirk as many independent pieces of evidence and reports an interval
narrower than the design supports.

`pair_id` identifies a contrast and is **not** the resampling unit. Two contrasts built from
one applicant have different `pair_id` values and the same `cluster_id`.

**The statistic is a pooled ratio**, `sum(numerators) / sum(denominators)`, not a mean of
per-cluster rates. Averaging rates would weight a cluster with 2 trials equally against one
with 40.

**The BCa fallback fires routinely, and says so.** BCa's bias-correction and acceleration terms
are undefined when the bootstrap distribution is degenerate — which is the *normal* case for a
deterministic scripted control where every cluster returns the identical value. The interval
then falls back to cluster-level percentile and sets `ci.fallback_used`, which the export
contract carries to the site. A page can never claim BCa when percentile ran.

A zero-width interval on a scripted run is a property of the known-answer design, not a
precision claim; `ci.degenerate` marks it.

---

## Multiplicity

Benjamini-Hochberg **within each declared family**, never pooled across them.

Pooling is not the conservative choice it looks like. A family with many easy rejections raises
the BH threshold for every other family in the pool, so a marginal p-value can be carried
across the line by results it has nothing to do with.

Exploratory hypotheses are excluded from every group. Including them would inflate the group
size and penalize the preregistered tests for the existence of diagnostics.

---

## Power

MDE is published **before** the run, from Connor's normal approximation for McNemar's test,
parameterized as the harness observes the design: `n_pairs` matched pairs, expected discordance
`π_d = (b + c) / n`, and net effect `δ = (c − b) / n`.

Power computed after seeing the result is not power, it is a restatement of the p-value. The
preregistration therefore fixes α and target power up front, so a null result reads as "no
effect above this size was detectable" rather than "no effect".

On deterministic scripted controls the planted effects are exactly 0.0 or 1.0, so the MDE is
reported for completeness and is not the binding constraint. It becomes load-bearing the moment
a stochastic agent — or a real provider — produces intermediate rates.

---

## pass^k

pass^k is the probability that **all** k trials pass. It is the reliability complement of
pass@k: an underwriting agent gets no retries, and the notice it produces is the notice the
applicant receives.

The estimator is the unbiased `C(s, k) / C(n, k)`. The plug-in `(s/n)**k` is biased upward at
small `n`, which is exactly the regime this harness runs in. Units with fewer than k trials are
excluded and counted, and `pass_1` is computed on the same surviving units so the two are
directly comparable.

pass^k is reported **only where a per-trial pass is unambiguous** — monotone and invariance
relations give one. `FLIP_TO_APPROVE` does not: a trial where the repaired arm stayed adverse
is the finding itself, not an inconsistency. Reason repair therefore reports no pass^k.

---

## Simulation-based calibration

The procedures are checked by simulation rather than by citation, because the implementation is
what ships. Every simulation is seeded, so the tests are deterministic despite being Monte
Carlo ([`tests/stats/test_calibration.py`](../tests/stats/test_calibration.py)).

| Property | Measured |
|---|---|
| Exact test size under the null at α = 0.01 / 0.05 / 0.10 | 0.0065 / 0.0300 / 0.0703 — valid at every level |
| Exact p-values super-uniform across the range | `P(p ≤ t) ≤ t` at 19 thresholds |
| Mid-p uniformity | mean 0.506, `P(p ≤ 0.05)` = 0.045 |
| BH false-discovery rate over 1,000 simulated runs | ≤ q, while still recovering planted effects |
| Clustered BCa interval coverage (nominal 95%) | 94.5% over 400 simulated datasets |
| Clustered vs response-level interval width | 2.13× wider, in 60 of 60 clustered datasets |

The last row is a guard, not a statistic. If someone later "simplifies" the clustering away,
that test fails loudly rather than quietly shrinking every published interval. Its companion
checks that on *independent* data the two agree — which shows the clustered interval is wider
because the data are dependent, not because the estimator is uniformly inflated.

---

## What the numbers do not do

- They do not establish that any model violated ECOA. See [`method.md`](./method.md) §11.
- They do not generalize beyond one agent, prompt, tool scaffold, and policy configuration.
- On a scripted run they measure the harness against known answers. That is a **stronger**
  claim than a rate about a real model, but it is a different claim, and the bundle refuses to
  let it be phrased as the other one.

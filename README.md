# llm-credit-decision-audit

**An audit harness that tests whether an LLM underwriting agent's stated adverse-action reasons
are the reasons it actually acted on — by repairing the cited factor and re-running.
No judge, no labels.**

> ### Status: scaffolding — Phase 0 of 11
>
> There are **no results yet**. Nothing in this README is a measurement, because no evaluation
> has been run. When results exist they will come from a committed run manifest with a content
> hash, and this notice will say so.

---

## The problem

An LLM denies a loan application and writes: *"Denied — insufficient income."*

Under **[12 CFR §1002.9](https://www.consumerfinance.gov/rules-policy/regulations/1002/9/)**
(ECOA / Regulation B), that sentence carries legal weight. A creditor taking adverse action must
state the **specific principal reasons**, and those reasons must reflect factors *actually
considered or scored*. The official interpretation is explicit that reasons based on "the
creditor's internal standards or policies" are insufficient.

Nothing forces the LLM's sentence to be true.

The model may have denied on credit score, or on a proxy it should not have used, or on nothing
coherent at all — and then written a fluent, plausible, legally false explanation. The
literature calls this **reason-code laundering**. It is not a hallucination in the usual sense:
the stated reason is often a genuine weakness in the file. It just isn't the reason the model
acted on.

Existing evaluation tooling scores that output as grounded, policy-compliant, and semantically
accurate. All three are correct, and all three miss the violation.

## The test

Causal, deterministic, and judge-free:

```
  decision = DENY,  stated reason = "insufficient income"
      │
      ▼   repair only the cited factor — raise income past the policy threshold,
          holding every other fact and all presentation bit-identical
      │
  APPROVE → the reason was binding                  FAITHFUL
  DENY    → the reason was not binding              DEFICIENT under §1002.9
```

The naive form of this test is wrong, and correcting it is the methodological contribution.
"Repair the one cited reason; if it doesn't flip, the reason is false" breaks whenever two
constraints bind simultaneously — the common case in realistic denials, and exactly where
laundering hides. The harness runs three tests per denied applicant instead:

| Test | Construction | A failure means |
|---|---|---|
| **Joint sufficiency** | Repair **all** cited reasons together → must flip to approve | The stated reason set is incomplete — an omitted principal reason |
| **Leave-one-out necessity** (per reason `rᵢ`) | Repair every cited reason **except** `rᵢ`. If it still flips, `rᵢ` wasn't binding | `rᵢ` is spurious |
| **Omission scan** | Repair a factor that breaches policy but was **not** cited | A principal reason was omitted |

Comparison is rate-based over *k* trials, never a single flip, because agents are stochastic.

## How the harness proves itself

The obvious objection — *"how do you know a failed repair means the reason was false, rather
than that your repair was broken?"* — is answered by running the whole thing against **scripted
agents whose true decision rule is written in the repo**. `LaunderingAgent` secretly denies on
credit score while always stating "insufficient income"; `FaithfulAgent` states exactly the
binding thresholds. The harness must catch the first and clear the second.

That known-answer table will be published here, alongside the checks that must **not** fire — a
harness that fails everything catches everything, so specificity is reported with equal weight.

## Planned scope

Six check families, five of them requiring no LLM judge and no human labels: reason validity,
policy adherence, monotonicity, invariance, serialization fragility, and counterfactual bias
(demographic / authority / framing arms). Every reported number ships with a confidence
interval clustered at the matched-pair level, a paired test, and multiplicity correction across
pre-registered families.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

Requires Python 3.11+. Phases 0–8 make **zero API calls** by design — the scripted agents are
deterministic, so the harness is fully testable before any model is ever contacted.

## Documentation

- [`docs/roadmap.md`](docs/roadmap.md) — the phased build plan and what each phase must prove
- [`docs/architecture.md`](docs/architecture.md) — types, agent environment, reason engine, verification design
- [`docs/related-work.md`](docs/related-work.md) — the competitive map and the precise novelty delta

## Disclaimer

Synthetic lender policy, synthetic applicants. This is a research and evaluation tool. It is
**not legal advice and not a compliance certification**, and it does not assess any real
lender's underwriting. Where results describe a model, they describe a specific prompt and tool
scaffold under a specific policy — not a model in general.

## License

Apache-2.0 — see [LICENSE](LICENSE).

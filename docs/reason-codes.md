# Reason codes

> The vocabulary an adverse-action notice is scored against, how free text becomes a code, and
> what each code's mechanical repair is.
>
> Companion docs: [`method.md`](./method.md) · [`statistics.md`](./statistics.md)

---

## Where the vocabulary comes from

The codes follow the Regulation B Appendix C sample notice vocabulary. Appendix C is a **model
form**, not a closed statutory enumeration — a real notice may state a specific principal
reason not on the list. The harness treats the list as the vocabulary of the *synthetic policy*
it evaluates, which is a narrower and checkable claim.

Codes split into three groups, and keeping them apart is what stops a structural defect from
being reported as a causal one.

### Reachable, rule-backed codes

Thirteen codes that a rule in this synthetic policy can actually produce. Only these can
support a `reason_validity.fabrication` finding.

| Code | Repairable | Repair moves |
|---|---|---|
| `INSUFFICIENT_INCOME` | yes | annual income up |
| `EXCESSIVE_OBLIGATIONS_DTI` | yes | monthly debt down |
| `CREDIT_SCORE_TOO_LOW` | yes | credit score up |
| `EXCESSIVE_UTILIZATION` | yes | revolving balance down |
| `DELINQUENT_OBLIGATIONS` | yes | 30/60/90-day delinquency counts down |
| `INSUFFICIENT_CREDIT_HISTORY` | yes | oldest tradeline age and open tradelines up |
| `TOO_MANY_INQUIRIES` | yes | recent inquiries down |
| `INSUFFICIENT_EMPLOYMENT_HISTORY` | yes | employment months up |
| `TEMPORARY_OR_IRREGULAR_EMPLOYMENT` | yes | employment status |
| `UNVERIFIABLE_INCOME` | yes | income documented |
| `LOAN_AMOUNT_EXCEEDS_LIMIT` | yes | loan amount down |
| `DEROGATORY_PUBLIC_RECORD` | yes | public records removed |
| `BANKRUPTCY` | yes | bankruptcy record removed |

`INSUFFICIENT_INCOME` and `EXCESSIVE_OBLIGATIONS_DTI` both clear a DTI breach, but only one of
them moves income. Keeping the two repairs distinct is what keeps the two reasons
experimentally distinguishable — a single "fix DTI" repair would make them the same
intervention and the necessity test would be unable to tell them apart.

`CREDIT_SCORE_TOO_LOW` is the hard one: a score is a composite of the very primitives the other
repairs move. It is treated as a generator-calibrated primitive, with a coherence check
available. Defining it as a deterministic scorecard would be more elegant and costs several
days; the trade is recorded here rather than hidden.

### Unreachable codes

In the Appendix C vocabulary, but no rule in this synthetic policy can trigger them —
`COLLATERAL_VALUE_INSUFFICIENT` on an unsecured product, for instance. Citing one is a
**policy-adherence** finding (`unreachable_reason`), not fabrication: the agent named a factor
this lender could not have acted on.

### Structural codes

Not reasons at all, but records of how the notice failed:

| Code | Meaning |
|---|---|
| `NON_SPECIFIC_INTERNAL_POLICY` | "does not meet internal credit standards" — no specific principal factor |
| `OUT_OF_SCHEMA_FACTOR` | cites information the application record cannot contain |
| `OUT_OF_POLICY_FACTOR` | outside the policy's vocabulary entirely |
| `PROHIBITED_BASIS_ADJACENT` | references a prohibited basis or a presentation proxy |
| `INCOMPLETE_APPLICATION` | procedural |
| `OTHER_UNMAPPED` | no tier could map the clause |

These fail with **zero API calls** and are all policy-adherence results.

---

## The fabrication boundary

`reason_validity.fabrication` is narrow on purpose: a **cited, reachable, rule-backed** code
that the applicant did not breach.

Everything else — vague, unmapped, unreachable, out-of-schema, out-of-policy, too few reasons,
too many reasons — is policy adherence. Folding them into fabrication would inflate the
flagship metric with structural defects that have nothing to do with causal reason validity,
and it is exactly the conflation a careful reviewer would catch.

---

## Three extraction tiers, always recorded

Free text becomes a code through one of three tiers, and `mapping_method` is **always**
recorded on the resulting `StatedReason`. It is never inferred after the fact.

| `mapping_method` | Tier | Notes |
|---|---|---|
| `structured` | The agent emitted a code directly | `reason_mode: coded` |
| `lexicon` | Committed phrase lexicon | Deterministic, offline |
| `embedding` | Embedding similarity | Not wired up; no embedding model is in this project |
| `llm_remap` | LLM remap | **Not implemented.** Deliberately: an LLM in the mapping path would reintroduce the judge this design removes. `llm_remap_rate` is therefore structurally 0.0, not an empirical finding |
| `unmapped` | Nothing matched | Becomes `OTHER_UNMAPPED`, a policy-adherence finding |

**`llm_remap` is the tier that would compromise the judge-free claim**, so its rate is reported
in every run's `operational` block — including, and especially, when it is zero. A remap rate
above 10% would itself be a headline finding: it would mean stated reasons are not
machine-mappable.

Running both `coded` and `freetext` modes over the same profiles separates **selection error**
(the agent chose the wrong factor) from **articulation error** (the agent chose right and wrote
it unmappably). Those are different failures and a single number would blur them.

---

## Reason counts

The synthetic policy configures a minimum and a maximum number of stated reasons for an adverse
decision. The maximum is currently four.

**Four is not a statutory cap.** The
[official Regulation B interpretation](https://www.consumerfinance.gov/rules-policy/regulations/1002/interp-9/)
mandates no number and says only that disclosing more than four reasons is unlikely to be
helpful. The decision tool deliberately accepts up to ten so that an excess stays *observable*
as a finding rather than being clipped away by a schema.

The same number bounds "principal" for the omission scan: the oracle's ranked unique breached
codes, truncated at the policy maximum. Fifth-and-later breaches therefore cannot become false
omissions against an agent that faithfully reported the allowed principal set.

---

## Repairs

Every repairable code has a mechanical repair with two properties the whole design depends on:

1. **Primitives only.** Derived quantities (`dti`, `cltv`, `utilization`) are computed
   properties, never stored fields, so a repair cannot leave a stale ratio behind for the agent
   to notice.
2. **Overshoot by 20%.** A repair clears the threshold rather than landing on it. The boundary
   is where agent noise dominates, and a repair that sits exactly on a cut tests noise instead
   of causality.

The invariant every repair must satisfy: after `repair(code)`, the oracle stops citing that
code, and the repaired applicant stays inside plausibility bounds. Both are asserted for every
repairable code.

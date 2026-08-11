# Limitations of the applicant population

`docs/architecture.md` §5 sketched the design; this document is the promised place where
every real gap between "real HMDA data" and "the population this harness actually evaluates"
is stated plainly, with the exact citation behind every number that is cited and an explicit
flag on every number that is not. Nothing here is a surprise a careful reader should have to
find themselves.

## 1. HMDA anchors realism; it never determines truth

Every synthesized profile is evaluated through Phase 1's real `policy/oracle.py` at
generation time. HMDA's own `action_taken` and `denial_reason-1..4` columns are **read only
as a query-level filter** (restricting the sampled applications to ones with a completed
originate-or-deny outcome, `actions_taken=1,3`) and are **never read per-row** to influence
anything about a synthesized applicant. Our 16 underwriting rules are our own invented
thresholds; a real mortgage lender's approval decision has no bearing on them, and no code
path in this project lets it.

## 2. The HMDA sample is a convenience sample, not a probability sample

`scripts/build_hmda_tables.py` does not download the full ~2.5 GB HMDA Modified LAR file for
`years=2024&actions_taken=1,3&loan_types=1`. It pulls 40 HTTP byte-range chunks (20 MB each,
~800 MB total, ~1.5M usable rows after filtering) **evenly spaced across the file's byte
offsets**, not a random sample of records. This was a deliberate choice over reading only a
file *prefix*: the file is grouped by lender (LEI), so a prefix read would sample only
whichever lenders happen to sort first; even spacing crosses many different lenders instead.
It is still a convenience sample, not a stratified or random probability sample of 2024 HMDA
filers, and is presented as such.

Rows missing income, DTI, race, ethnicity, sex, or age (HMDA's own "not available"/exempt
sentinels) are dropped before aggregation. The committed table
(`profiles/hmda_tables/joint_marginals_2024.json`) keeps only
`(income_bin × dti_bracket × race × ethnicity × sex × age_band)` cells with count ≥ 5, and
records its own provenance (query URL, resolved file URL, fetch timestamp, byte ranges
sampled, rows scanned/kept) inline.

HMDA itself has further known limitations this project inherits: it has **no credit score**
field (GAO-09-704), is privacy-modified (fields binned, rounded, or suppressed by the
Bureau before publication), is **mortgage-only**, and is not a census of all mortgage
activity — only covers institutions meeting HMDA's reporting thresholds.

## 3. Loan amount is never drawn from HMDA

HMDA's `loan_amount` column describes **mortgages** — tens of thousands to low millions of
dollars. This product is a $1,000–$100,000 unsecured personal loan (`policy.yaml`'s
`product.min_amount_cents`/`max_amount_cents`). Using HMDA's loan amounts would be
structurally incommensurable, so `loan_amount_cents` is drawn **independently**, from a
lognormal distribution whose median is anchored to a real cited figure and whose shape is
our own choice:

- **Cited:** Experian, "Average Personal Loan Balance Grows 1.7% in 2025" — national average
  outstanding personal-loan balance of **$19,333** (data as of 2025-09, published
  2026-03-30). `profiles/calibration/loan_amount_distribution.yaml`.
- **Not cited, our own choice:** the lognormal shape and `sigma=0.65`. Experian reports only
  a single average, not a distribution, so the spread is ours, chosen to keep the bulk of
  draws inside the product's own bounds.

## 4. HMDA's DTI bracket is derated before use, and the derating factor is a proxy

HMDA's `debt_to_income_ratio` is the applicant's *total* monthly debt (including the
mortgage payment being originated in that same record) over gross monthly income. Using it
directly as a personal-loan applicant's existing debt burden would silently launder a
mortgage-sized obligation onto someone who, in this product, has no mortgage. This project
derates it in two explicit, inspectable steps (`profiles/selection.py::_monthly_debt_cents`):

1. Each HMDA DTI bracket (already bucketed for privacy — `"<20%"`, `"20-30%"`, ...,
   `">60%"`) is mapped to a **point-estimate midpoint** (e.g. `"20-30%" → 0.25`). These
   midpoints are our own reasonable reading of the bracket labels, **not independently
   cited**.
2. The midpoint is multiplied by a **non-mortgage debt share**:
   - **Cited:** Federal Reserve Bank of New York, *Household Debt and Credit Report*, Q4
     2025 — mortgage balances $13.17T of $18.80T total household debt ≈ 70%, so
     `NON_MORTGAGE_DEBT_SHARE = 0.30`.
   - **Caveat, stated directly:** this is a **balance-based** statistic (stock of debt
     outstanding), used as a proxy for a **payment-based** quantity (share of a monthly DTI
     ratio). It is the best available public, dated, citable figure for this purpose, not an
     exact match. A side effect: this derating makes `max_dti` very difficult to breach
     through natural Stage A sampling alone (the derated ratio rarely approaches the 43%
     threshold) — Stage C's audit-and-top-up loop covers it via deliberate construction
     (§6 of `docs/architecture.md`'s design, `policy/boundary.py`'s `set_dti`) rather than
     leaving it unreachable.

## 5. Fannie Mae is not used, for two independent reasons — replaced by a direct Experian citation

`docs/architecture.md`'s original sketch proposed calibrating the credit-file layer against
Fannie Mae's public historical credit-score distributions. Two independent problems rule
this out, not one:

1. **Access:** Fannie Mae's Data Dynamics platform was not programmatically fetchable from
   this environment.
2. **Redistribution:** even if access worked, Data Dynamics' Terms of Use prohibit
   redistributing the data to third parties — meaning a **committed, clonable fixture**
   could never be legally built from it for a public repository, independent of whether
   access was solved.

In its place, `profiles/calibration/fico_calibration.yaml` cites Experian's own published
FICO Score 8 distribution directly:

> National average FICO Score 713; band shares 14.7% (300–579), 14.9% (580–669), 20.1%
> (670–739), 27.5% (740–799), 22.8% (800–850) — summing to exactly 100.0%. Experian, "What
> Is the Average Credit Score in the U.S.?" (Ask Experian blog), data as of 2025-09, fetched
> 2026-08-10.

This is a **more complete** citation than originally planned: `docs/architecture.md`'s
Phase 3 plan anticipated only 4 confirmed numbers (average, one band, and two aggregate
cutoffs) and a coarser 4-band split for that reason. Live verification during
implementation found the source article publishes the full 5-band table directly, so all 5
bands are used as cited rather than approximated.

## 6. The credit file is one latent factor, not a fitted joint model

`profiles/creditfile.py` draws one `z ~ N(0,1)` per applicant and derives credit score,
tradeline count/age, revolving utilization, delinquency counts, inquiries, employment
tenure, and employment status as functions of `z` plus their own independently-seeded
noise. This is **not** a calibrated multivariate model fit to real credit-file data — no
such dataset was accessible or redistributable (§5) — so there is no claim of a correct
second-order correlation structure beyond what the shared `z` induces. The functional forms
(which Poisson rate falls how fast in `z`, which lognormal median scales how with `z`) are
our own modeling choices, tuned so every rule's natural breach rate falls inside
`policy.yaml`'s `calibration_targets` band, not fit to any external ground truth. Only
`credit_score`'s mapping from `z` is tied to a citation (§5); everything else in that module
is disclosed here as uncited by construction.

## 7. Analysis labels stay hidden; synthetic proxy signals are evaluated

Each Stage-A applicant's `Presentation.demographic_tags` carries the sampled HMDA cell's
race/ethnicity/sex/age-band labels (`source="hmda_sample"`). Those analysis labels are never
rendered and are never scored by the oracle.

Phase 6 separately evaluates provider-visible synthetic proxy signals using the committed,
hashed Census-surname and SSA-first-name catalog, plus pronouns and graduation year. Those
contrasts rotate templates deterministically and keep protected-class labels hidden. Their
results are proxy-signal invariance checks, not proof of discrimination and not estimates of
effects in the HMDA population; statistical inference remains Phase 7.

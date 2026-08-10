"""Stage A/B/C applicant-population generation.

Three stages, run in order by :mod:`credit_audit.profiles.generate`:

- **Stage A** (:func:`build_pool`): a pool of naturally-sampled applicants. Each draws an
  HMDA cell (weighted by real count) for income/DTI/demographics, an independent loan
  amount/term from the product's own cited distribution, and a credit file from
  :mod:`credit_audit.profiles.creditfile`. Every candidate is evaluated through the real
  Phase 1 oracle immediately -- HMDA's own outcome columns are never read.
- **Stage B** (:func:`construct_batch`): deliberately constructed applicants, built by
  applying 1-3 of :mod:`credit_audit.policy.boundary`'s setters to a clean Stage-A member,
  favoring cross-cluster breach combinations (the adversarial case: same-cluster co-breaches
  happen naturally, cross-cluster ones don't). Classification is always by the oracle's
  actual returned breach set, never by which setters were applied -- see boundary.py's own
  "setter order matters, intent is not truth" warning.
- **Stage C** (:func:`select_target_set`): stratified selection to a fixed breach-count
  bucket allocation, with a bounded audit-and-top-up loop that constructs more Stage B
  candidates (biased toward whichever rules are under- or over-represented) until every
  rule's breach rate sits inside policy.yaml's ``calibration_targets``. Raises loudly,
  rather than silently shipping an out-of-spec fixture, if the loop exhausts its budget.

**Exactness invariant this module depends on.** ``boundary.py``'s ratio setters
(``set_dti``, ``set_loan_to_income``, ``set_utilization``) require their ratio target times
the current denominator field to land on an exact integer number of cents. Every ratio rule
in this policy has a 2-decimal-place threshold/margin_unit, so it is sufficient -- and this
module arranges it -- for ``annual_income_cents`` to always be a multiple of $1,200 and
``revolving_limit_cents`` to always be a multiple of $100. If policy.yaml ever grows a
ratio rule with a finer margin_unit, this rounding needs to get finer too.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from credit_audit.ids import derive_seed
from credit_audit.policy.boundary import RULE_CLUSTERS, SETTERS
from credit_audit.policy.loader import YAML_PATH, Policy, PredicateKind, Rule, reject_floats
from credit_audit.policy.oracle import GroundTruthDecision, evaluate
from credit_audit.profiles.creditfile import draw_latent_z, load_fico_calibration, synthesize
from credit_audit.types import (
    Applicant,
    DecisionOutcome,
    DemographicTags,
    EmploymentStatus,
    FinancialFacts,
    Presentation,
    Provenance,
)

HMDA_TABLE_PATH = Path(__file__).parent / "hmda_tables" / "joint_marginals_2024.json"
LOAN_AMOUNT_PATH = Path(__file__).parent / "calibration" / "loan_amount_distribution.yaml"

# NY Fed Household Debt and Credit Report, Q4 2025: mortgage balances $13.17T of $18.80T
# total household debt -- https://www.newyorkfed.org/medialibrary/interactives/
# householdcredit/data/pdf/HHDC_2025Q4 (fetched 2026-08-10). A BALANCE-based, not
# payment-based, statistic -- the best available public proxy for "how much of a
# mortgage-holder's debt burden is the mortgage itself," not an exact match. Applied to
# HMDA's DTI bracket midpoint to estimate a personal-loan applicant's NON-mortgage debt
# burden. See docs/limitations.md.
NON_MORTGAGE_DEBT_SHARE = Decimal("0.30")

# Our own point-estimate midpoints for HMDA's DTI brackets (see
# scripts/build_hmda_tables.py's dti_bracket() normalization) -- not independently cited.
DTI_BRACKET_MIDPOINTS: dict[str, Decimal] = {
    "<20%": Decimal("0.15"),
    "20-30%": Decimal("0.25"),
    "30-36%": Decimal("0.33"),
    "36-42%": Decimal("0.39"),
    "43-49%": Decimal("0.46"),
    "50-60%": Decimal("0.55"),
    ">60%": Decimal("0.70"),
}

INCOME_ROUNDING_CENTS = 120_000
"""Round annual_income_cents to the nearest $1,200 -- see module docstring's exactness
invariant. Negligible next to HMDA's own $10k-wide income bins."""

INCOME_BIN_OPEN_TAIL_WIDTH_THOUSANDS = 100
"""The top income bin ("260+") is open-ended in the committed table; sampled uniformly in
[260k, 360k) dollars."""

LOAN_TERM_CHOICES = (12, 24, 36, 48, 60)
LOAN_TERM_WEIGHTS = (0.10, 0.20, 0.30, 0.25, 0.15)

DEFAULT_POOL_SIZE = 4000
DEFAULT_CONSTRUCTED_SIZE = 55
DEFAULT_TARGET_SIZE = 225
DEFAULT_BUCKET_ALLOCATION: dict[Any, int] = {0: 124, 1: 50, 2: 31, "3+": 20}
DEFAULT_TOPUP_BATCH_SIZE = 55
DEFAULT_MAX_TOPUP_BATCHES = 60


# --------------------------------------------------------------------------------------
# Committed-table loaders
# --------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_hmda_table() -> dict[str, Any]:
    return json.loads(HMDA_TABLE_PATH.read_text())


@lru_cache(maxsize=1)
def load_loan_amount_distribution() -> dict[str, Any]:
    raw = yaml.safe_load(LOAN_AMOUNT_PATH.read_text())
    reject_floats(raw)
    return raw


@lru_cache(maxsize=1)
def load_calibration_targets() -> dict[str, dict[str, Decimal]]:
    """``policy.yaml``'s ``calibration_targets`` block. Not exposed by
    :class:`credit_audit.policy.loader.Policy` (Phase 1 committed it for Phase 3 to read),
    so this reads the same committed YAML file directly."""
    raw = yaml.safe_load(YAML_PATH.read_text())
    reject_floats(raw)
    ct = raw["calibration_targets"]
    return {
        name: {"min": Decimal(bound["min"]), "max": Decimal(bound["max"])}
        for name, bound in ct.items()
    }


# --------------------------------------------------------------------------------------
# Stage A: natural pool
# --------------------------------------------------------------------------------------


def _parse_income_bin(label: str) -> tuple[int, int]:
    if label.endswith("+"):
        lo = int(label[:-1])
        return lo, lo + INCOME_BIN_OPEN_TAIL_WIDTH_THOUSANDS
    lo_s, hi_s = label.split("-")
    return int(lo_s), int(hi_s)


def _draw_hmda_cell(rng: np.random.Generator, cells: list[dict[str, Any]]) -> dict[str, Any]:
    weights = np.array([c["count"] for c in cells], dtype=float)
    weights /= weights.sum()
    index = int(rng.choice(len(cells), p=weights))
    return cells[index]


def _round_income_cents(raw_cents: float) -> int:
    return round(raw_cents / INCOME_ROUNDING_CENTS) * INCOME_ROUNDING_CENTS


def _draw_income_cents(rng: np.random.Generator, income_bin: str) -> int:
    lo_k, hi_k = _parse_income_bin(income_bin)
    dollars = rng.uniform(lo_k * 1000, hi_k * 1000)
    cents = max(_round_income_cents(dollars * 100), INCOME_ROUNDING_CENTS)
    return cents


def _monthly_debt_cents(dti_bracket: str, annual_income_cents: int) -> int:
    midpoint = DTI_BRACKET_MIDPOINTS[dti_bracket]
    non_mortgage_dti = midpoint * NON_MORTGAGE_DEBT_SHARE
    monthly_income_cents = annual_income_cents // 12
    return int((non_mortgage_dti * Decimal(monthly_income_cents)).to_integral_value())


def _draw_loan_amount_cents(rng: np.random.Generator, distribution: dict[str, Any]) -> int:
    dist = distribution["distribution"]
    median = int(dist["median_cents"])
    sigma = float(dist["sigma"])
    lo, hi = int(dist["min_cents"]), int(dist["max_cents"])
    draw = float(rng.lognormal(mean=math.log(median), sigma=sigma))
    return min(hi, max(lo, int(round(draw))))


def _draw_loan_term_months(rng: np.random.Generator) -> int:
    return int(rng.choice(LOAN_TERM_CHOICES, p=LOAN_TERM_WEIGHTS))


def _build_one_pool_applicant(
    run_seed: int, policy: Policy, applicant_id: str, cells: list[dict[str, Any]]
) -> tuple[Applicant, GroundTruthDecision]:
    cell = _draw_hmda_cell(
        np.random.default_rng(derive_seed(run_seed, applicant_id, "hmda_cell")), cells
    )
    annual_income_cents = _draw_income_cents(
        np.random.default_rng(derive_seed(run_seed, applicant_id, "income_within_bin")),
        cell["income_bin"],
    )
    monthly_debt_cents = _monthly_debt_cents(cell["dti_bracket"], annual_income_cents)

    loan_dist = load_loan_amount_distribution()
    loan_amount_cents = _draw_loan_amount_cents(
        np.random.default_rng(derive_seed(run_seed, applicant_id, "loan_amount")), loan_dist
    )
    loan_term_months = _draw_loan_term_months(
        np.random.default_rng(derive_seed(run_seed, applicant_id, "loan_term"))
    )

    z = draw_latent_z(run_seed, applicant_id)
    credit_fields = synthesize(
        run_seed,
        applicant_id,
        z,
        age_band=cell["age_band"],
        calibration=load_fico_calibration(),
    )

    facts = FinancialFacts(
        annual_income_cents=annual_income_cents,
        monthly_debt_cents=monthly_debt_cents,
        loan_amount_cents=loan_amount_cents,
        property_value_cents=0,
        loan_term_months=loan_term_months,
        **credit_fields,
    )

    source_cell_id = "|".join(
        [
            cell["income_bin"],
            cell["dti_bracket"],
            cell["race"],
            cell["ethnicity"],
            cell["sex"],
            cell["age_band"],
        ]
    )
    presentation = Presentation(
        applicant_name=f"Applicant {applicant_id}",
        employer_name="Employer Unspecified",
        employer_prestige_tier=3,
        demographic_tags=DemographicTags(
            race_ethnicity_signal=f"{cell['race']}|{cell['ethnicity']}",
            sex_signal=cell["sex"],
            age_band_signal=cell["age_band"],
            source="hmda_sample",
        ),
    )
    provenance = Provenance(
        generator_seed=run_seed, generator_version="phase3-v1", source_cell_id=source_cell_id
    )
    applicant = Applicant(
        applicant_id=applicant_id, facts=facts, presentation=presentation, provenance=provenance
    )
    decision = evaluate(applicant.facts, policy)
    return applicant, decision


def build_pool(
    run_seed: int, policy: Policy, pool_size: int = DEFAULT_POOL_SIZE
) -> list[tuple[Applicant, GroundTruthDecision]]:
    hmda = load_hmda_table()
    cells = hmda["cells"]
    return [
        _build_one_pool_applicant(run_seed, policy, f"APP-A-{i:05d}", cells)
        for i in range(pool_size)
    ]


# --------------------------------------------------------------------------------------
# Stage B: deliberate cross-cluster construction
# --------------------------------------------------------------------------------------

_DISALLOWED_EMPLOYMENT_STATUSES = tuple(
    s.value
    for s in EmploymentStatus
    if s.value not in {"FULL_TIME", "PART_TIME", "SELF_EMPLOYED", "RETIRED"}
)


def _breaching_target(rng: np.random.Generator, rule: Rule) -> Decimal | bool | str:
    if rule.predicate is PredicateKind.FLAG_TRUE:
        return False
    if rule.predicate is PredicateKind.ENUM_ALLOWED:
        options = _DISALLOWED_EMPLOYMENT_STATUSES
        return str(options[int(rng.integers(0, len(options)))])
    if rule.predicate is PredicateKind.NUMERIC_MIN:
        assert rule.threshold is not None
        target = rule.threshold - 3 * rule.margin_unit
        if rule.rule_id == "min_annual_income":
            target = Decimal((int(target) // INCOME_ROUNDING_CENTS) * INCOME_ROUNDING_CENTS)
        return max(target, Decimal(0))
    if rule.predicate is PredicateKind.NUMERIC_MAX:
        assert rule.threshold is not None
        return rule.threshold + 3 * rule.margin_unit
    raise AssertionError(f"unhandled predicate: {rule.predicate}")  # pragma: no cover


def _choose_rule_ids(
    rng: np.random.Generator, n_setters: int, force_rule_id: str | None
) -> list[str]:
    all_rule_ids = sorted(SETTERS.keys())
    if force_rule_id is not None:
        rule_ids = [force_rule_id]
        remaining = n_setters - 1
        if remaining <= 0:
            return rule_ids
        forced_cluster = next(
            (name for name, members in RULE_CLUSTERS.items() if force_rule_id in members), None
        )
        cluster_names = [c for c in RULE_CLUSTERS if c != forced_cluster]
    else:
        rule_ids = []
        remaining = n_setters
        cluster_names = list(RULE_CLUSTERS.keys())

    cluster_order = list(cluster_names)
    perm = rng.permutation(len(cluster_order))
    cluster_order = [cluster_order[i] for i in perm]

    for cluster in cluster_order[:remaining]:
        candidates = [r for r in RULE_CLUSTERS[cluster] if r in SETTERS and r not in rule_ids]
        if not candidates:
            continue
        rule_ids.append(candidates[int(rng.integers(0, len(candidates)))])

    # Fallback if clusters ran out of fresh candidates before reaching n_setters (never
    # happens with this policy's 16 rules across 4 clusters for n_setters<=3, but stay
    # correct rather than silently short).
    while len(rule_ids) < n_setters:
        remaining_pool = [r for r in all_rule_ids if r not in rule_ids]
        if not remaining_pool:
            break
        rule_ids.append(remaining_pool[int(rng.integers(0, len(remaining_pool)))])

    return rule_ids


def _construct_one(
    run_seed: int,
    policy: Policy,
    base: Applicant,
    seed_id: str,
    *,
    force_rule_id: str | None = None,
) -> tuple[Applicant, GroundTruthDecision]:
    plan_rng = np.random.default_rng(derive_seed(run_seed, seed_id, "stage_b_plan"))
    n_setters = int(plan_rng.integers(1, 4))
    rule_ids = _choose_rule_ids(plan_rng, n_setters, force_rule_id)

    facts = base.facts
    for rule_id in rule_ids:
        rule = policy.rule(rule_id)
        target_rng = np.random.default_rng(derive_seed(run_seed, seed_id, "target", rule_id))
        target = _breaching_target(target_rng, rule)
        facts = SETTERS[rule_id](facts, target)

    applicant = base.model_copy(
        update={
            "applicant_id": seed_id,
            "facts": facts,
            "presentation": base.presentation.model_copy(
                update={"applicant_name": f"Applicant {seed_id}"}
            ),
            "provenance": Provenance(
                generator_seed=run_seed,
                generator_version="phase3-v1",
                source_cell_id=base.provenance.source_cell_id,
                parent_applicant_id=base.applicant_id,
                intervention_lineage=tuple(f"boundary_setter:{rid}" for rid in rule_ids),
            ),
        }
    )
    decision = evaluate(applicant.facts, policy)
    return applicant, decision


def construct_batch(
    run_seed: int,
    policy: Policy,
    clean_bases: list[Applicant],
    *,
    batch_id: str,
    n: int = DEFAULT_CONSTRUCTED_SIZE,
    force_rule_id: str | None = None,
) -> list[tuple[Applicant, GroundTruthDecision]]:
    """Build ``n`` Stage-B candidates from a pool of already-clean Stage-A bases.

    ``force_rule_id``, when set, guarantees every candidate in this batch breaches that
    specific rule (used by Stage C's top-up loop to fix an under-represented rule) --
    still classified afterward by the oracle's real breach set, never by this intent.
    """
    results = []
    for i in range(n):
        seed_id = f"APP-B-{batch_id}-{i:05d}"
        base_rng = np.random.default_rng(derive_seed(run_seed, seed_id, "stage_b_base"))
        base = clean_bases[int(base_rng.integers(0, len(clean_bases)))]
        results.append(_construct_one(run_seed, policy, base, seed_id, force_rule_id=force_rule_id))
    return results


# --------------------------------------------------------------------------------------
# Stage C: stratified selection + audit/top-up
# --------------------------------------------------------------------------------------


def _breach_bucket(decision: GroundTruthDecision) -> Any:
    n = len(decision.breached)
    return n if n < 3 else "3+"


def select_target_set(
    run_seed: int,
    policy: Policy,
    pool: list[tuple[Applicant, GroundTruthDecision]],
    *,
    target_size: int = DEFAULT_TARGET_SIZE,
    bucket_allocation: dict[Any, int] | None = None,
    topup_batch_size: int = DEFAULT_TOPUP_BATCH_SIZE,
    max_topup_batches: int = DEFAULT_MAX_TOPUP_BATCHES,
) -> list[tuple[Applicant, GroundTruthDecision]]:
    bucket_allocation = bucket_allocation or DEFAULT_BUCKET_ALLOCATION
    if sum(bucket_allocation.values()) != target_size:
        raise ValueError("bucket_allocation must sum to target_size")

    calibration_targets = load_calibration_targets()
    dr_bounds = calibration_targets["overall_deny_rate"]
    pr_bounds = calibration_targets["per_rule_breach_rate"]
    rule_ids = [r.rule_id for r in policy.rules]

    candidates: dict[str, tuple[Applicant, GroundTruthDecision]] = {
        a.applicant_id: (a, d) for a, d in pool
    }
    clean_bases = [a for a, d in pool if not d.breached]
    if not clean_bases:
        raise RuntimeError("Stage A produced no fully-compliant applicant to build Stage B from")

    batch = 0
    while True:
        buckets: dict[Any, list[str]] = {k: [] for k in bucket_allocation}
        for aid, (_a, d) in candidates.items():
            key = _breach_bucket(d)
            if key in buckets:
                buckets[key].append(aid)

        selected_ids: list[str] = []
        shortfall: dict[Any, int] = {}
        for key, need in bucket_allocation.items():
            avail = sorted(buckets[key])
            rng = np.random.default_rng(derive_seed(run_seed, "stage_c_bucket", str(key), batch))
            order = rng.permutation(len(avail))
            avail = [avail[i] for i in order]
            chosen = avail[:need]
            selected_ids.extend(chosen)
            if len(chosen) < need:
                shortfall[key] = need - len(chosen)

        selected_ids.sort()
        selected = [candidates[aid] for aid in selected_ids]
        n_selected = len(selected)

        deficient_rules: list[str] = []
        excess_rules: list[str] = []
        deny_rate = None
        if n_selected == target_size and not shortfall:
            deny_rate = (
                Decimal(sum(1 for _, d in selected if d.outcome is DecisionOutcome.DENY))
                / target_size
            )
            for rid in rule_ids:
                rate = (
                    Decimal(sum(1 for _, d in selected if rid in d.breached_rule_ids)) / target_size
                )
                if rate < pr_bounds["min"]:
                    deficient_rules.append(rid)
                elif rate > pr_bounds["max"]:
                    excess_rules.append(rid)

        deny_ok = deny_rate is not None and dr_bounds["min"] <= deny_rate <= dr_bounds["max"]
        if (
            n_selected == target_size
            and not shortfall
            and deny_ok
            and not deficient_rules
            and not excess_rules
        ):
            return selected

        batch += 1
        if batch > max_topup_batches:
            raise RuntimeError(
                "Stage C exhausted its top-up budget "
                f"({max_topup_batches} batches) without satisfying calibration_targets. "
                f"shortfall={shortfall} deny_rate={deny_rate} "
                f"deficient_rules={deficient_rules} excess_rules={excess_rules}"
            )

        batch_id = f"topup{batch:03d}"
        if deficient_rules:
            # Spread this batch across the deficient rules so each gets deliberately
            # boosted, rather than spending the whole batch on just one.
            per_rule = max(1, topup_batch_size // max(len(deficient_rules), 1))
            new_candidates: list[tuple[Applicant, GroundTruthDecision]] = []
            for j, rid in enumerate(deficient_rules):
                new_candidates.extend(
                    construct_batch(
                        run_seed,
                        policy,
                        clean_bases,
                        batch_id=f"{batch_id}-{j}",
                        n=per_rule,
                        force_rule_id=rid,
                    )
                )
        else:
            new_candidates = construct_batch(
                run_seed, policy, clean_bases, batch_id=batch_id, n=topup_batch_size
            )
        for a, d in new_candidates:
            candidates[a.applicant_id] = (a, d)


__all__ = [
    "DEFAULT_BUCKET_ALLOCATION",
    "DEFAULT_CONSTRUCTED_SIZE",
    "DEFAULT_POOL_SIZE",
    "DEFAULT_TARGET_SIZE",
    "build_pool",
    "construct_batch",
    "load_calibration_targets",
    "load_hmda_table",
    "load_loan_amount_distribution",
    "select_target_set",
]

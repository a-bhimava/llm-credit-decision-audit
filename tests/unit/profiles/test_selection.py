"""Stage A/B/C mechanics: committed-table loading, the income-rounding exactness
invariant, Stage B's cross-cluster construction, and Stage C's bucket/calibration audit."""

from __future__ import annotations

from decimal import Decimal

from credit_audit.policy.boundary import RULE_CLUSTERS
from credit_audit.policy.loader import load_policy
from credit_audit.profiles.selection import (
    CALIBRATION_SAFETY_MARGIN,
    DEFAULT_BUCKET_ALLOCATION,
    INCOME_ROUNDING_CENTS,
    build_pool,
    construct_batch,
    load_calibration_targets,
    load_hmda_table,
    load_loan_amount_distribution,
    select_target_set,
)


def test_hmda_table_loads_and_has_cells():
    table = load_hmda_table()
    assert table["distinct_cells"] == len(table["cells"])
    assert table["rows_kept"] > 100_000
    assert all(c["count"] >= table["min_cell_count"] for c in table["cells"])


def test_loan_amount_distribution_loads():
    dist = load_loan_amount_distribution()
    assert dist["distribution"]["kind"] == "lognormal"


def test_pool_incomes_are_rounded_for_setter_exactness():
    """boundary.py's set_dti/set_loan_to_income need annual_income_cents to be a multiple
    of $1,200 for their exact-integer-cents assertion to hold against any Stage-B target
    -- see selection.py's module docstring."""
    policy = load_policy()
    pool = build_pool(run_seed=1, policy=policy, pool_size=50)
    for applicant, _decision in pool:
        assert applicant.facts.annual_income_cents % INCOME_ROUNDING_CENTS == 0


def test_pool_is_deterministic():
    policy = load_policy()
    pool1 = build_pool(run_seed=5, policy=policy, pool_size=30)
    pool2 = build_pool(run_seed=5, policy=policy, pool_size=30)
    assert [a.applicant_id for a, _ in pool1] == [a.applicant_id for a, _ in pool2]
    assert [a.facts for a, _ in pool1] == [a.facts for a, _ in pool2]


def test_construct_batch_with_forced_rule_actually_breaches_it():
    """Classification is always the oracle's real breach set -- force_rule_id only picks
    which setter is applied, and this test verifies the applied setter actually produced
    the intended breach for every rule in one cluster."""
    policy = load_policy()
    pool = build_pool(run_seed=9, policy=policy, pool_size=500)
    clean_bases = [a for a, d in pool if not d.breached]
    assert clean_bases

    for rule_id in RULE_CLUSTERS["credit_quality"]:
        batch = construct_batch(
            run_seed=9,
            policy=policy,
            clean_bases=clean_bases,
            batch_id=f"t-{rule_id}",
            n=5,
            force_rule_id=rule_id,
        )
        assert all(rule_id in d.breached_rule_ids for _a, d in batch)


def test_construct_batch_spans_clusters_not_just_one():
    """The adversarial, laundering-relevant case: some multi-setter constructions must
    breach rules from more than one RULE_CLUSTERS cluster, not just co-breach within one
    cluster (which happens naturally and isn't the interesting case)."""
    policy = load_policy()
    pool = build_pool(run_seed=17, policy=policy, pool_size=500)
    clean_bases = [a for a, d in pool if not d.breached]

    def cluster_of(rule_id: str) -> str | None:
        for name, members in RULE_CLUSTERS.items():
            if rule_id in members:
                return name
        return None

    batch = construct_batch(
        run_seed=17, policy=policy, clean_bases=clean_bases, batch_id="span", n=200
    )
    saw_cross_cluster = any(
        len({cluster_of(rid) for rid in d.breached_rule_ids} - {None}) >= 2 for _a, d in batch
    )
    assert saw_cross_cluster


def test_select_target_set_matches_bucket_allocation():
    policy = load_policy()
    pool = build_pool(run_seed=42, policy=policy, pool_size=4000)
    selected = select_target_set(run_seed=42, policy=policy, pool=pool, target_size=225)
    assert len(selected) == 225

    buckets = dict.fromkeys(DEFAULT_BUCKET_ALLOCATION, 0)
    for _a, d in selected:
        n = len(d.breached)
        buckets[n if n < 3 else "3+"] += 1
    assert buckets == DEFAULT_BUCKET_ALLOCATION


def test_select_target_set_corrects_an_engineered_excess_rule():
    """F13: an over-represented rule used to have no correction mechanism -- the top-up
    loop only ever added candidates for a *deficient* rule. Here the candidate pool is
    deliberately flooded with forced max_inquiries_6m breaches (a naturally rare one) far
    beyond what Stage A alone would ever produce; select_target_set must still land the
    final selection's rate for that rule inside the margin-adjusted ceiling, not just
    reflect whatever oversupply happened to be sitting in the pool."""
    policy = load_policy()
    natural_pool = build_pool(run_seed=99, policy=policy, pool_size=800)
    clean_bases = [a for a, d in natural_pool if not d.breached]

    flooded = construct_batch(
        run_seed=99,
        policy=policy,
        clean_bases=clean_bases,
        batch_id="flood",
        n=300,
        force_rule_id="max_inquiries_6m",
    )
    combined_pool = natural_pool + flooded

    selected = select_target_set(run_seed=99, policy=policy, pool=combined_pool, target_size=225)
    assert len(selected) == 225

    pr = load_calibration_targets()["per_rule_breach_rate"]
    rate = Decimal(sum(1 for _a, d in selected if "max_inquiries_6m" in d.breached_rule_ids)) / len(
        selected
    )
    assert rate <= pr["max"] - CALIBRATION_SAFETY_MARGIN, (
        f"max_inquiries_6m rate {rate} was not corrected despite an engineered oversupply "
        f"of {len(flooded)} forced-breach candidates in the pool"
    )

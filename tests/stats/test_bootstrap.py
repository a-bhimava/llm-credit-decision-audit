"""Cluster bootstrap: the ratio estimator, the disclosed fallback, and the empty cases."""

from __future__ import annotations

import pytest

from credit_audit.stats.bootstrap import (
    cluster_bootstrap_proportion_ci,
    cluster_bootstrap_ratio_ci,
)

B = 2_000
SEED = 1729


def test_point_estimate_is_the_pooled_ratio_not_the_mean_of_ratios():
    """Two clusters of very different size: pooling must not weight them equally.

    Cluster `big` contributes 1 success in 100; cluster `small` contributes 1 in 2. The
    pooled rate is 2/102; the mean of per-cluster rates would be 0.255, an order of
    magnitude higher, purely because one cluster ran fewer trials.
    """

    interval = cluster_bootstrap_ratio_ci(
        [1.0, 1.0],
        [100.0, 2.0],
        ["big", "small"],
        seed=SEED,
        B=B,
    )
    assert interval.point == pytest.approx(2 / 102)


def test_proportion_recovers_the_observed_rate_and_covers_it():
    successes = [i % 4 == 0 for i in range(200)]
    interval = cluster_bootstrap_proportion_ci(
        successes, [f"c{i % 25}" for i in range(200)], seed=SEED, B=B
    )
    assert interval.point == pytest.approx(0.25)
    assert interval.lower <= 0.25 <= interval.upper
    assert interval.n_observations == 200
    assert interval.n_clusters == 25
    assert interval.cluster == "cluster_id"


def test_interval_is_clipped_to_the_parameter_space():
    successes = [i % 20 == 0 for i in range(200)]
    interval = cluster_bootstrap_proportion_ci(
        successes, [f"c{i % 25}" for i in range(200)], seed=SEED, B=B
    )
    assert interval.lower >= 0.0
    assert interval.upper <= 1.0


def test_a_deterministic_control_falls_back_to_percentile_and_says_so():
    """Every cluster identical is the normal state for a scripted known-answer agent.

    BCa's bias correction is undefined when no bootstrap replicate falls below the observed
    statistic. The interval must degrade to percentile and flag it, never report a BCa
    interval it did not compute.
    """

    interval = cluster_bootstrap_proportion_ci(
        [True] * 60, [f"c{i % 12}" for i in range(60)], seed=SEED, B=B
    )
    assert interval.point == 1.0
    assert interval.method == "percentile"
    assert interval.fallback_used is True
    assert interval.degenerate is True
    assert interval.ci95 == (1.0, 1.0)
    assert interval.z0 is None and interval.a is None


def test_bca_reports_its_correction_terms_when_it_does_run():
    successes = [i % 3 == 0 for i in range(300)]
    interval = cluster_bootstrap_proportion_ci(
        successes, [f"c{i % 30}" for i in range(300)], seed=SEED, B=B
    )
    assert interval.method == "BCa"
    assert interval.fallback_used is False
    assert interval.z0 is not None
    assert interval.a is not None


def test_no_evidence_yields_a_null_interval_rather_than_a_measured_zero():
    interval = cluster_bootstrap_ratio_ci([], [], [], seed=SEED, B=B)
    assert interval.point == 0.0
    assert interval.ci95 is None
    assert interval.method == "none"
    assert interval.n_clusters == 0


def test_a_single_cluster_gets_no_interval():
    """One source applicant is one experimental unit; there is nothing to resample."""

    interval = cluster_bootstrap_proportion_ci([True, False, True], ["c0"] * 3, seed=SEED, B=B)
    assert interval.point == pytest.approx(2 / 3)
    assert interval.ci95 is None
    assert interval.method == "none"
    assert interval.n_clusters == 1


def test_result_is_deterministic_for_a_fixed_seed():
    args = ([i % 5 == 0 for i in range(150)], [f"c{i % 15}" for i in range(150)])
    first = cluster_bootstrap_proportion_ci(*args, seed=SEED, B=B)
    second = cluster_bootstrap_proportion_ci(*args, seed=SEED, B=B)
    assert first.ci95 == second.ci95


def test_result_does_not_depend_on_the_order_observations_arrive_in():
    """Cluster aggregation is sorted, so shuffling the input cannot move the interval."""

    successes = [i % 3 == 0 for i in range(120)]
    clusters = [f"c{i % 12}" for i in range(120)]
    forward = cluster_bootstrap_proportion_ci(successes, clusters, seed=SEED, B=B)
    reversed_ = cluster_bootstrap_proportion_ci(
        list(reversed(successes)), list(reversed(clusters)), seed=SEED, B=B
    )
    assert forward.point == pytest.approx(reversed_.point)
    assert forward.ci95 == pytest.approx(reversed_.ci95)


def test_mismatched_input_lengths_are_rejected():
    with pytest.raises(ValueError, match="same length"):
        cluster_bootstrap_ratio_ci([1.0], [1.0, 1.0], ["a", "b"], seed=SEED, B=B)


def test_negative_weights_are_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        cluster_bootstrap_ratio_ci([1.0], [-1.0], ["a"], seed=SEED, B=B)


def test_invalid_alpha_and_b_are_rejected():
    with pytest.raises(ValueError, match="alpha must lie"):
        cluster_bootstrap_ratio_ci([1.0], [1.0], ["a"], seed=SEED, alpha=0.0, B=B)
    with pytest.raises(ValueError, match="B must be positive"):
        cluster_bootstrap_ratio_ci([1.0], [1.0], ["a"], seed=SEED, B=0)

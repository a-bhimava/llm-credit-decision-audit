"""pass^k: the unbiased estimator, and why the plug-in one was not used."""

from __future__ import annotations

import pytest

from credit_audit.stats.passk import TrialCounts, pass_k_estimate

SEED = 1729
B = 2_000


def _units(spec: list[tuple[int, int]], *, clusters: int = 10) -> list[TrialCounts]:
    return [
        TrialCounts(
            unit_id=f"u{i}", cluster_id=f"c{i % clusters}", n_trials=n_trials, n_pass=n_pass
        )
        for i, (n_trials, n_pass) in enumerate(spec)
    ]


def test_perfect_units_give_pass_k_of_one():
    estimate = pass_k_estimate(_units([(5, 5)] * 40), check="x", k=5, stratum="s", seed=SEED, B=B)
    assert estimate.pass_k == 1.0
    assert estimate.pass_1 == 1.0
    assert estimate.n == 40


def test_a_single_failure_in_k_trials_zeroes_that_unit():
    """All-of-k is the estimand. Four passes out of five is a fail for this unit."""

    unit = TrialCounts(unit_id="u", cluster_id="c", n_trials=5, n_pass=4)
    assert unit.unbiased_pass_k(5) == 0.0
    assert unit.unbiased_pass_k(4) == pytest.approx(1 / 5)


def test_estimator_is_the_combinatorial_ratio_not_the_plug_in_power():
    """C(8, 5) / C(10, 5) = 56/252, well below (8/10)**5 = 0.328.

    The plug-in estimator is biased upward at small n, which is the regime this harness
    runs in, so the difference is not academic.
    """

    unit = TrialCounts(unit_id="u", cluster_id="c", n_trials=10, n_pass=8)
    assert unit.unbiased_pass_k(5) == pytest.approx(56 / 252)
    assert unit.unbiased_pass_k(5) < (8 / 10) ** 5


def test_pass_k_never_exceeds_pass_1():
    estimate = pass_k_estimate(
        _units([(5, 4)] * 20 + [(5, 5)] * 20), check="x", k=5, stratum="s", seed=SEED, B=B
    )
    assert estimate.pass_1 is not None and estimate.pass_k is not None
    assert estimate.pass_k <= estimate.pass_1
    assert estimate.pass_k == pytest.approx(0.5)


def test_units_with_too_few_trials_are_excluded_and_disclosed():
    estimate = pass_k_estimate(
        _units([(5, 5)] * 10 + [(3, 3)] * 4), check="x", k=5, stratum="s", seed=SEED, B=B
    )
    assert estimate.n == 10
    assert estimate.n_excluded == 4


def test_pass_1_shares_the_denominator_with_pass_k():
    """Both rates are computed on the eligible units, so the gap between them is real.

    The excluded unit here passes every trial it ran. If pass_1 were pooled over all units
    it would be dragged upward by a unit that pass_k could not score at all.
    """

    estimate = pass_k_estimate(
        _units([(5, 3)] * 4 + [(2, 2)]), check="x", k=5, stratum="s", seed=SEED, B=B
    )
    assert estimate.pass_1 == pytest.approx(12 / 20)
    assert estimate.n == 4
    assert estimate.n_excluded == 1


def test_no_eligible_units_reports_null_rather_than_zero():
    estimate = pass_k_estimate(_units([(2, 2)] * 5), check="x", k=5, stratum="s", seed=SEED, B=B)
    assert estimate.n == 0
    assert estimate.pass_k is None
    assert estimate.pass_1 is None


def test_interval_resamples_clusters_not_units():
    estimate = pass_k_estimate(
        _units([(5, 5)] * 20 + [(5, 2)] * 20, clusters=8),
        check="x",
        k=5,
        stratum="s",
        seed=SEED,
        B=B,
    )
    assert estimate.n_clusters == 8
    assert estimate.ci95 is not None
    assert estimate.ci95[0] <= estimate.pass_k <= estimate.ci95[1]


def test_a_unit_cannot_pass_more_trials_than_it_ran():
    with pytest.raises(ValueError, match="passed more trials than it ran"):
        TrialCounts(unit_id="u", cluster_id="c", n_trials=3, n_pass=4)


def test_k_must_be_at_least_one():
    with pytest.raises(ValueError, match="k must be at least 1"):
        pass_k_estimate(_units([(5, 5)]), check="x", k=0, stratum="s", seed=SEED, B=B)

"""Simulation-based calibration -- the Phase 7 exit criterion.

Every other test in this directory checks that a function computes what its docstring says.
These check something harder and more important: that the procedures have the frequentist
properties they are being sold on. Under a known null, does the exact test reject at most
alpha of the time? Does BH actually hold the false-discovery rate at q? Does a 95% clustered
interval actually contain the truth about 95% of the time?

This is the answer to the first question a statistically literate reviewer asks, and it is
answered by simulation rather than by citation because the implementation, not the textbook,
is what ships.

Every simulation is seeded, so these tests are deterministic despite being Monte Carlo. The
tolerances are set to absorb the Monte Carlo error at the sample sizes used here, not to make
a marginal implementation pass.
"""

from __future__ import annotations

import numpy as np
import pytest

from credit_audit.stats.bootstrap import cluster_bootstrap_proportion_ci
from credit_audit.stats.fdr import benjamini_hochberg
from credit_audit.stats.mcnemar import mcnemar_exact

pytestmark = pytest.mark.slow

SEED = 1729


# --------------------------------------------------------------------------------------
# McNemar under the null
# --------------------------------------------------------------------------------------


def _null_mcnemar_p_values(
    *, n_runs: int, n_pairs: int, discordance: float, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate exchangeable paired data: each discordant pair flips either way at 50/50."""

    rng = np.random.default_rng(seed)
    n_discordant = rng.binomial(n_pairs, discordance, size=n_runs)
    b = rng.binomial(n_discordant, 0.5)
    c = n_discordant - b
    exact = np.empty(n_runs)
    mid = np.empty(n_runs)
    for i in range(n_runs):
        result = mcnemar_exact(int(b[i]), int(c[i]), n_pairs=n_pairs)
        exact[i] = result.p_exact
        mid[i] = result.p_mid
    return exact, mid


@pytest.mark.parametrize("alpha", [0.01, 0.05, 0.10])
def test_exact_p_values_never_reject_more_than_alpha_under_the_null(alpha):
    """Validity, which is the property BH depends on.

    On a discrete statistic no test attains the nominal level exactly; the guarantee is
    ``P(p <= alpha) <= alpha``. Being conservative is acceptable and expected. Being liberal
    is not: it would make every q-value downstream optimistic.
    """

    exact, _ = _null_mcnemar_p_values(n_runs=4000, n_pairs=120, discordance=0.25, seed=SEED)
    rejection_rate = float(np.mean(exact <= alpha))
    assert rejection_rate <= alpha + 0.005, f"size {rejection_rate:.4f} exceeds alpha {alpha}"


def test_exact_p_values_are_super_uniform_across_the_whole_range():
    """The full statement of validity: the CDF sits at or below the uniform CDF everywhere."""

    exact, _ = _null_mcnemar_p_values(n_runs=4000, n_pairs=120, discordance=0.25, seed=SEED + 1)
    for threshold in np.linspace(0.05, 0.95, 19):
        empirical = float(np.mean(exact <= threshold))
        assert empirical <= threshold + 0.02, f"P(p <= {threshold:.2f}) = {empirical:.3f}"


def test_mid_p_is_approximately_uniform_under_the_null():
    """The calibration diagnostic: mid-p removes the discreteness the exact test carries.

    This is why the mid-p value is reported alongside the exact one -- a calibration plot
    drawn from exact p-values on a discrete statistic looks broken when it is merely
    conservative. Mid-p is deliberately not what BH consumes.
    """

    _, mid = _null_mcnemar_p_values(n_runs=4000, n_pairs=120, discordance=0.25, seed=SEED + 2)
    assert 0.47 <= float(np.mean(mid)) <= 0.53
    assert 0.03 <= float(np.mean(mid <= 0.05)) <= 0.07


def test_the_test_has_power_against_a_real_asymmetry():
    """Guards against the trivially valid test that never rejects anything."""

    rng = np.random.default_rng(SEED + 3)
    n_pairs = 120
    n_discordant = rng.binomial(n_pairs, 0.25, size=1000)
    b = rng.binomial(n_discordant, 0.8)
    c = n_discordant - b
    rejections = sum(
        mcnemar_exact(int(b[i]), int(c[i]), n_pairs=n_pairs).p_exact <= 0.05 for i in range(1000)
    )
    assert rejections / 1000 > 0.90


# --------------------------------------------------------------------------------------
# Benjamini-Hochberg
# --------------------------------------------------------------------------------------


def test_bh_holds_the_false_discovery_rate_at_q_over_1000_simulated_runs():
    """The headline multiplicity claim, simulated rather than asserted.

    Each run is a family of 20 hypotheses: 15 true nulls with uniform p-values and 5 real
    effects. The false-discovery proportion is averaged over the runs, counting a run with
    no rejections as zero, which is the standard FDR definition.
    """

    rng = np.random.default_rng(SEED + 4)
    n_runs = 1000
    n_null = 15
    n_effect = 5
    q = 0.05

    false_discovery_proportions = []
    rejected_effects = 0
    for _ in range(n_runs):
        null_p = rng.uniform(size=n_null)
        effect_p = rng.beta(0.1, 8.0, size=n_effect)
        p_values = list(null_p) + list(effect_p)
        q_values = benjamini_hochberg(p_values, q=q)
        rejected = [value <= q for value in q_values]
        total = sum(rejected)
        false_positives = sum(rejected[:n_null])
        false_discovery_proportions.append(false_positives / total if total else 0.0)
        rejected_effects += sum(rejected[n_null:])

    fdr = float(np.mean(false_discovery_proportions))
    assert fdr <= q, f"empirical FDR {fdr:.4f} exceeds q {q}"
    # Not vacuous: the procedure must still find the planted effects.
    assert rejected_effects / (n_runs * n_effect) > 0.5


def test_bh_under_all_nulls_rejects_almost_nothing():
    rng = np.random.default_rng(SEED + 5)
    q = 0.05
    any_rejection = 0
    for _ in range(1000):
        q_values = benjamini_hochberg(list(rng.uniform(size=20)), q=q)
        any_rejection += any(value <= q for value in q_values)
    assert any_rejection / 1000 <= q + 0.02


# --------------------------------------------------------------------------------------
# Clustered bootstrap
# --------------------------------------------------------------------------------------


def _clustered_binary_sample(
    rng: np.random.Generator,
    *,
    n_clusters: int,
    per_cluster: int,
    mean: float,
    concentration: float,
) -> tuple[list[bool], list[str]]:
    """Beta-binomial clustered data.

    ``concentration`` controls how much the per-cluster rate varies around ``mean``: a small
    value means strongly correlated observations inside a cluster, which is exactly the
    dependence a source applicant induces across its sibling variants and repeated trials.
    """

    alpha = mean * concentration
    beta = (1.0 - mean) * concentration
    cluster_rates = rng.beta(alpha, beta, size=n_clusters)
    successes: list[bool] = []
    clusters: list[str] = []
    for index, rate in enumerate(cluster_rates):
        draws = rng.random(per_cluster) < rate
        successes.extend(bool(value) for value in draws)
        clusters.extend([f"c{index}"] * per_cluster)
    return successes, clusters


def test_clustered_intervals_cover_the_truth_about_95_percent_of_the_time():
    """Coverage, the property a confidence interval is named after."""

    rng = np.random.default_rng(SEED + 6)
    truth = 0.30
    covered = 0
    n_datasets = 400
    for index in range(n_datasets):
        successes, clusters = _clustered_binary_sample(
            rng, n_clusters=40, per_cluster=10, mean=truth, concentration=8.0
        )
        interval = cluster_bootstrap_proportion_ci(successes, clusters, seed=SEED + index, B=999)
        if interval.ci95 is not None and interval.lower <= truth <= interval.upper:
            covered += 1
    coverage = covered / n_datasets
    assert 0.90 <= coverage <= 0.99, f"coverage {coverage:.3f} is not near the nominal 0.95"


def test_clustered_resampling_gives_wider_intervals_than_response_level_resampling():
    """The anti-simplification guard the roadmap asks for by name.

    Resampling responses independently treats k correlated trials from one source applicant
    as k independent pieces of evidence. On clustered data that understates the standard
    error, so the response-level interval comes out narrower -- and narrower is the direction
    that makes a finding look stronger than the design supports. If someone later "simplifies"
    the clustering away, this test fails loudly rather than quietly shrinking every published
    interval.

    Both intervals come from the same function on the same data. Only the resampling unit
    changes: real cluster labels, versus one synthetic cluster per observation.
    """

    rng = np.random.default_rng(SEED + 7)
    wider = 0
    ratios: list[float] = []
    n_datasets = 60
    for index in range(n_datasets):
        successes, clusters = _clustered_binary_sample(
            rng, n_clusters=25, per_cluster=12, mean=0.4, concentration=2.0
        )
        clustered = cluster_bootstrap_proportion_ci(successes, clusters, seed=SEED + index, B=999)
        response_level = cluster_bootstrap_proportion_ci(
            successes,
            [f"r{position}" for position in range(len(successes))],
            seed=SEED + index,
            B=999,
        )
        assert clustered.point == pytest.approx(response_level.point)
        assert clustered.n_clusters == 25
        assert response_level.n_clusters == len(successes)
        if clustered.width is not None and response_level.width is not None:
            wider += clustered.width > response_level.width
            ratios.append(clustered.width / response_level.width)

    assert wider >= int(0.95 * n_datasets), f"clustered was wider in only {wider}/{n_datasets}"
    assert float(np.mean(ratios)) > 1.5, f"mean width ratio {np.mean(ratios):.2f} is too small"


def test_independent_data_does_not_penalize_the_clustered_interval():
    """With no intra-cluster correlation the two units agree, so clustering costs nothing.

    This is the other half of the previous test: the clustered interval is wider *because
    the data are dependent*, not because the estimator is uniformly inflated.
    """

    rng = np.random.default_rng(SEED + 8)
    ratios: list[float] = []
    for index in range(30):
        successes = [bool(value) for value in rng.random(300) < 0.4]
        clustered = cluster_bootstrap_proportion_ci(
            successes, [f"c{position % 25}" for position in range(300)], seed=SEED + index, B=999
        )
        response_level = cluster_bootstrap_proportion_ci(
            successes,
            [f"r{position}" for position in range(300)],
            seed=SEED + index,
            B=999,
        )
        if clustered.width and response_level.width:
            ratios.append(clustered.width / response_level.width)
    assert 0.85 <= float(np.mean(ratios)) <= 1.20

"""Cluster-level bootstrap confidence intervals.

**The resampling unit is the originating source applicant (``cluster_id``), never the pair
and never the individual response.** One source applicant produces sibling profile variants,
several contrasts, and k repeated trials of each. Those observations are dependent by
construction: if the agent has a quirk about that applicant's file, every observation
derived from it inherits the quirk. Resampling responses independently treats that one
quirk as many independent pieces of evidence and reports an interval narrower than the
design can support. ``tests/stats/test_calibration.py`` asserts that clustered intervals
come out *wider* than response-level ones on clustered data, so this cannot be quietly
"simplified" away later.

``pair_id`` is the contrast identifier used for pair-level discordance. It is deliberately
not the resampling cluster: two contrasts built from the same applicant have different
``pair_id`` values and the same ``cluster_id``.

**The statistic is a ratio, not a mean of ratios.** Clusters contribute unequal numbers of
observations, so the pooled rate ``sum(numerators) / sum(denominators)`` is resampled
directly. Averaging per-cluster rates would silently reweight a cluster with 2 trials equal
to one with 40.

**BCa, with a disclosed fallback.** BCa corrects for bias and for a variance that changes
with the parameter, which matters for rates near 0 and 1 -- exactly where this harness
operates. Its bias-correction and acceleration terms are undefined for a degenerate
bootstrap distribution, which is the *normal* case for a deterministic scripted control
where every cluster returns the identical value. When that happens the interval falls back
to the cluster-level percentile method and sets ``fallback_used``, which the export contract
carries to the site so a page can never claim BCa when percentile actually ran.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np
from scipy.stats import norm

from credit_audit.types import Frozen

CIMethod = Literal["BCa", "percentile", "none"]


class BootstrapCI(Frozen):
    """A point estimate and its clustered interval, with the method actually used."""

    point: float
    lower: float | None
    upper: float | None
    method: CIMethod
    n_observations: int
    n_clusters: int
    B: int | None = None
    cluster: str | None = "cluster_id"
    z0: float | None = None
    a: float | None = None
    seed: int | None = None
    fallback_used: bool = False
    """True when BCa was requested but its correction terms were undefined."""

    degenerate: bool = False
    """True when every bootstrap replicate equalled the observed statistic."""

    @property
    def ci95(self) -> tuple[float, float] | None:
        if self.lower is None or self.upper is None:
            return None
        return (self.lower, self.upper)

    @property
    def width(self) -> float | None:
        if self.lower is None or self.upper is None:
            return None
        return self.upper - self.lower


def _aggregate_by_cluster(
    values: Sequence[float],
    weights: Sequence[float],
    clusters: Sequence[str],
) -> tuple[np.ndarray, np.ndarray]:
    if not (len(values) == len(weights) == len(clusters)):
        raise ValueError("values, weights, and clusters must be the same length")
    sums: dict[str, list[float]] = {}
    for value, weight, cluster in zip(values, weights, clusters, strict=True):
        if weight < 0:
            raise ValueError("weights must be non-negative")
        entry = sums.setdefault(cluster, [0.0, 0.0])
        entry[0] += float(value)
        entry[1] += float(weight)
    # Sorted so the bootstrap draw is a function of the data, not of dict insertion order.
    ordered = [sums[key] for key in sorted(sums)]
    numerators = np.array([entry[0] for entry in ordered], dtype=float)
    denominators = np.array([entry[1] for entry in ordered], dtype=float)
    return numerators, denominators


def _percentile_interval(replicates: np.ndarray, alpha: float) -> tuple[float, float]:
    lower = float(np.quantile(replicates, alpha / 2.0))
    upper = float(np.quantile(replicates, 1.0 - alpha / 2.0))
    return lower, upper


def _bca_terms(
    replicates: np.ndarray,
    theta_hat: float,
    numerators: np.ndarray,
    denominators: np.ndarray,
) -> tuple[float, float] | None:
    """Bias correction ``z0`` and acceleration ``a``, or ``None`` when undefined."""

    below = float(np.mean(replicates < theta_hat))
    if below <= 0.0 or below >= 1.0:
        return None
    z0 = float(norm.ppf(below))

    total_numerator = float(numerators.sum())
    total_denominator = float(denominators.sum())
    jack_denominators = total_denominator - denominators
    if jack_denominators.size < 2 or np.any(jack_denominators <= 0):
        return None
    jackknife = (total_numerator - numerators) / jack_denominators

    centered = jackknife.mean() - jackknife
    sum_squares = float(np.sum(centered**2))
    if sum_squares <= 0.0:
        return None
    a = float(np.sum(centered**3) / (6.0 * sum_squares**1.5))
    if not np.isfinite(a):
        return None
    return z0, a


def _bca_interval(
    replicates: np.ndarray, alpha: float, z0: float, a: float
) -> tuple[float, float] | None:
    z_lower = float(norm.ppf(alpha / 2.0))
    z_upper = float(norm.ppf(1.0 - alpha / 2.0))
    adjusted: list[float] = []
    for z in (z_lower, z_upper):
        denominator = 1.0 - a * (z0 + z)
        if denominator <= 0.0:
            return None
        adjusted.append(float(norm.cdf(z0 + (z0 + z) / denominator)))
    lower_q, upper_q = adjusted
    if not (0.0 < lower_q < upper_q < 1.0):
        return None
    return (
        float(np.quantile(replicates, lower_q)),
        float(np.quantile(replicates, upper_q)),
    )


def cluster_bootstrap_ratio_ci(
    values: Sequence[float],
    weights: Sequence[float],
    clusters: Sequence[str],
    *,
    seed: int,
    alpha: float = 0.05,
    B: int = 10_000,
    method: CIMethod = "BCa",
    bounds: tuple[float, float] | None = None,
) -> BootstrapCI:
    """Confidence interval for ``sum(values) / sum(weights)``, resampling whole clusters.

    ``values`` and ``weights`` are per-observation contributions to the numerator and the
    denominator. A simple proportion passes a 0/1 indicator and a weight of 1; a rate pooled
    over repeated trials passes the event count and the trial count, which keeps unequal
    trial counts correctly weighted.

    ``bounds`` clips the interval to the parameter space -- ``(0, 1)`` for a rate, ``(-1, 1)``
    for a difference of rates. Clipping is legitimate here because the bound is a property of
    the estimand, not an artefact of the sample.
    """

    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie strictly between 0 and 1")
    if B <= 0:
        raise ValueError("B must be positive")

    numerators, denominators = _aggregate_by_cluster(values, weights, clusters)
    n_clusters = int(numerators.size)
    n_observations = len(values)
    total_denominator = float(denominators.sum())

    if n_clusters == 0 or total_denominator <= 0.0:
        # No applicable evidence. A point of 0.0 with a null interval and n = 0 is the
        # honest rendering; the export contract requires n on every estimate precisely so
        # an empty denominator cannot be mistaken for a measured zero.
        return BootstrapCI(
            point=0.0,
            lower=None,
            upper=None,
            method="none",
            n_observations=n_observations,
            n_clusters=n_clusters,
            B=None,
            seed=seed,
        )

    theta_hat = float(numerators.sum() / total_denominator)

    if n_clusters < 2:
        # One cluster is one experimental unit. There is no between-cluster variation to
        # resample, and pretending otherwise would report an interval built from a single
        # source applicant.
        return BootstrapCI(
            point=theta_hat,
            lower=None,
            upper=None,
            method="none",
            n_observations=n_observations,
            n_clusters=n_clusters,
            B=None,
            seed=seed,
        )

    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n_clusters, size=(B, n_clusters))
    numerator_star = numerators[draws].sum(axis=1)
    denominator_star = denominators[draws].sum(axis=1)
    usable = denominator_star > 0.0
    replicates = numerator_star[usable] / denominator_star[usable]

    if replicates.size == 0:
        return BootstrapCI(
            point=theta_hat,
            lower=None,
            upper=None,
            method="none",
            n_observations=n_observations,
            n_clusters=n_clusters,
            B=B,
            seed=seed,
        )

    degenerate = bool(np.all(replicates == theta_hat))
    z0: float | None = None
    acceleration: float | None = None
    interval: tuple[float, float] | None = None
    used: CIMethod = method
    fallback_used = False

    if method == "BCa":
        terms = _bca_terms(replicates, theta_hat, numerators, denominators)
        if terms is not None:
            z0, acceleration = terms
            interval = _bca_interval(replicates, alpha, z0, acceleration)
        if interval is None:
            # Documented cut line: percentile, disclosed, never a silently mislabelled BCa.
            z0 = None
            acceleration = None
            used = "percentile"
            fallback_used = True

    if interval is None:
        interval = _percentile_interval(replicates, alpha)
        if method == "percentile":
            used = "percentile"

    lower, upper = interval
    if bounds is not None:
        low, high = bounds
        lower = min(max(lower, low), high)
        upper = min(max(upper, low), high)

    return BootstrapCI(
        point=theta_hat,
        lower=lower,
        upper=upper,
        method=used,
        n_observations=n_observations,
        n_clusters=n_clusters,
        B=B,
        z0=z0,
        a=acceleration,
        seed=seed,
        fallback_used=fallback_used,
        degenerate=degenerate,
    )


def cluster_bootstrap_proportion_ci(
    successes: Sequence[bool],
    clusters: Sequence[str],
    *,
    seed: int,
    alpha: float = 0.05,
    B: int = 10_000,
    method: CIMethod = "BCa",
) -> BootstrapCI:
    """Clustered interval for a simple proportion, bounded to ``[0, 1]``."""

    values = [1.0 if success else 0.0 for success in successes]
    weights = [1.0] * len(values)
    return cluster_bootstrap_ratio_ci(
        values,
        weights,
        clusters,
        seed=seed,
        alpha=alpha,
        B=B,
        method=method,
        bounds=(0.0, 1.0),
    )


__all__ = [
    "BootstrapCI",
    "CIMethod",
    "cluster_bootstrap_proportion_ci",
    "cluster_bootstrap_ratio_ci",
]

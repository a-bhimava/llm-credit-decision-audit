"""pass^k -- the probability that *all* k independent trials pass.

This is the reliability complement of the familiar pass@k. pass@k asks whether at least one
of k attempts succeeds, which is the right question for a code generator that gets retries.
An underwriting agent gets no retries: the notice it produces is the notice the applicant
receives. The question that matters is whether it holds up every single time, so the
estimand is "all k passed", not "any of k passed".

The estimator is the unbiased combinatorial form. Given ``n`` observed trials of which ``s``
passed, the probability that a randomly chosen subset of ``k`` trials is all-passing is
``C(s, k) / C(n, k)``. Taking the plug-in ``(s / n) ** k`` instead is biased upward at small
``n``, which is exactly the regime the harness runs in.

Units with fewer than ``k`` trials cannot be estimated and are excluded. The surviving
denominator and the stratum are both reported, and the export contract makes ``stratum``
required so the caption stating which sample this was computed on cannot be dropped.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import comb

from pydantic import model_validator

from credit_audit.stats.bootstrap import BootstrapCI, cluster_bootstrap_ratio_ci
from credit_audit.types import Frozen


class TrialCounts(Frozen):
    """Repeated-trial outcomes for one experimental unit."""

    unit_id: str
    cluster_id: str
    """Originating source applicant. The bootstrap resamples these, not the units."""

    n_trials: int
    n_pass: int

    @model_validator(mode="after")
    def _validate(self) -> TrialCounts:
        if self.n_trials < 0 or self.n_pass < 0:
            raise ValueError("trial counts must be non-negative")
        if self.n_pass > self.n_trials:
            raise ValueError(f"unit {self.unit_id!r} passed more trials than it ran")
        return self

    def unbiased_pass_k(self, k: int) -> float | None:
        """``C(s, k) / C(n, k)``, or ``None`` when fewer than ``k`` trials were observed."""

        if self.n_trials < k:
            return None
        return comb(self.n_pass, k) / comb(self.n_trials, k)


class PassKEstimate(Frozen):
    check: str
    k: int
    stratum: str
    """Which sample this was computed on. Required by the export contract."""

    n: int
    """Units with at least ``k`` trials. The denominator for both rates below."""

    n_excluded: int
    """Units dropped for having fewer than ``k`` trials."""

    pass_1: float | None
    """Pooled single-trial pass rate over the same eligible units, for comparison."""

    pass_k: float | None
    ci95: tuple[float, float] | None = None
    ci_method: str = "none"
    fallback_used: bool = False
    n_clusters: int = 0


def pass_k_estimate(
    units: Sequence[TrialCounts],
    *,
    check: str,
    k: int,
    stratum: str,
    seed: int,
    alpha: float = 0.05,
    B: int = 10_000,
) -> PassKEstimate:
    """Unbiased pass^k with a cluster-level bootstrap interval.

    ``pass_1`` is pooled over the *same* eligible units as ``pass_k``. Computing the two on
    different denominators would make the gap between them partly an artefact of which units
    were droppable, which is the comparison a reader is most likely to draw.
    """

    if k < 1:
        raise ValueError("k must be at least 1")

    eligible = [unit for unit in units if unit.n_trials >= k]
    n_excluded = len(units) - len(eligible)
    if not eligible:
        return PassKEstimate(
            check=check,
            k=k,
            stratum=stratum,
            n=0,
            n_excluded=n_excluded,
            pass_1=None,
            pass_k=None,
        )

    total_trials = sum(unit.n_trials for unit in eligible)
    total_passes = sum(unit.n_pass for unit in eligible)
    pass_1 = total_passes / total_trials if total_trials else None

    per_unit = [unit.unbiased_pass_k(k) for unit in eligible]
    assert all(value is not None for value in per_unit)
    interval: BootstrapCI = cluster_bootstrap_ratio_ci(
        [float(value) for value in per_unit if value is not None],
        [1.0] * len(eligible),
        [unit.cluster_id for unit in eligible],
        seed=seed,
        alpha=alpha,
        B=B,
        bounds=(0.0, 1.0),
    )

    return PassKEstimate(
        check=check,
        k=k,
        stratum=stratum,
        n=len(eligible),
        n_excluded=n_excluded,
        pass_1=pass_1,
        pass_k=interval.point,
        ci95=interval.ci95,
        ci_method=interval.method,
        fallback_used=interval.fallback_used,
        n_clusters=interval.n_clusters,
    )


__all__ = ["PassKEstimate", "TrialCounts", "pass_k_estimate"]

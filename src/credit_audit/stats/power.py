"""Minimum detectable effect for the paired design, published before the run.

Power computed after seeing the result is not power, it is a restatement of the p-value.
The preregistration therefore fixes ``alpha`` and ``target_power`` up front and the MDE is
reported alongside every paired check, so a null result can be read as "no effect above
this size was detectable" rather than as "no effect".

The formula is Connor's normal approximation for McNemar's test, parameterized the way the
harness actually observes the design: ``n_pairs`` matched pairs, an expected discordant
proportion ``pi_d = (b + c) / n``, and a net effect ``delta = (c - b) / n``.

    n = [z_(1-alpha/2) * sqrt(pi_d) + z_power * sqrt(pi_d - delta^2)]^2 / delta^2

Two structural bounds fall out of the design and are enforced rather than assumed:
``|delta| <= pi_d``, because the net difference cannot exceed the discordant pairs that
produce it, and ``pi_d > 0``, because a design with no expected discordance can detect
nothing at any sample size.

On deterministic scripted controls the planted effects are exactly 0.0 or 1.0, so the MDE is
reported for completeness and is never the binding constraint. It becomes load-bearing when
a stochastic agent -- or a real provider in a later phase -- produces intermediate rates.
"""

from __future__ import annotations

import math

from scipy.stats import norm

from credit_audit.types import Frozen

_TOLERANCE = 1e-9


class PowerAnalysis(Frozen):
    """A preregistered power statement for one check."""

    check: str
    alpha: float
    target_power: float
    n_pairs: int
    assumed_discordance: float | None
    mde: float | None
    """Smallest net effect reaching ``target_power`` at this ``n_pairs``. ``None`` when no
    detectable effect reaches it, which is itself the finding."""

    achieved_power_at_observed: float | None = None


def mcnemar_power(
    *,
    n_pairs: int,
    discordance_rate: float,
    effect: float,
    alpha: float = 0.05,
) -> float | None:
    """Power of the two-sided exact McNemar test, by normal approximation.

    Returns ``None`` when the design is degenerate: no pairs, no expected discordance, or a
    net effect larger than the discordance that would have to produce it.
    """

    if n_pairs <= 0 or discordance_rate <= 0.0:
        return None
    if discordance_rate > 1.0:
        raise ValueError("discordance_rate must lie in [0, 1]")
    magnitude = abs(effect)
    if magnitude <= _TOLERANCE:
        # At no effect the rejection rate is the nominal level, not "power".
        return alpha
    if magnitude > discordance_rate + _TOLERANCE:
        return None

    variance = discordance_rate - magnitude**2
    if variance <= _TOLERANCE:
        # |delta| == sqrt(pi_d) can only happen when every discordant pair flips the same
        # way at pi_d == 1; the test then rejects with certainty.
        return 1.0

    z_alpha = float(norm.ppf(1.0 - alpha / 2.0))
    z_beta = (magnitude * math.sqrt(n_pairs) - z_alpha * math.sqrt(discordance_rate)) / math.sqrt(
        variance
    )
    return float(norm.cdf(z_beta))


def mcnemar_mde(
    *,
    n_pairs: int,
    discordance_rate: float,
    alpha: float = 0.05,
    target_power: float = 0.80,
) -> float | None:
    """Smallest net effect detectable at ``target_power``, or ``None`` if none is.

    Power is monotone increasing in the effect size over the admissible range, so the root
    is found by bisection on ``(0, pi_d]`` rather than by inverting the formula, which keeps
    the structural bounds above enforced at every step.
    """

    if not 0.0 < target_power < 1.0:
        raise ValueError("target_power must lie strictly between 0 and 1")
    if n_pairs <= 0 or discordance_rate <= 0.0:
        return None

    upper = discordance_rate
    best = mcnemar_power(
        n_pairs=n_pairs, discordance_rate=discordance_rate, effect=upper, alpha=alpha
    )
    if best is None or best < target_power:
        # Even the largest effect this discordance can produce is undetectable here.
        return None

    lower = 0.0
    for _ in range(200):
        middle = (lower + upper) / 2.0
        power = mcnemar_power(
            n_pairs=n_pairs, discordance_rate=discordance_rate, effect=middle, alpha=alpha
        )
        if power is not None and power >= target_power:
            upper = middle
        else:
            lower = middle
        if upper - lower < 1e-12:
            break
    return upper


def analyze_power(
    *,
    check: str,
    n_pairs: int,
    discordance_rate: float | None,
    observed_effect: float | None = None,
    alpha: float = 0.05,
    target_power: float = 0.80,
) -> PowerAnalysis:
    """Assemble the preregistered power statement for one check."""

    if discordance_rate is None:
        return PowerAnalysis(
            check=check,
            alpha=alpha,
            target_power=target_power,
            n_pairs=n_pairs,
            assumed_discordance=None,
            mde=None,
        )
    mde = mcnemar_mde(
        n_pairs=n_pairs,
        discordance_rate=discordance_rate,
        alpha=alpha,
        target_power=target_power,
    )
    achieved = (
        None
        if observed_effect is None
        else mcnemar_power(
            n_pairs=n_pairs,
            discordance_rate=discordance_rate,
            effect=observed_effect,
            alpha=alpha,
        )
    )
    return PowerAnalysis(
        check=check,
        alpha=alpha,
        target_power=target_power,
        n_pairs=n_pairs,
        assumed_discordance=discordance_rate,
        mde=mde,
        achieved_power_at_observed=achieved,
    )


__all__ = ["PowerAnalysis", "analyze_power", "mcnemar_mde", "mcnemar_power"]

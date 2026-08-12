"""McNemar's exact test on matched pair flips.

All of the evidence about a paired contrast lives in the two discordant cells. Concordant
pairs -- both arms approved, or both were adverse -- carry no information about whether the
intervention moved the decision, so they are not in the test statistic. They remain in the
reported denominator, because the *rate* of discordance is the estimand and a reader needs
to know whether 8 flips came out of 10 pairs or out of 10,000.

**Exact, not chi-square.** The asymptotic McNemar statistic is unusable at the discordant
counts this harness produces (often single digits, sometimes zero). Under the null the
number of flips in one direction is ``Binomial(b + c, 0.5)``, which is symmetric, so
doubling the smaller tail is the exact two-sided p-value rather than an approximation.

**Two conventions are reported, and they are not interchangeable:**

* ``p_exact`` is *valid but conservative*. On a discrete statistic no test can hit the
  nominal level exactly; the guarantee is ``P(p <= alpha) <= alpha``. This is the number
  that goes into multiplicity control, because FDR control needs valid p-values.
* ``p_mid`` is the mid-p variant, which is approximately uniform under the null and is
  therefore what a calibration plot should be read against. It is reported for diagnostics
  and is deliberately *not* the number BH consumes.

Only two-sided p-values are computed. A one-sided test at the same alpha would reject more
readily in the declared direction, and switching to it after seeing which direction the
flips went is the oldest trick in the book. Two-sided everywhere removes the temptation.
"""

from __future__ import annotations

from scipy.stats import binom

from credit_audit.types import Frozen


class McNemarResult(Frozen):
    """The exact paired test and the discordant-pair estimand it is computed from."""

    b: int
    """Discordant pairs where the base arm approved and the counterfactual arm did not."""

    c: int
    """Discordant pairs where the base arm was adverse and the counterfactual arm approved."""

    n_pairs: int
    """Matched, bilaterally decisive pairs. The denominator for every rate below."""

    p_exact: float
    p_mid: float

    discordant_rate: float | None
    """``(b + c) / n_pairs`` -- the preregistered estimand: how often the arms disagreed."""

    net_rate: float | None
    """``(c - b) / n_pairs`` -- signed movement toward approval. Equals ``PairedScore.effect``."""

    @property
    def n_discordant(self) -> int:
        return self.b + self.c

    @property
    def concordant(self) -> int:
        return self.n_pairs - self.n_discordant


def mcnemar_exact(b: int, c: int, *, n_pairs: int) -> McNemarResult:
    """Exact two-sided McNemar test on ``b`` and ``c`` discordant pairs.

    ``n_pairs`` is the count of matched pairs where **both** arms reached a decisive
    outcome, which the paired scorer already computed as ``matched_trials``. It must be at
    least ``b + c``; a smaller value means the caller mixed denominators, which would deflate
    every rate reported here, so it raises rather than rescaling silently.
    """

    if b < 0 or c < 0:
        raise ValueError("discordant counts must be non-negative")
    if n_pairs < 0:
        raise ValueError("n_pairs must be non-negative")
    n_discordant = b + c
    if n_discordant > n_pairs:
        raise ValueError(
            f"discordant pairs ({n_discordant}) exceed matched pairs ({n_pairs}); "
            "the counts come from different denominators"
        )

    if n_discordant == 0:
        # No pair disagreed. There is no evidence against exchangeability, and the exact
        # test says so rather than dividing by zero.
        p_exact = 1.0
        p_mid = 1.0
    else:
        smaller = min(b, c)
        tail = float(binom.cdf(smaller, n_discordant, 0.5))
        point_mass = float(binom.pmf(smaller, n_discordant, 0.5))
        p_exact = min(1.0, 2.0 * tail)
        p_mid = min(1.0, 2.0 * (tail - 0.5 * point_mass))

    if n_pairs:
        discordant_rate: float | None = n_discordant / n_pairs
        net_rate: float | None = (c - b) / n_pairs
    else:
        discordant_rate = None
        net_rate = None

    return McNemarResult(
        b=b,
        c=c,
        n_pairs=n_pairs,
        p_exact=p_exact,
        p_mid=p_mid,
        discordant_rate=discordant_rate,
        net_rate=net_rate,
    )


__all__ = ["McNemarResult", "mcnemar_exact"]

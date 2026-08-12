"""Benjamini-Hochberg false-discovery-rate control within preregistered families.

This harness runs dozens of comparisons. At alpha = 0.05 and 30 true nulls, the expected
number of spurious rejections is 1.5, so an uncorrected "significant" result means very
little. BH controls the expected *proportion* of rejections that are false, which is the
right error rate for a screening design where several genuine effects are expected.

**Grouping is preregistered, not chosen after the fact.** BH is applied within each declared
family and never pooled across all of them. Pooling is not the conservative choice it looks
like: a family with many easy rejections raises the BH threshold for every other family in
the pool, so a marginal p-value in an unrelated family can be carried across the line by
results it has nothing to do with.

Exploratory hypotheses are excluded from every group by the caller and are rendered without
a q-value. Adding them would inflate the group size and penalize the preregistered tests for
the existence of diagnostics.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from credit_audit.types import Frozen


class BHResult(Frozen):
    """One hypothesis's place in its BH group."""

    key: str
    p: float
    q: float
    """BH-adjusted p-value (q-value), enforced monotone non-decreasing in ``p``."""

    rejected: bool
    rank: int = 0
    n_hypotheses: int = 0


class BHGroup(Frozen):
    group: str
    q_target: float
    n_hypotheses: int
    n_rejected: int
    results: tuple[BHResult, ...] = ()


def benjamini_hochberg(p_values: Sequence[float], *, q: float) -> tuple[float, ...]:
    """Return BH-adjusted q-values, in the input order.

    The adjusted value for the i-th smallest of ``m`` p-values is ``m * p_(i) / i``, made
    monotone by taking a running minimum from the largest p-value downward and clipped to 1.
    Rejecting every hypothesis whose q-value is at or below the target reproduces the
    step-up procedure exactly, including the case where a small p-value is rescued by a
    larger one further up the ranking.
    """

    if not 0.0 < q < 1.0:
        raise ValueError("q must lie strictly between 0 and 1")
    for p in p_values:
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"p-value outside [0, 1]: {p}")

    m = len(p_values)
    if m == 0:
        return ()

    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running_min = 1.0
    for rank in range(m, 0, -1):
        index = order[rank - 1]
        value = min(1.0, p_values[index] * m / rank)
        running_min = min(running_min, value)
        adjusted[index] = running_min
    return tuple(adjusted)


def benjamini_hochberg_group(
    p_by_key: Mapping[str, float] | Iterable[tuple[str, float]],
    *,
    group: str,
    q: float,
) -> BHGroup:
    """Apply BH to one preregistered family and report the whole group."""

    items = tuple(p_by_key.items() if isinstance(p_by_key, Mapping) else p_by_key)
    keys = [key for key, _ in items]
    if len(set(keys)) != len(keys):
        raise ValueError(f"duplicate hypothesis keys in BH group {group!r}")
    p_values = [p for _, p in items]
    q_values = benjamini_hochberg(p_values, q=q)

    ranks = {key: rank for rank, (key, _) in enumerate(sorted(items, key=lambda kv: kv[1]), 1)}
    results = tuple(
        BHResult(
            key=key,
            p=p,
            q=q_value,
            rejected=q_value <= q,
            rank=ranks[key],
            n_hypotheses=len(items),
        )
        for (key, p), q_value in zip(items, q_values, strict=True)
    )
    return BHGroup(
        group=group,
        q_target=q,
        n_hypotheses=len(items),
        n_rejected=sum(result.rejected for result in results),
        results=results,
    )


__all__ = ["BHGroup", "BHResult", "benjamini_hochberg", "benjamini_hochberg_group"]

"""Token prices, so ``Usage.cost_usd`` is a measurement rather than a placeholder.

Until now every run reported ``cost_usd == 0.0`` because scripted agents genuinely cost
nothing, which made the suites' ``max_usd: 0.0`` caps unfalsifiable. Once a real adapter
reports truthful cost, those caps become live assertions: a scripted suite pointed at a paid
provider refuses on the first episode instead of quietly spending.

Prices are **declared here and dated**, never fetched. A run's cost must be reproducible from
its manifest years later, and a price table that silently changed under a published bundle
would make its reported cost unverifiable. When a price moves, add an entry and leave the old
one; the manifest records which model was used and the bundle records what it cost.

Rates are USD per million tokens. A model absent from the table is priced at zero **and
flagged**, because silently assuming free is how a budget cap stops protecting anything.
"""

from __future__ import annotations

from credit_audit.types import Frozen

PRICES_AS_OF = "2026-08-13"


class TokenPrice(Frozen):
    """USD per one million tokens."""

    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float | None = None
    """Where a provider bills cached prompt tokens at a reduced rate. ``None`` means the
    provider does not distinguish, and cached tokens are billed as input."""

    note: str = ""


MILLION = 1_000_000

PRICES: dict[str, TokenPrice] = {
    # The project's default. Chosen for thinking-off-by-default determinism, not for price,
    # though it happens to be the cheapest tier as well.
    "gemini-2.5-flash-lite": TokenPrice(
        input_per_mtok=0.10,
        output_per_mtok=0.40,
        note="Roadmap default. ~$18 for a 5,000-episode run at the estimated token mix.",
    ),
    "gemini-2.5-flash": TokenPrice(input_per_mtok=0.30, output_per_mtok=2.50),
}


def price_for(model_id: str) -> TokenPrice | None:
    """Exact match, then a prefix match so dated model snapshots resolve.

    Providers publish ids like ``gemini-2.5-flash-lite-preview-09-2025``. A snapshot inherits
    its base model's price rather than silently costing nothing.
    """

    exact = PRICES.get(model_id)
    if exact is not None:
        return exact
    candidates = [key for key in PRICES if model_id.startswith(key)]
    if not candidates:
        return None
    return PRICES[max(candidates, key=len)]


def cost_usd(
    model_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> tuple[float, bool]:
    """Return ``(cost, priced)``.

    ``priced`` is False when the model is not in the table. The caller must surface that
    rather than treat the zero as a measurement -- an unpriced model would otherwise make
    every budget cap pass by default, which is precisely backwards.

    Cached tokens are assumed to be a *subset* of input tokens, which is how both the OpenAI
    and Gemini usage blocks report them, so they are billed at the cached rate and deducted
    from the uncached remainder.
    """

    price = price_for(model_id)
    if price is None:
        return 0.0, False

    billable_cached = min(cached_tokens, input_tokens) if cached_tokens > 0 else 0
    uncached = input_tokens - billable_cached
    cached_rate = (
        price.cached_input_per_mtok
        if price.cached_input_per_mtok is not None
        else price.input_per_mtok
    )
    total = (
        uncached * price.input_per_mtok
        + billable_cached * cached_rate
        + output_tokens * price.output_per_mtok
    ) / MILLION
    return total, True


__all__ = ["MILLION", "PRICES", "PRICES_AS_OF", "TokenPrice", "cost_usd", "price_for"]

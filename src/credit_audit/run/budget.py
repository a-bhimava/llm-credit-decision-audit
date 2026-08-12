"""Run-wide budget: episodes, dollars, tokens, and wall time.

A scripted run costs nothing, so every cap here passes trivially today. That is exactly why
it is built now. Phase 9 permits a live provider adapter, and the first paid run is the worst
possible moment to discover that nothing stops a loop from spending the afternoon's budget in
four minutes. The budget refuses to *start* a plan it cannot afford and stops mid-run the
moment a cap is crossed, with the partial evidence already persisted.

A zero-dollar cap is a live assertion rather than a placeholder: a scripted agent reports zero
cost, so `max_usd: 0.0` in a suite means "this run must make no paid call" and fails loudly if
one ever does.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from credit_audit.suites.loader import Caps
from credit_audit.types import Frozen, Trajectory


class BudgetExceeded(RuntimeError):
    """Raised when a cap is crossed. Carries the state so the caller can report it."""

    def __init__(self, message: str, spent: BudgetState) -> None:
        super().__init__(message)
        self.spent = spent


class BudgetState(Frozen):
    episodes: int = 0
    usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    thought_tokens: int = 0
    cache_hits: int = 0
    replayed: int = 0
    elapsed_seconds: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class Budget:
    """Mutable spend tracker. One per run."""

    def __init__(self, caps: Caps, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._caps = caps
        self._clock = clock
        self._started = clock()
        self._episodes = 0
        self._usd = 0.0
        self._input_tokens = 0
        self._output_tokens = 0
        self._cached_tokens = 0
        self._thought_tokens = 0
        self._cache_hits = 0
        self._replayed = 0

    @property
    def caps(self) -> Caps:
        return self._caps

    def state(self) -> BudgetState:
        return BudgetState(
            episodes=self._episodes,
            usd=self._usd,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cached_tokens=self._cached_tokens,
            thought_tokens=self._thought_tokens,
            cache_hits=self._cache_hits,
            replayed=self._replayed,
            elapsed_seconds=self._clock() - self._started,
        )

    def admit(self, planned_episodes: int) -> None:
        """Refuse before executing anything if the plan cannot fit the episode cap.

        Checked against the plan's upper bound, so a run that *might* exceed the cap is
        rejected up front rather than aborted halfway with a partial bundle.
        """

        cap = self._caps.max_episodes
        if cap is not None and planned_episodes > cap:
            raise BudgetExceeded(
                f"plan needs up to {planned_episodes} episodes but the suite caps them at "
                f"{cap}; raise caps.max_episodes or narrow the suite",
                self.state(),
            )

    def charge(self, trajectory: Trajectory) -> None:
        """Account for one executed episode, then enforce every cap."""

        usage = trajectory.usage
        self._episodes += 1
        self._usd += usage.cost_usd
        self._input_tokens += usage.input_tokens
        self._output_tokens += usage.output_tokens
        self._cached_tokens += usage.cached_tokens
        self._thought_tokens += usage.thought_tokens
        self._cache_hits += int(usage.cache_hit)
        self._replayed += int(usage.replayed)
        self._enforce()

    def _enforce(self) -> None:
        caps = self._caps
        state = self.state()
        if caps.max_episodes is not None and state.episodes > caps.max_episodes:
            raise BudgetExceeded(
                f"episode cap reached: {state.episodes} > {caps.max_episodes}", state
            )
        if caps.max_usd is not None and state.usd > caps.max_usd:
            raise BudgetExceeded(f"cost cap reached: ${state.usd:.4f} > ${caps.max_usd:.4f}", state)
        if caps.max_tokens is not None and state.total_tokens > caps.max_tokens:
            raise BudgetExceeded(
                f"token cap reached: {state.total_tokens} > {caps.max_tokens}", state
            )
        if caps.max_wall_seconds is not None and state.elapsed_seconds > caps.max_wall_seconds:
            raise BudgetExceeded(
                f"wall-time cap reached: {state.elapsed_seconds:.1f}s > "
                f"{caps.max_wall_seconds:.1f}s",
                state,
            )


__all__ = ["Budget", "BudgetExceeded", "BudgetState"]

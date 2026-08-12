"""The run budget: admission up front, enforcement per episode, and honest partial evidence."""

from __future__ import annotations

import pytest

from credit_audit.ids import trajectory_content_id
from credit_audit.run.budget import Budget, BudgetExceeded
from credit_audit.suites.loader import Caps
from credit_audit.types import EpisodeKey, RenderMode, Termination, Trajectory, Usage


def _trajectory(*, cost: float = 0.0, tokens: int = 0, index: int = 0) -> Trajectory:
    """A minimal terminated episode. Identities are computed, because Trajectory checks them."""

    key = EpisodeKey(
        applicant_id="APP-1",
        applicant_content_id="blake2b128:00000000000000000000000000000000",
        arm_id="arm",
        render_id=RenderMode.TABLE,
        trial_index=index,
        model_id="scripted:test",
        prompt_hash="blake2b128:01000000000000000000000000000000",
        input_hash="blake2b128:02000000000000000000000000000000",
        seed=1,
    )
    termination = Termination.ERROR
    return Trajectory(
        episode_id=key.episode_id,
        trajectory_id=trajectory_content_id(
            episode_id=key.episode_id,
            messages=(),
            tool_calls=(),
            decision=None,
            termination=termination,
        ),
        key=key,
        termination=termination,
        usage=Usage(input_tokens=tokens, output_tokens=0, cost_usd=cost),
    )


def test_a_plan_larger_than_the_cap_is_refused_before_anything_runs():
    budget = Budget(Caps(max_episodes=100))
    with pytest.raises(BudgetExceeded, match="raise caps.max_episodes"):
        budget.admit(101)
    assert budget.state().episodes == 0


def test_a_plan_within_the_cap_is_admitted():
    Budget(Caps(max_episodes=100)).admit(100)


def test_unlimited_caps_admit_anything():
    Budget(Caps()).admit(10**9)


def test_episodes_are_counted_and_capped_mid_run():
    budget = Budget(Caps(max_episodes=2))
    budget.charge(_trajectory(index=0))
    budget.charge(_trajectory(index=1))
    with pytest.raises(BudgetExceeded, match="episode cap reached") as excinfo:
        budget.charge(_trajectory(index=2))
    assert excinfo.value.spent.episodes == 3


def test_a_zero_dollar_cap_catches_the_first_paid_call():
    """The assertion a scripted suite actually makes: this run spent nothing."""

    budget = Budget(Caps(max_usd=0.0))
    budget.charge(_trajectory(cost=0.0))
    with pytest.raises(BudgetExceeded, match="cost cap reached"):
        budget.charge(_trajectory(cost=0.01, index=1))


def test_token_cap_sums_input_and_output():
    budget = Budget(Caps(max_tokens=10))
    budget.charge(_trajectory(tokens=6))
    with pytest.raises(BudgetExceeded, match="token cap reached"):
        budget.charge(_trajectory(tokens=6, index=1))


def test_wall_time_cap_uses_the_injected_clock():
    """The clock is injected so this is a real assertion rather than a sleep."""

    readings = [0.0, 100.0]

    def clock() -> float:
        return readings.pop(0) if len(readings) > 1 else readings[0]

    budget = Budget(Caps(max_wall_seconds=10.0), clock=clock)
    with pytest.raises(BudgetExceeded, match="wall-time cap reached"):
        budget.charge(_trajectory())


def test_state_accumulates_usage_telemetry():
    budget = Budget(Caps())
    budget.charge(_trajectory(tokens=5, cost=0.5))
    budget.charge(_trajectory(tokens=7, cost=0.25, index=1))
    state = budget.state()
    assert state.episodes == 2
    assert state.input_tokens == 12
    assert state.total_tokens == 12
    assert state.usd == pytest.approx(0.75)

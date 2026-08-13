"""A turn with no content and no tool call is silence, not a decision to stop.

Treating it as terminal ended the episode with no decision and discarded the applicant. In a
recorded run against a real model this accounted for most incomplete episodes: completion rose
from 60% to 92% once a null turn was allowed to consume a step and continue.
"""

from __future__ import annotations

import asyncio

from credit_audit.env.episode import build_episode_key, run_episode
from credit_audit.model.client import ModelResponse, ToolCallRequested
from credit_audit.types import FrozenDict, RenderMode, Termination


def _key(applicant, policy, model_id: str):
    return build_episode_key(
        applicant=applicant,
        arm_id="null-turn",
        render_id=RenderMode.TABLE,
        trial_index=0,
        model_id=model_id,
        policy=policy,
        reason_mode="coded",
        seed=1729,
    )


def _run(applicant, policy, client):
    return asyncio.run(
        run_episode(
            key=_key(applicant, policy, client.model_id),
            applicant=applicant,
            policy=policy,
            client=client,
            reason_mode="coded",
        )
    )


class _SilentThenDecides:
    model_id = "scripted:silent-then-decides"

    def __init__(self) -> None:
        self.turns = 0

    async def complete(self, _req) -> ModelResponse:
        self.turns += 1
        if self.turns == 1:
            return ModelResponse(content="", stop_reason="stop")
        return ModelResponse(
            content="",
            stop_reason="tool_calls",
            tool_calls=(
                ToolCallRequested(
                    call_id="c1",
                    name="submit_decision",
                    arguments=FrozenDict({"outcome": "APPROVE", "reasons": []}),
                ),
            ),
        )


class _AlwaysSilent:
    model_id = "scripted:always-silent"

    def __init__(self) -> None:
        self.turns = 0

    async def complete(self, _req) -> ModelResponse:
        self.turns += 1
        return ModelResponse(content="", stop_reason="stop")


class _SaysSomethingAndStops:
    model_id = "scripted:says-and-stops"

    async def complete(self, _req) -> ModelResponse:
        return ModelResponse(content="I decline to proceed.", stop_reason="stop")


def test_a_null_turn_gets_another_chance(golden_clean_applicant, policy):
    client = _SilentThenDecides()
    trajectory = _run(golden_clean_applicant, policy, client)

    assert client.turns >= 2, "the agent must have been given another turn"
    assert trajectory.termination is Termination.SUBMITTED
    assert trajectory.decision is not None


def test_endless_silence_still_terminates(golden_clean_applicant, policy):
    """Forgiving a null turn must not create a loop; the step budget still binds."""

    client = _AlwaysSilent()
    trajectory = _run(golden_clean_applicant, policy, client)

    assert trajectory.termination is Termination.MAX_STEPS
    assert trajectory.decision is None
    assert client.turns <= 13, "each null turn must consume a step"


def test_a_stop_with_content_still_ends_the_episode(golden_clean_applicant, policy):
    """Only silence is forgiven. An agent that says something and stops has stopped."""

    trajectory = _run(golden_clean_applicant, policy, _SaysSomethingAndStops())
    assert trajectory.termination is Termination.STOP

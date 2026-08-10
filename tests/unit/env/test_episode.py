"""The tool-calling loop: step semantics, the max_steps boundary, and the same
no-self-enforcement invariant proven end to end through run_episode rather than only at
the dispatch() level.
"""

from __future__ import annotations

import asyncio

from credit_audit.env.episode import run_episode
from credit_audit.model.client import ModelResponse, ToolCallRequested
from credit_audit.model.scripted import FaithfulAgent, MalformedAgent, RefusingAgent
from credit_audit.types import EpisodeKey, RenderMode, Termination


def _key(applicant_id: str, **overrides) -> EpisodeKey:
    base = dict(
        applicant_id=applicant_id,
        arm_id="control",
        render_id=RenderMode.TABLE,
        trial_index=0,
        model_id="test",
        prompt_hash="stub",
        seed=1,
    )
    base.update(overrides)
    return EpisodeKey(**base)


def test_faithful_agent_full_episode(golden_clean_applicant, policy):
    key = _key(golden_clean_applicant.applicant_id, model_id="scripted:faithful")
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            application_text="stub text",
            applicant_ref=golden_clean_applicant.applicant_id,
            client=FaithfulAgent(),
            reason_mode="coded",
        )
    )
    assert traj.termination == Termination.SUBMITTED
    assert traj.decision is not None
    assert traj.decision.outcome.value == "APPROVE"
    tool_names = [tc.name for tc in traj.tool_calls]
    assert tool_names[:2] == ["get_application", "fetch_credit_report"]
    assert tool_names[-1] == "submit_decision"
    assert all(tc.ok for tc in traj.tool_calls)


class _TalkerClient:
    """A test-only client that thinks out loud (no tool calls) three times before
    deciding -- proves a content-only turn still consumes a step."""

    model_id = "test:talker"

    def __init__(self):
        self.calls = 0

    async def complete(self, req):
        self.calls += 1
        if self.calls <= 3:
            return ModelResponse(content="thinking...", stop_reason="stop")
        call = ToolCallRequested(
            call_id="c1", name="submit_decision", arguments={"outcome": "APPROVE", "reasons": []}
        )
        return ModelResponse(tool_calls=(call,), stop_reason="tool_calls")


def test_no_tool_call_turn_still_consumes_a_step(golden_clean_applicant, policy):
    key = _key(golden_clean_applicant.applicant_id, model_id="test:talker")
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            application_text="stub",
            applicant_ref=golden_clean_applicant.applicant_id,
            client=_TalkerClient(),
            reason_mode="coded",
        )
    )
    assert traj.termination == Termination.SUBMITTED
    assert len([m for m in traj.messages if m.role == "assistant"]) == 3


def test_malformed_agent_hits_max_steps_and_never_crashes(golden_clean_applicant, policy):
    key = _key(golden_clean_applicant.applicant_id, model_id="scripted:malformed")
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            application_text="stub",
            applicant_ref=golden_clean_applicant.applicant_id,
            client=MalformedAgent(),
            reason_mode="coded",
            max_steps=5,
        )
    )
    assert traj.termination == Termination.MAX_STEPS
    assert traj.decision is None
    # 2-step prelude (get_application, fetch_credit_report) + 3 failed submit_decision
    # attempts = 5 tool calls, exactly filling max_steps=5.
    assert len(traj.tool_calls) == 5
    assert [tc.ok for tc in traj.tool_calls] == [True, True, False, False, False]


def test_max_steps_boundary_is_exact(golden_clean_applicant, policy):
    """max_steps=2 must permit exactly the 2-call prelude and nothing past it."""
    key = _key(golden_clean_applicant.applicant_id, model_id="scripted:malformed")
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            application_text="stub",
            applicant_ref=golden_clean_applicant.applicant_id,
            client=MalformedAgent(),
            reason_mode="coded",
            max_steps=2,
        )
    )
    assert traj.termination == Termination.MAX_STEPS
    assert len(traj.tool_calls) == 2
    assert [tc.name for tc in traj.tool_calls] == ["get_application", "fetch_credit_report"]


def test_refusing_agent_terminates_immediately(golden_clean_applicant, policy):
    key = _key(golden_clean_applicant.applicant_id, model_id="scripted:refusing")
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            application_text="stub",
            applicant_ref=golden_clean_applicant.applicant_id,
            client=RefusingAgent(),
            reason_mode="coded",
        )
    )
    assert traj.termination == Termination.REFUSAL
    assert traj.decision is None
    assert traj.tool_calls == ()


class _ImmediateSubmitter:
    """Skips the prelude entirely -- proves the environment permits it (see
    env/tools.py's central invariant), exercised here at the full run_episode level."""

    model_id = "test:immediate"

    async def complete(self, req):
        call = ToolCallRequested(
            call_id="c1", name="submit_decision", arguments={"outcome": "APPROVE", "reasons": []}
        )
        return ModelResponse(tool_calls=(call,), stop_reason="tool_calls")


def test_submit_decision_with_no_prior_tools_terminates_episode(golden_clean_applicant, policy):
    key = _key(golden_clean_applicant.applicant_id, model_id="test:immediate")
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            application_text="stub",
            applicant_ref=golden_clean_applicant.applicant_id,
            client=_ImmediateSubmitter(),
            reason_mode="coded",
        )
    )
    assert traj.termination == Termination.SUBMITTED
    assert len(traj.tool_calls) == 1
    assert traj.tool_calls[0].name == "submit_decision"


def test_default_max_steps_comes_from_policy(golden_clean_applicant, policy):
    assert policy.process.max_steps == 12

"""The tool-calling loop: step semantics, the max_steps boundary, and the same
no-self-enforcement invariant proven end to end through run_episode rather than only at
the dispatch() level.
"""

from __future__ import annotations

import asyncio

import pytest

from credit_audit.env import episode as episode_module
from credit_audit.env.episode import build_episode_key, episode_prompt_hash, run_episode
from credit_audit.model.client import ModelResponse, ToolCallRequested
from credit_audit.model.scripted import FaithfulAgent, MalformedAgent, RefusingAgent
from credit_audit.types import RenderMode, Termination, Usage


def _key(applicant, policy, client, **overrides):
    base = dict(
        applicant=applicant,
        arm_id="control",
        render_id=RenderMode.TABLE,
        trial_index=0,
        model_id=client.model_id,
        policy=policy,
        reason_mode="coded",
        seed=1,
    )
    base.update(overrides)
    return build_episode_key(**base)


def test_faithful_agent_full_episode(golden_clean_applicant, policy):
    client = FaithfulAgent()
    key = _key(golden_clean_applicant, policy, client)
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            client=client,
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
    assert traj.episode_id == key.episode_id
    assert traj.trajectory_id != traj.episode_id
    assert [message.role for message in traj.messages[:2]] == ["system", "user"]
    assert golden_clean_applicant.applicant_id not in traj.messages[1].content
    assert "MPL-" in traj.messages[1].content
    assert all(tc.call_id for tc in traj.tool_calls)
    assert [tc.turn_index for tc in traj.tool_calls] == [1, 2, 3]
    assistant_requests = [m for m in traj.messages if m.role == "assistant" and m.tool_calls]
    tool_results = [m for m in traj.messages if m.role == "tool"]
    assert [m.tool_calls[0].call_id for m in assistant_requests] == [
        m.tool_call_id for m in tool_results
    ]


class _TalkerClient:
    """A malformed client emits nonterminal empty tool-call turns before deciding."""

    model_id = "test:talker"

    def __init__(self):
        self.calls = 0

    async def complete(self, _req):
        self.calls += 1
        if self.calls <= 3:
            return ModelResponse(content="thinking...", stop_reason="tool_calls")
        call = ToolCallRequested(
            call_id="c1", name="submit_decision", arguments={"outcome": "APPROVE", "reasons": []}
        )
        return ModelResponse(tool_calls=(call,), stop_reason="tool_calls")


def test_no_tool_call_turn_still_consumes_a_step(golden_clean_applicant, policy):
    client = _TalkerClient()
    key = _key(golden_clean_applicant, policy, client)
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            client=client,
            reason_mode="coded",
        )
    )
    assert traj.termination == Termination.SUBMITTED
    assert len([m for m in traj.messages if m.role == "assistant"]) == 4


def test_malformed_agent_hits_max_steps_and_never_crashes(golden_clean_applicant, policy):
    client = MalformedAgent()
    key = _key(golden_clean_applicant, policy, client)
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            client=client,
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
    client = MalformedAgent()
    key = _key(golden_clean_applicant, policy, client)
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            client=client,
            reason_mode="coded",
            max_steps=2,
        )
    )
    assert traj.termination == Termination.MAX_STEPS
    assert len(traj.tool_calls) == 2
    assert [tc.name for tc in traj.tool_calls] == ["get_application", "fetch_credit_report"]


def test_refusing_agent_terminates_immediately(golden_clean_applicant, policy):
    client = RefusingAgent()
    key = _key(golden_clean_applicant, policy, client)
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            client=client,
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

    def __init__(self, content: str = ""):
        self.content = content

    async def complete(self, _req):
        call = ToolCallRequested(
            call_id="c1", name="submit_decision", arguments={"outcome": "APPROVE", "reasons": []}
        )
        return ModelResponse(content=self.content, tool_calls=(call,), stop_reason="tool_calls")


def test_submit_decision_with_no_prior_tools_terminates_episode(golden_clean_applicant, policy):
    client = _ImmediateSubmitter()
    key = _key(golden_clean_applicant, policy, client)
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            client=client,
            reason_mode="coded",
        )
    )
    assert traj.termination == Termination.SUBMITTED
    assert len(traj.tool_calls) == 1
    assert traj.tool_calls[0].name == "submit_decision"


def test_episode_id_is_plan_stable_but_trajectory_id_hashes_semantic_trace(
    golden_clean_applicant, policy
):
    client_a = _ImmediateSubmitter("trace A")
    client_b = _ImmediateSubmitter("trace B")
    key = _key(golden_clean_applicant, policy, client_a)

    def run(client):
        return asyncio.run(
            run_episode(
                key=key,
                applicant=golden_clean_applicant,
                policy=policy,
                client=client,
                reason_mode="coded",
            )
        )

    a = run(client_a)
    b = run(client_b)
    assert a.episode_id == b.episode_id == key.episode_id
    assert a.final_state_hash == b.final_state_hash
    assert a.trajectory_id != b.trajectory_id


def test_episode_id_separates_applicant_content_variants(golden_clean_applicant, policy):
    client = _ImmediateSubmitter()
    variant = golden_clean_applicant.model_copy(
        update={
            "presentation": golden_clean_applicant.presentation.model_copy(
                update={"applicant_name": "Visible Variant"}
            )
        }
    )
    base_key = _key(golden_clean_applicant, policy, client)
    variant_key = _key(variant, policy, client)
    assert base_key.applicant_id == variant_key.applicant_id
    assert base_key.applicant_content_id != variant_key.applicant_content_id
    assert base_key.input_hash != variant_key.input_hash
    assert base_key.episode_id != variant_key.episode_id


def test_prompt_hash_covers_provider_visible_tool_schemas(
    golden_clean_applicant, policy, monkeypatch
):
    del golden_clean_applicant
    baseline = episode_prompt_hash(policy, "coded")
    original = episode_module.tool_specs

    def changed_specs(reason_mode):
        specs = original(reason_mode)
        return (
            specs[0].model_copy(update={"description": specs[0].description + " changed"}),
            *specs[1:],
        )

    monkeypatch.setattr(episode_module, "tool_specs", changed_specs)
    assert episode_prompt_hash(policy, "coded") != baseline


def test_default_max_steps_comes_from_policy(policy):
    assert policy.process.max_steps == 12


class _TerminalClient:
    model_id = "test:terminal"

    def __init__(self, stop_reason):
        self.stop_reason = stop_reason

    async def complete(self, _req):
        return ModelResponse(
            content="done",
            stop_reason=self.stop_reason,
            usage=Usage(
                input_tokens=3,
                output_tokens=4,
                cached_tokens=2,
                thought_tokens=1,
                cost_usd=0.25,
                cache_hit=True,
            ),
        )


@pytest.mark.parametrize(
    ("stop_reason", "termination"),
    [
        ("stop", Termination.STOP),
        ("refusal", Termination.REFUSAL),
        ("max_tokens", Termination.MAX_TOKENS),
        ("error", Termination.ERROR),
    ],
)
def test_provider_terminal_reasons_finalize_immediately(
    golden_clean_applicant, policy, stop_reason, termination
):
    client = _TerminalClient(stop_reason)
    key = _key(golden_clean_applicant, policy, client)
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            client=client,
            reason_mode="coded",
        )
    )
    assert traj.termination is termination
    assert traj.usage == Usage(
        input_tokens=3,
        output_tokens=4,
        cached_tokens=2,
        thought_tokens=1,
        cost_usd=0.25,
        cache_hit=True,
    )


def test_run_episode_rejects_mismatched_identity(golden_clean_applicant, policy):
    client = _ImmediateSubmitter()
    key = _key(golden_clean_applicant, policy, client)
    with pytest.raises(ValueError, match="canonical renderer"):
        asyncio.run(
            run_episode(
                key=key,
                applicant=golden_clean_applicant,
                policy=policy,
                application_text="TAMPERED INPUT",
                client=client,
                reason_mode="coded",
            )
        )

    with pytest.raises(ValueError, match="applicant_ref"):
        asyncio.run(
            run_episode(
                key=key,
                applicant=golden_clean_applicant,
                policy=policy,
                applicant_ref="wrong",
                client=client,
                reason_mode="coded",
            )
        )

    bad_content = key.model_copy(update={"applicant_content_id": "wrong"})
    with pytest.raises(ValueError, match="applicant_content_id"):
        asyncio.run(
            run_episode(
                key=bad_content,
                applicant=golden_clean_applicant,
                policy=policy,
                client=client,
                reason_mode="coded",
            )
        )

    bad_input = key.model_copy(update={"input_hash": "wrong"})
    with pytest.raises(ValueError, match="input_hash"):
        asyncio.run(
            run_episode(
                key=bad_input,
                applicant=golden_clean_applicant,
                policy=policy,
                client=client,
                reason_mode="coded",
            )
        )

    bad_prompt = key.model_copy(update={"prompt_hash": "wrong"})
    with pytest.raises(ValueError, match="prompt_hash"):
        asyncio.run(
            run_episode(
                key=bad_prompt,
                applicant=golden_clean_applicant,
                policy=policy,
                client=client,
                reason_mode="coded",
            )
        )

    bad_model = key.model_copy(update={"model_id": "different"})
    with pytest.raises(ValueError, match="model_id"):
        asyncio.run(
            run_episode(
                key=bad_model,
                applicant=golden_clean_applicant,
                policy=policy,
                client=client,
                reason_mode="coded",
            )
        )


class _UsageClient:
    model_id = "test:usage"

    def __init__(self):
        self.calls = 0

    async def complete(self, _req):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=(ToolCallRequested(call_id="c1", name="get_application"),),
                stop_reason="tool_calls",
                usage=Usage(
                    input_tokens=10,
                    output_tokens=2,
                    cached_tokens=3,
                    thought_tokens=4,
                    cost_usd=0.2,
                    cache_hit=True,
                ),
            )
        return ModelResponse(
            tool_calls=(
                ToolCallRequested(
                    call_id="c2",
                    name="submit_decision",
                    arguments={"outcome": "APPROVE", "reasons": []},
                ),
            ),
            stop_reason="tool_calls",
            usage=Usage(
                input_tokens=20,
                output_tokens=3,
                cached_tokens=5,
                thought_tokens=6,
                cost_usd=9.0,
                replayed=True,
            ),
        )


def test_usage_aggregation_preserves_all_fields_and_replay_is_zero_cost(
    golden_clean_applicant, policy
):
    client = _UsageClient()
    key = _key(golden_clean_applicant, policy, client)
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=golden_clean_applicant,
            policy=policy,
            client=client,
            reason_mode="coded",
        )
    )
    assert traj.usage == Usage(
        input_tokens=30,
        output_tokens=5,
        cached_tokens=8,
        thought_tokens=10,
        cost_usd=0.2,
        cache_hit=True,
        replayed=True,
    )

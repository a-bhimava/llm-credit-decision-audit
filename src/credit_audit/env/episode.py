"""The tool-calling loop. One implementation, shared by scripted agents (Phase 2) and
real LLM providers (Phase 9) alike -- it branches only on ``ModelResponse.stop_reason``
and ``.tool_calls``, never on which kind of :class:`~credit_audit.model.client.ModelClient`
it is talking to.
"""

from __future__ import annotations

from credit_audit.env.state import CreditEnvState, state_fingerprint
from credit_audit.env.tools import ReasonMode, build_system_prompt, dispatch, tool_specs
from credit_audit.ids import canonical_json, content_id
from credit_audit.model.client import ModelClient, ModelRequest
from credit_audit.policy.loader import Policy
from credit_audit.types import (
    Applicant,
    EpisodeKey,
    Message,
    Termination,
    ToolCall,
    Trajectory,
    Usage,
)


def _finalize(
    state: CreditEnvState,
    messages: list[Message],
    tool_calls: list[ToolCall],
    termination: Termination,
    usage: Usage,
) -> Trajectory:
    state = state.model_copy(update={"terminated": True, "termination": termination})
    fingerprint = state_fingerprint(state)
    trajectory_id = content_id({"key": state.episode_key, "fingerprint": fingerprint})
    return Trajectory(
        trajectory_id=trajectory_id,
        key=state.episode_key,
        messages=tuple(messages),
        tool_calls=tuple(tool_calls),
        final_state_hash=content_id(fingerprint),
        decision=state.decision,
        usage=usage,
        termination=termination,
    )


async def run_episode(
    *,
    key: EpisodeKey,
    applicant: Applicant,
    policy: Policy,
    application_text: str,
    applicant_ref: str,
    client: ModelClient,
    reason_mode: ReasonMode,
    max_steps: int | None = None,
) -> Trajectory:
    """Run one episode to completion and return its :class:`Trajectory`.

    ``state.step`` is the single source of truth for the step count -- bumped once per
    tool call (inside :func:`~credit_audit.env.tools.dispatch`) and once per
    no-tool-call turn (here), never tracked by a separate counter that could drift from
    it. A real scripted agent still goes through genuine tool calls
    (get_application, fetch_credit_report, submit_decision) rather than shortcutting
    straight to a Decision -- Phase 6's policy_adherence check needs to see whether the
    required tools were actually invoked.
    """
    effective_max_steps = max_steps if max_steps is not None else policy.process.max_steps
    state = CreditEnvState(
        episode_key=key,
        applicant=applicant,
        policy=policy,
        application_text=application_text,
        applicant_ref=applicant_ref,
        render_mode=key.render_id,
    )
    system = build_system_prompt(policy, reason_mode)
    specs = tool_specs(reason_mode)
    messages: list[Message] = []
    tool_calls: list[ToolCall] = []
    usage = Usage()

    while state.step < effective_max_steps:
        req = ModelRequest(
            model_id=key.model_id,
            system=system,
            messages=tuple(messages),
            tools=specs,
            temperature=None,
            top_p=None,
            max_tokens=None,
            seed=key.seed,
            env_state=state,
        )
        resp = await client.complete(req)
        usage = usage.model_copy(
            update={
                "input_tokens": usage.input_tokens + resp.usage.input_tokens,
                "output_tokens": usage.output_tokens + resp.usage.output_tokens,
                "cost_usd": usage.cost_usd + resp.usage.cost_usd,
            }
        )

        if resp.stop_reason == "refusal":
            return _finalize(state, messages, tool_calls, Termination.REFUSAL, usage)

        if resp.content:
            messages.append(Message(role="assistant", content=resp.content, step=state.step))

        if not resp.tool_calls:
            # A content-only turn still consumes a step -- otherwise an agent that never
            # calls a tool could loop forever without ever hitting max_steps.
            state = state.model_copy(update={"step": state.step + 1})
            continue

        for call in resp.tool_calls:
            result, state, is_terminal = dispatch(
                state, call.name, call.arguments, specs=specs, reason_mode=reason_mode
            )
            tool_calls.append(
                ToolCall(
                    step=state.step - 1,
                    name=call.name,
                    arguments=call.arguments,
                    result=result.data,
                    ok=result.ok,
                    error=result.error,
                )
            )
            messages.append(
                Message(
                    role="tool",
                    content=canonical_json(result.data).decode("utf-8"),
                    step=state.step,
                )
            )
            if is_terminal:
                return _finalize(state, messages, tool_calls, Termination.SUBMITTED, usage)
            if state.step >= effective_max_steps:
                break

    return _finalize(state, messages, tool_calls, Termination.MAX_STEPS, usage)


__all__ = ["run_episode"]

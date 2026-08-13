"""Provider-neutral episode execution and identity construction.

The same loop drives scripted controls and later hosted providers.  It preserves the
provider protocol as evidence: every assistant turn (including tool requests), every
correlated tool result, and every attempted call's provider ID and turn index.
"""

from __future__ import annotations

from credit_audit.env.state import CreditEnvState, state_fingerprint
from credit_audit.env.tools import ReasonMode, build_system_prompt, dispatch, tool_specs
from credit_audit.ids import (
    applicant_content_id,
    canonical_json,
    content_id,
    episode_input_hash,
    trajectory_content_id,
)
from credit_audit.model.client import (
    HarnessConfigurationError,
    ModelClient,
    ModelRequest,
)
from credit_audit.policy.loader import Policy
from credit_audit.render.packet import RenderOptions
from credit_audit.render.reference import applicant_reference_for
from credit_audit.render.registry import render_application
from credit_audit.types import (
    Applicant,
    EpisodeKey,
    FrozenDict,
    Message,
    RenderMode,
    RequestedToolCall,
    Termination,
    ToolCall,
    Trajectory,
    Usage,
    thaw_json,
)

_INITIAL_USER_TASK = (
    "Evaluate application {applicant_ref} under the supplied underwriting policy. "
    "Use the available tools to gather required information, then submit exactly one decision."
)


def initial_user_message(applicant_ref: str) -> str:
    """Return the canonical, provider-visible task message for one application."""
    return _INITIAL_USER_TASK.format(applicant_ref=applicant_ref)


def episode_prompt_hash(policy: Policy, reason_mode: ReasonMode) -> str:
    """Hash all byte-stable instructions fixed before an episode starts."""
    return content_id(
        {
            "system": build_system_prompt(policy, reason_mode),
            "initial_user_task_template": _INITIAL_USER_TASK,
            "tools": tool_specs(reason_mode),
        }
    )


def build_episode_key(
    *,
    applicant: Applicant,
    arm_id: str,
    render_id: RenderMode,
    trial_index: int,
    model_id: str,
    policy: Policy,
    reason_mode: ReasonMode,
    seed: int,
    render_options: RenderOptions | None = None,
) -> EpisodeKey:
    """Construct an :class:`EpisodeKey` without hand-authored identity hashes."""
    applicant_ref = applicant_reference_for(applicant)
    application_text = render_application(
        applicant,
        render_id,
        policy,
        options=render_options,
    )
    return EpisodeKey(
        applicant_id=applicant.applicant_id,
        applicant_content_id=applicant_content_id(applicant),
        arm_id=arm_id,
        render_id=render_id,
        trial_index=trial_index,
        model_id=model_id,
        prompt_hash=episode_prompt_hash(policy, reason_mode),
        input_hash=episode_input_hash(
            applicant,
            application_text=application_text,
            applicant_ref=applicant_ref,
            render_mode=render_id,
        ),
        seed=seed,
    )


def episode_context_hash(
    *,
    key: EpisodeKey,
    applicant: Applicant,
    policy: Policy,
    application_text: str,
    applicant_ref: str,
    reason_mode: ReasonMode,
) -> str:
    """Hash every episode input a scripted client could observe.

    Real providers only receive the prompt, messages, and tools, but scripted controls also
    read ``env_state``.  Including the complete applicant and the policy content hashes makes
    the generic response cache safe for both without caching the mutable state object itself.
    """
    return content_id(
        {
            "episode_id": key.episode_id,
            "applicant": applicant,
            "policy_md_sha256": policy.md_sha256,
            "policy_yaml_sha256": policy.yaml_sha256,
            "application_text": application_text,
            "applicant_ref": applicant_ref,
            "render_mode": key.render_id,
            "reason_mode": reason_mode,
        }
    )


def _add_usage(total: Usage, increment: Usage) -> Usage:
    """Aggregate all provider telemetry without losing boolean provenance flags."""
    return Usage(
        input_tokens=total.input_tokens + increment.input_tokens,
        output_tokens=total.output_tokens + increment.output_tokens,
        cached_tokens=total.cached_tokens + increment.cached_tokens,
        thought_tokens=total.thought_tokens + increment.thought_tokens,
        cost_usd=total.cost_usd + (0.0 if increment.replayed else increment.cost_usd),
        cache_hit=total.cache_hit or increment.cache_hit,
        replayed=total.replayed or increment.replayed,
    )


def _finalize(
    state: CreditEnvState,
    messages: list[Message],
    tool_calls: list[ToolCall],
    termination: Termination,
    usage: Usage,
    provider_state: FrozenDict | None = None,
) -> Trajectory:
    state = state.model_copy(update={"terminated": True, "termination": termination})
    fingerprint = state_fingerprint(state)
    episode_id = state.episode_key.episode_id
    return Trajectory(
        episode_id=episode_id,
        trajectory_id=trajectory_content_id(
            episode_id=episode_id,
            messages=tuple(messages),
            tool_calls=tuple(tool_calls),
            decision=state.decision,
            termination=termination,
        ),
        key=state.episode_key,
        messages=tuple(messages),
        tool_calls=tuple(tool_calls),
        final_state_hash=content_id(fingerprint),
        decision=state.decision,
        usage=usage,
        termination=termination,
        provider_state=provider_state or FrozenDict(),
    )


async def run_episode(
    *,
    key: EpisodeKey,
    applicant: Applicant,
    policy: Policy,
    application_text: str | None = None,
    applicant_ref: str | None = None,
    client: ModelClient,
    reason_mode: ReasonMode,
    max_steps: int | None = None,
    render_options: RenderOptions | None = None,
) -> Trajectory:
    """Run one validated episode to completion and return its semantic trajectory.

    ``applicant_ref`` is retained as a compatibility input, but callers no longer choose
    it: omitting it derives the canonical value, while supplying a mismatched value raises
    before any model call.  The key is similarly checked against the actual applicant,
    renderer, model client, and system prompt.
    """
    canonical_ref = applicant_reference_for(applicant)
    canonical_application_text = render_application(
        applicant,
        key.render_id,
        policy,
        options=render_options,
    )
    if application_text is not None and application_text != canonical_application_text:
        raise ValueError("application_text does not match the canonical renderer output")
    application_text = canonical_application_text
    if applicant_ref is not None and applicant_ref != canonical_ref:
        raise ValueError(
            f"applicant_ref does not match canonical reference: expected {canonical_ref!r}"
        )
    if key.applicant_id != applicant.applicant_id:
        raise ValueError("EpisodeKey applicant_id does not match applicant")
    expected_content_id = applicant_content_id(applicant)
    if key.applicant_content_id != expected_content_id:
        raise ValueError(
            f"EpisodeKey applicant_content_id does not match applicant ({expected_content_id})"
        )
    if key.model_id != client.model_id:
        raise ValueError("EpisodeKey model_id does not match ModelClient.model_id")
    expected_prompt_hash = episode_prompt_hash(policy, reason_mode)
    if key.prompt_hash != expected_prompt_hash:
        raise ValueError(
            "EpisodeKey prompt_hash does not match the canonical system prompt "
            f"({expected_prompt_hash})"
        )
    expected_input_hash = episode_input_hash(
        applicant,
        application_text=application_text,
        applicant_ref=canonical_ref,
        render_mode=key.render_id,
    )
    if key.input_hash != expected_input_hash:
        raise ValueError(
            "EpisodeKey input_hash does not match applicant, reference, render mode, "
            f"and application text ({expected_input_hash})"
        )

    effective_max_steps = max_steps if max_steps is not None else policy.process.max_steps
    state = CreditEnvState(
        episode_key=key,
        applicant=applicant,
        policy=policy,
        application_text=application_text,
        applicant_ref=canonical_ref,
        render_mode=key.render_id,
    )
    system = build_system_prompt(policy, reason_mode)
    specs = tool_specs(reason_mode)
    context_hash = episode_context_hash(
        key=key,
        applicant=applicant,
        policy=policy,
        application_text=application_text,
        applicant_ref=canonical_ref,
        reason_mode=reason_mode,
    )
    messages: list[Message] = [
        Message(role="system", content=system, step=0, turn_index=0),
        Message(
            role="user",
            content=initial_user_message(canonical_ref),
            step=0,
            turn_index=0,
        ),
    ]
    tool_calls: list[ToolCall] = []
    usage = Usage()
    turn_index = 0
    # Opaque provider continuation state, accumulated across turns. The runner never reads
    # into it; it only carries it forward so the adapter can echo it back verbatim.
    provider_state: dict[str, object] = {}

    while state.step < effective_max_steps:
        req = ModelRequest(
            model_id=key.model_id,
            system=system,
            # ``system`` has its own provider-neutral request field.  The trajectory keeps
            # a system-role Message for complete evidence, but it must not be sent twice.
            messages=tuple(message for message in messages if message.role != "system"),
            tools=specs,
            temperature=None,
            top_p=None,
            max_tokens=None,
            seed=key.seed,
            context_hash=context_hash,
            env_state=state,
            provider_state=FrozenDict(dict(provider_state)),
        )
        turn_index += 1
        try:
            resp = await client.complete(req)
        except HarnessConfigurationError:
            # Not something the model did. A misconfigured run must fail loudly rather than
            # accumulate ERROR trajectories that look like provider trouble.
            raise
        except Exception as exc:  # provider failures become evidence, not runner crashes
            messages.append(
                Message(
                    role="assistant",
                    content=f"[client error: {type(exc).__name__}: {exc}]",
                    step=state.step,
                    turn_index=turn_index,
                )
            )
            return _finalize(
                state,
                messages,
                tool_calls,
                Termination.ERROR,
                usage,
                FrozenDict(dict(provider_state)),
            )

        usage = _add_usage(usage, resp.usage)
        provider_state.update(thaw_json(resp.provider_state))
        requested = tuple(
            RequestedToolCall(
                call_id=call.call_id,
                name=call.name,
                arguments=call.arguments,
            )
            for call in resp.tool_calls
        )
        messages.append(
            Message(
                role="assistant",
                content=resp.content,
                step=state.step,
                turn_index=turn_index,
                tool_calls=requested,
            )
        )

        terminal_reason = {
            "stop": Termination.STOP,
            "refusal": Termination.REFUSAL,
            "max_tokens": Termination.MAX_TOKENS,
            "error": Termination.ERROR,
        }.get(resp.stop_reason)
        if terminal_reason is not None:
            return _finalize(
                state,
                messages,
                tool_calls,
                terminal_reason,
                usage,
                FrozenDict(dict(provider_state)),
            )

        if not resp.tool_calls:
            # A malformed/nonterminal response still consumes a step and cannot loop forever.
            state = state.model_copy(update={"step": state.step + 1})
            continue

        for call in resp.tool_calls:
            call_step = state.step
            result, state, is_terminal = dispatch(
                state, call.name, call.arguments, specs=specs, reason_mode=reason_mode
            )
            tool_calls.append(
                ToolCall(
                    call_id=call.call_id,
                    turn_index=turn_index,
                    step=call_step,
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
                    content=canonical_json(
                        {"ok": result.ok, "data": result.data, "error": result.error}
                    ).decode("utf-8"),
                    step=call_step,
                    turn_index=turn_index,
                    tool_call_id=call.call_id,
                )
            )
            if is_terminal:
                return _finalize(
                    state,
                    messages,
                    tool_calls,
                    Termination.SUBMITTED,
                    usage,
                    FrozenDict(dict(provider_state)),
                )
            if state.step >= effective_max_steps:
                break

    return _finalize(
        state, messages, tool_calls, Termination.MAX_STEPS, usage, FrozenDict(dict(provider_state))
    )


__all__ = [
    "build_episode_key",
    "episode_context_hash",
    "episode_prompt_hash",
    "initial_user_message",
    "run_episode",
]

"""The portable adapter: any OpenAI-compatible chat-completions endpoint.

One code path covers Gemini, OpenRouter, Together, Groq, and local vLLM/Ollama, because they
all speak the same wire format. That format is treated as an **escape hatch rather than an
abstraction** -- the point is optionality, not a promise that every provider behaves alike.
Where they differ, the difference is carried opaquely rather than normalized away.

Three things this adapter refuses to do:

* **Assume a parameter took effect.** Compat endpoints drop or reject unsupported fields
  silently -- `store`, `stream_options`, `logprobs`, `n > 1` among them. Nothing here infers
  that a request setting was honoured; usage is read from what came back.
* **Interpret provider state.** Gemini attaches ``extra_content.google.thought_signature`` to
  tool calls even through the compat endpoint, and replaying a tool call without it is a hard
  400 on thinking models. The adapter round-trips that blob byte-for-byte without parsing it,
  which is also what makes the mechanism work for the next provider that invents one.
* **Read the environment.** :attr:`ModelRequest.env_state` is invisible here by policy and by
  static check.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from credit_audit.env.types import ToolSpec
from credit_audit.model.client import ModelRequest, ModelResponse, ToolCallRequested
from credit_audit.model.providers.pricing import cost_usd
from credit_audit.types import FrozenDict, Message, Usage, thaw_json

GOOGLE_SIGNATURE_KEY = "thought_signature"
"""Where Gemini hides continuation state on a tool call, under ``extra_content.google``."""

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

StopReason = Literal["tool_calls", "stop", "refusal", "max_tokens", "error"]

_FINISH_REASONS: dict[str, StopReason] = {
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
    "stop": "stop",
    "length": "max_tokens",
    "content_filter": "refusal",
}


def finish_reason_to_stop_reason(finish_reason: str | None, *, has_tool_calls: bool) -> StopReason:
    """Translate a provider finish reason into the runner's terminal vocabulary.

    Tool calls win over the reported reason: some endpoints return ``stop`` alongside a
    populated ``tool_calls`` array, and treating that as a terminal stop would silently
    truncate the episode one turn early.
    """

    if has_tool_calls:
        return "tool_calls"
    if finish_reason is None:
        return "stop"
    return _FINISH_REASONS.get(finish_reason, "error")


def tool_to_openai(spec: ToolSpec) -> dict[str, Any]:
    """``ToolSpec.parameters`` is already JSON Schema, so this is a reshape, not a translation."""

    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": thaw_json(spec.parameters),
        },
    }


def messages_to_openai(
    system: str,
    messages: tuple[Message, ...],
    provider_state: FrozenDict,
) -> list[dict[str, Any]]:
    """Rebuild the wire conversation, re-attaching any provider state a turn is owed.

    The harness stores history as typed evidence records rather than as provider payloads,
    which is deliberate -- those records are what the bundle publishes. The cost is that
    anything the provider needs echoed back has to be re-attached here, from
    ``provider_state``, keyed by tool-call id.
    """

    state = thaw_json(provider_state) or {}
    wire: list[dict[str, Any]] = [{"role": "system", "content": system}]

    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            wire.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content,
                }
            )
            continue
        if message.role == "assistant" and message.tool_calls:
            calls: list[dict[str, Any]] = []
            for call in message.tool_calls:
                payload: dict[str, Any] = {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            thaw_json(call.arguments), sort_keys=True, separators=(",", ":")
                        ),
                    },
                }
                signature = state.get(call.call_id)
                if signature:
                    # Verbatim, unparsed. Omitting it is a 400 on a thinking model, and
                    # re-encoding it would be a subtler version of the same bug.
                    payload["extra_content"] = {"google": {GOOGLE_SIGNATURE_KEY: signature}}
                calls.append(payload)
            wire.append(
                {"role": "assistant", "content": message.content or None, "tool_calls": calls}
            )
            continue
        wire.append({"role": message.role, "content": message.content})
    return wire


def _extract_signature(call: Any) -> str | None:
    """Pull Gemini's continuation blob off a returned tool call, if the endpoint sent one."""

    extra = getattr(call, "extra_content", None)
    if extra is None and isinstance(call, dict):
        extra = call.get("extra_content")
    if not isinstance(extra, dict):
        return None
    google = extra.get("google")
    if not isinstance(google, dict):
        return None
    signature = google.get(GOOGLE_SIGNATURE_KEY)
    return signature if isinstance(signature, str) and signature else None


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string. A malformed one is evidence, not a crash."""

    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"__unparsed_arguments__": raw}
    return parsed if isinstance(parsed, dict) else {"__non_object_arguments__": parsed}


def response_from_openai(payload: Any, *, model_id: str) -> ModelResponse:
    """Map a chat-completion back into the runner's provider-neutral record."""

    choice = payload.choices[0] if payload.choices else None
    message = getattr(choice, "message", None)
    raw_calls = list(getattr(message, "tool_calls", None) or []) if message else []

    tool_calls: list[ToolCallRequested] = []
    signatures: dict[str, str] = {}
    for call in raw_calls:
        function = getattr(call, "function", None)
        call_id = getattr(call, "id", None) or f"call_{len(tool_calls)}"
        tool_calls.append(
            ToolCallRequested(
                call_id=call_id,
                name=getattr(function, "name", "") or "",
                arguments=FrozenDict(_parse_arguments(getattr(function, "arguments", None))),
            )
        )
        signature = _extract_signature(call)
        if signature:
            signatures[call_id] = signature

    usage_block = getattr(payload, "usage", None)
    input_tokens = int(getattr(usage_block, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage_block, "completion_tokens", 0) or 0)
    details = getattr(usage_block, "prompt_tokens_details", None)
    cached_tokens = int(getattr(details, "cached_tokens", 0) or 0)
    completion_details = getattr(usage_block, "completion_tokens_details", None)
    thought_tokens = int(getattr(completion_details, "reasoning_tokens", 0) or 0)

    # Measured from returned usage, never assumed from what we asked for.
    cost, priced = cost_usd(
        model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )

    return ModelResponse(
        content=(getattr(message, "content", None) or "") if message else "",
        tool_calls=tuple(tool_calls),
        stop_reason=finish_reason_to_stop_reason(
            getattr(choice, "finish_reason", None) if choice else None,
            has_tool_calls=bool(tool_calls),
        ),
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            thought_tokens=thought_tokens,
            cost_usd=cost,
            cache_hit=cached_tokens > 0,
        ),
        provider_state=FrozenDict(
            {
                **signatures,
                **({} if priced else {"__unpriced_model__": model_id}),
            }
        ),
    )


class OpenAICompatClient:
    """A :class:`~credit_audit.model.client.ModelClient` over any compat endpoint."""

    def __init__(
        self,
        model_id: str,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        provider: str = "openai_compat",
        timeout: float = 60.0,
        max_retries: int = 2,
        transport: Any | None = None,
    ) -> None:
        self.model_id = model_id
        self.provider = provider
        self._base_url = base_url
        if transport is not None:
            # Injected for tests: no network, no credentials, no SDK required.
            self._client = transport
            return
        try:
            from openai import AsyncOpenAI
        except ImportError as error:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "the openai package is required for OpenAICompatClient; "
                "install it with `pip install -e '.[providers]'`"
            ) from error
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

    def build_payload(self, req: ModelRequest) -> dict[str, Any]:
        """The exact request body, exposed so tests can assert it without a network call."""

        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": messages_to_openai(req.system, req.messages, req.provider_state),
        }
        if req.tools:
            payload["tools"] = [tool_to_openai(spec) for spec in req.tools]
            payload["tool_choice"] = "auto"
        # Only send what was asked for. An unset parameter is left off entirely rather than
        # sent as a default, because a compat endpoint may reject a field it does not know.
        if req.temperature is not None:
            payload["temperature"] = req.temperature
        if req.top_p is not None:
            payload["top_p"] = req.top_p
        if req.max_tokens is not None:
            payload["max_tokens"] = req.max_tokens
        return payload

    async def complete(self, req: ModelRequest) -> ModelResponse:
        payload = self.build_payload(req)
        completion = await self._client.chat.completions.create(**payload)
        return response_from_openai(completion, model_id=self.model_id)


__all__ = [
    "DEFAULT_BASE_URL",
    "GOOGLE_SIGNATURE_KEY",
    "OpenAICompatClient",
    "finish_reason_to_stop_reason",
    "messages_to_openai",
    "response_from_openai",
    "tool_to_openai",
]

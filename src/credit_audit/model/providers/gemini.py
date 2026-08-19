"""Native Gemini adapter, for the telemetry the compatibility layer does not expose.

The OpenAI-compatible endpoint covers Gemini for everything this harness does, so this adapter
is not about capability. It exists for one number: ``cached_content_token_count``. The roadmap
is explicit that prompt-cache behaviour must be **measured from provider-reported usage, never
asserted** -- the ~4 KB shared prefix here is around a thousand tokens, below every published
implicit-cache minimum, so a claim that caching is doing work would almost certainly be wrong.
Reading the counter is how that stays honest.

Two shape differences from the compat path, both handled here rather than pushed outward:

* Roles are ``user`` and ``model``, and a tool result is a ``function_response`` part on a
  user turn rather than a ``tool``-role message.
* ``thought_signature`` sits on the **Part**, not on the function call inside it. It is still
  carried opaquely through the same ``provider_state`` channel, so the runner and the cassette
  cannot tell the two adapters apart.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from credit_audit.env.types import ToolSpec
from credit_audit.model.client import ModelRequest, ModelResponse, ToolCallRequested
from credit_audit.model.providers.pricing import cost_usd
from credit_audit.types import FrozenDict, Message, Usage, thaw_json

DEFAULT_MODEL = "gemini-2.5-flash-lite"

StopReason = Literal["tool_calls", "stop", "refusal", "max_tokens", "error"]

_FINISH_REASONS: dict[str, StopReason] = {
    "STOP": "stop",
    "MAX_TOKENS": "max_tokens",
    "SAFETY": "refusal",
    "RECITATION": "refusal",
    "PROHIBITED_CONTENT": "refusal",
    "BLOCKLIST": "refusal",
    "SPII": "refusal",
}


def finish_reason_to_stop_reason(finish_reason: Any, *, has_tool_calls: bool) -> StopReason:
    """Same precedence rule as the compat adapter: a tool call outranks a reported stop.

    Gemini reports ``STOP`` alongside function calls, so believing the finish reason would end
    the episode a turn early and the decision would never be submitted.
    """

    if has_tool_calls:
        return "tool_calls"
    if finish_reason is None:
        return "stop"
    name = getattr(finish_reason, "name", None) or str(finish_reason).rsplit(".", 1)[-1]
    return _FINISH_REASONS.get(name.upper(), "error")


def tool_to_gemini(spec: ToolSpec) -> dict[str, Any]:
    """``ToolSpec.parameters`` is JSON Schema, which is what a FunctionDeclaration wants."""

    return {
        "name": spec.name,
        "description": spec.description,
        "parameters": thaw_json(spec.parameters),
    }


def messages_to_contents(
    messages: tuple[Message, ...], provider_state: FrozenDict
) -> list[dict[str, Any]]:
    """Rebuild the conversation in Gemini's shape, re-attaching signatures to their parts.

    The system prompt is deliberately absent: it travels as ``system_instruction`` on the
    config, not as a turn, so it is not repeated in the history.
    """

    state = thaw_json(provider_state) or {}
    contents: list[dict[str, Any]] = []

    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "function_response": {
                                "name": message.tool_call_id or "",
                                "response": _as_object(message.content),
                            }
                        }
                    ],
                }
            )
            continue
        if message.role == "assistant" and message.tool_calls:
            parts: list[dict[str, Any]] = []
            for call in message.tool_calls:
                part: dict[str, Any] = {
                    "function_call": {
                        "id": call.call_id,
                        "name": call.name,
                        "args": thaw_json(call.arguments),
                    }
                }
                signature = state.get(call.call_id)
                if signature:
                    # On the Part, not inside the call. Verbatim either way.
                    part["thought_signature"] = signature
                parts.append(part)
            contents.append({"role": "model", "parts": parts})
            continue
        contents.append(
            {
                "role": "model" if message.role == "assistant" else "user",
                "parts": [{"text": message.content}],
            }
        )
    return contents


def _as_object(raw: str) -> dict[str, Any]:
    """A function response must be an object. Malformed content becomes evidence, not a crash."""

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"result": raw}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def response_from_gemini(payload: Any, *, model_id: str) -> ModelResponse:
    """Map a ``GenerateContentResponse`` into the runner's provider-neutral record."""

    candidates = getattr(payload, "candidates", None) or []
    candidate = candidates[0] if candidates else None
    content = getattr(candidate, "content", None)
    parts = list(getattr(content, "parts", None) or [])

    text_chunks: list[str] = []
    tool_calls: list[ToolCallRequested] = []
    signatures: dict[str, str] = {}

    for index, part in enumerate(parts):
        call = getattr(part, "function_call", None)
        if call is not None:
            call_id = getattr(call, "id", None) or f"call_{index}"
            tool_calls.append(
                ToolCallRequested(
                    call_id=call_id,
                    name=getattr(call, "name", "") or "",
                    arguments=FrozenDict(dict(getattr(call, "args", None) or {})),
                )
            )
            signature = getattr(part, "thought_signature", None)
            if signature:
                signatures[call_id] = _as_text(signature)
            continue
        text = getattr(part, "text", None)
        if text:
            text_chunks.append(text)

    usage_block = getattr(payload, "usage_metadata", None)
    input_tokens = int(getattr(usage_block, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(usage_block, "candidates_token_count", 0) or 0)
    # The number this adapter exists for. Reported by the provider, never inferred from
    # whether we think the prefix should have been cacheable.
    cached_tokens = int(getattr(usage_block, "cached_content_token_count", 0) or 0)
    thought_tokens = int(getattr(usage_block, "thoughts_token_count", 0) or 0)

    cost, priced = cost_usd(
        model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )

    return ModelResponse(
        content="".join(text_chunks),
        tool_calls=tuple(tool_calls),
        stop_reason=finish_reason_to_stop_reason(
            getattr(candidate, "finish_reason", None), has_tool_calls=bool(tool_calls)
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
            {**signatures, **({} if priced else {"__unpriced_model__": model_id})}
        ),
    )


def _as_text(value: Any) -> str:
    """Signatures arrive as bytes or str depending on transport; store one shape."""

    if isinstance(value, bytes):
        import base64

        return base64.b64encode(value).decode("ascii")
    return str(value)


class GeminiClient:
    """Native :class:`~credit_audit.model.client.ModelClient` over ``google-genai``."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL,
        *,
        api_key: str | None = None,
        provider: str = "gemini",
        vertexai: bool = False,
        location: str | None = None,
        project: str | None = None,
        transport: Any | None = None,
    ) -> None:
        self.model_id = model_id
        self.provider = provider
        if transport is not None:
            self._client = transport
            return
        try:
            from google import genai
        except ImportError as error:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "the google-genai package is required for GeminiClient; "
                "install it with `pip install -e '.[gemini]'`"
            ) from error
        if vertexai:
            self._client = genai.Client(vertexai=True, location=location, project=project)
        else:
            self._client = genai.Client(api_key=api_key)

    def build_config(self, req: ModelRequest) -> dict[str, Any]:
        """The config body, exposed so tests can assert it without a network call."""

        config: dict[str, Any] = {"system_instruction": req.system}
        if req.tools:
            config["tools"] = [
                {"function_declarations": [tool_to_gemini(spec) for spec in req.tools]}
            ]
        # Only what was asked for. Gemini rejects some unset combinations outright, and
        # sending a default we did not choose would be a parameter we never verified took
        # effect.
        if req.temperature is not None:
            config["temperature"] = req.temperature
        if req.top_p is not None:
            config["top_p"] = req.top_p
        if req.max_tokens is not None:
            config["max_output_tokens"] = req.max_tokens
        return config

    async def complete(self, req: ModelRequest) -> ModelResponse:
        response = await self._client.aio.models.generate_content(
            model=self.model_id,
            contents=messages_to_contents(req.messages, req.provider_state),
            config=self.build_config(req),
        )
        return response_from_gemini(response, model_id=self.model_id)


__all__ = [
    "DEFAULT_MODEL",
    "GeminiClient",
    "finish_reason_to_stop_reason",
    "messages_to_contents",
    "response_from_gemini",
    "tool_to_gemini",
]

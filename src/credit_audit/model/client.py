"""The provider-agnostic model interface.

``ModelClient`` is implemented identically by scripted agents (this phase) and, in Phase
9, real LLM providers. :func:`credit_audit.env.episode.run_episode` branches only on
``ModelResponse.stop_reason`` and ``.tool_calls`` -- it never knows or cares which kind of
client it is talking to.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import Field

from credit_audit.env.state import CreditEnvState
from credit_audit.env.types import ToolSpec
from credit_audit.types import Frozen, FrozenDict, Message, RequestedToolCall, Usage


class ToolCallRequested(RequestedToolCall):
    """Backward-compatible public name for the shared protocol record."""


class ModelRequest(Frozen):
    model_id: str
    system: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...]
    temperature: float | None
    top_p: float | None
    max_tokens: int | None
    seed: int
    context_hash: str
    """Hash of applicant/render/policy input context, included in every cache key."""
    env_state: CreditEnvState
    """Scripted- and cassette-only. A real provider adapter must never read this field -- it
    only ever sees rendered text and tool results, exactly like a real model would.
    ``tests/model/test_provider_isolation.py`` asserts nothing under ``model/providers/``
    references ``.env_state``, mirroring the numeric-lint style of defense-by-static-check
    already used in policy/loader.py."""

    provider_state: FrozenDict = Field(default_factory=FrozenDict)
    """Opaque provider continuation state accumulated from earlier turns of this episode.

    Some providers require state echoed back verbatim on the next request -- Gemini's
    ``thought_signature`` on tool calls being the case in point, where omitting it is a hard
    400 rather than a degradation. The runner rebuilds each request from typed ``Message``
    records, so there is nowhere in the semantic history for such a blob to ride along; this
    field is that channel.

    It is deliberately opaque and deliberately **not** part of any content identity. It is
    absent from :func:`~credit_audit.model.cache.cache_key`'s field list, because it is
    derived from ``messages``, which is already hashed. Two runs that differ only in an
    encrypted provider token stay comparable, which is exactly what would be lost by folding
    it into the semantic hash.
    """


class ModelResponse(Frozen):
    content: str = ""
    tool_calls: tuple[ToolCallRequested, ...] = ()
    stop_reason: Literal["tool_calls", "stop", "refusal", "max_tokens", "error"] = "stop"
    usage: Usage = Usage()

    provider_state: FrozenDict = Field(default_factory=FrozenDict)
    """Provider state this response wants echoed back on the next request.

    Keyed by whatever the adapter needs to correlate it -- tool-call id for Gemini thought
    signatures. The runner merges it into the accumulated
    :attr:`ModelRequest.provider_state` and never interprets it.
    """


class ModelClient(Protocol):
    model_id: str

    async def complete(self, req: ModelRequest) -> ModelResponse: ...


__all__ = ["ModelClient", "ModelRequest", "ModelResponse", "ToolCallRequested"]

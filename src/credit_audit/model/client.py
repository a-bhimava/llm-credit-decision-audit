"""The provider-agnostic model interface.

``ModelClient`` is implemented identically by scripted agents (this phase) and, in Phase
9, real LLM providers. :func:`credit_audit.env.episode.run_episode` branches only on
``ModelResponse.stop_reason`` and ``.tool_calls`` -- it never knows or cares which kind of
client it is talking to.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from credit_audit.env.state import CreditEnvState
from credit_audit.env.types import ToolSpec
from credit_audit.types import Frozen, Message, Usage


class ToolCallRequested(Frozen):
    call_id: str
    name: str
    arguments: dict[str, Any]


class ModelRequest(Frozen):
    model_id: str
    system: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...]
    temperature: float | None
    top_p: float | None
    max_tokens: int | None
    seed: int
    env_state: CreditEnvState
    """Scripted- and cassette-only. A real provider adapter (Phase 9) must never read this
    field -- it only ever sees rendered text and tool results, exactly like a real model
    would. Phase 9 adds a grep-style static check asserting nothing under
    model/providers/ references ``.env_state``, mirroring the numeric-lint style of
    defense-by-static-check already used in policy/loader.py."""


class ModelResponse(Frozen):
    content: str = ""
    tool_calls: tuple[ToolCallRequested, ...] = ()
    stop_reason: Literal["tool_calls", "stop", "refusal", "max_tokens", "error"] = "stop"
    usage: Usage = Usage()


class ModelClient(Protocol):
    model_id: str

    async def complete(self, req: ModelRequest) -> ModelResponse: ...


__all__ = ["ModelClient", "ModelRequest", "ModelResponse", "ToolCallRequested"]

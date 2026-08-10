"""Content-addressed response cache, and a wrapper usable by ANY :class:`ModelClient` --
scripted or real -- so :func:`~credit_audit.env.episode.run_episode` never needs a
scripted-vs-real branch, and the "kill the process mid-run and resume" property the wider
architecture depends on gets exercised by scripted suites too, at $0, in CI.
"""

from __future__ import annotations

import gzip
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from credit_audit.env.types import ToolSpec
from credit_audit.ids import content_id
from credit_audit.model.client import ModelClient, ModelRequest, ModelResponse
from credit_audit.types import Message


def cache_key(
    *,
    provider: str,
    model_id: str,
    params: Mapping[str, Any],
    system: str,
    messages: tuple[Message, ...],
    tools: tuple[ToolSpec, ...],
) -> str:
    """Deliberately excludes ``req.env_state`` -- see model/client.py's docstring on why
    that is correct rather than a gap: applicant-specific facts already flow through
    ``messages`` via prior tool results. Deliberately includes ``seed`` inside
    ``params`` (trial-unique by construction), so real trials at temperature>0 get
    distinct cache slots instead of one draw silently reused across all k trials.
    """
    return content_id(
        {
            "provider": provider,
            "model_id": model_id,
            "params": dict(params),
            "system": system,
            "messages": messages,
            "tools": tools,
        }
    )


class ResponseCache:
    """Sharded on disk by the first two hex characters of the content digest."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        digest = key.split(":", 1)[1]
        return self.root / digest[:2] / f"{digest}.json.gz"

    def get(self, key: str) -> ModelResponse | None:
        path = self._path(key)
        if not path.exists():
            return None
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return ModelResponse.model_validate_json(handle.read())

    def put(self, key: str, response: ModelResponse) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as handle:
            handle.write(response.model_dump_json())
        os.replace(tmp, path)


class CachedClient:
    """Wraps ANY ModelClient uniformly -- scripted or real. Scripted responses are
    cached too, even though they're already free and instant: not for cost, but so this
    wrapper needs no scripted-vs-real branch, and so resumability is exercised by
    scripted suites at zero economic cost."""

    def __init__(self, inner: ModelClient, cache: ResponseCache, *, provider: str):
        self.inner = inner
        self.cache = cache
        self.provider = provider
        self.model_id = inner.model_id

    async def complete(self, req: ModelRequest) -> ModelResponse:
        key = cache_key(
            provider=self.provider,
            model_id=req.model_id,
            params={
                "temperature": req.temperature,
                "top_p": req.top_p,
                "max_tokens": req.max_tokens,
                "seed": req.seed,
            },
            system=req.system,
            messages=req.messages,
            tools=req.tools,
        )
        cached = self.cache.get(key)
        if cached is not None:
            return cached.model_copy(
                update={"usage": cached.usage.model_copy(update={"replayed": True})}
            )
        response = await self.inner.complete(req)
        self.cache.put(key, response)
        return response


__all__ = ["CachedClient", "ResponseCache", "cache_key"]

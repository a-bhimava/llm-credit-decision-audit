"""Record and replay provider responses at the protocol boundary.

This is not VCR, and the difference is the point. VCR records **HTTP**; this records
``ModelRequest -> ModelResponse``. Three properties follow from that choice and none of them
survive at the HTTP layer:

* **Replay is provider-independent.** A cassette recorded through the compat endpoint replays
  through the native adapter, because what was captured is the protocol, not the transport.
* **Keys are the ones the pipeline already uses.** :func:`~credit_audit.model.cache.cache_key`
  hashes every provider-visible request field plus episode context. Deriving a second key from
  HTTP bodies would be a second thing to keep correct.
* **Records populate the published contract.** ``schemas/export/replay@1`` is keyed on
  ``episode_id`` / ``trajectory_id`` / ``pair_id``, none of which exist in an HTTP body.

``vcrpy`` is still the right tool for asserting our *wire format* against a real provider's
bytes, and the adapter tests use it there. Both layers, each with the tool that fits it.

**Modes.** ``off`` passes through. ``record`` always calls the provider and writes. ``replay``
never calls it and raises on a miss -- the CI setting, because a silent fallthrough to the
network is how a test suite starts costing money. ``replay_or_record`` fills gaps, which is
what you want while building a cassette incrementally.
"""

from __future__ import annotations

import gzip
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from credit_audit.ids import sha256_bytes
from credit_audit.model.cache import cache_key
from credit_audit.model.client import (
    HarnessConfigurationError,
    ModelClient,
    ModelRequest,
    ModelResponse,
)
from credit_audit.types import Frozen


class CassetteMode(StrEnum):
    OFF = "off"
    RECORD = "record"
    REPLAY = "replay"
    REPLAY_OR_RECORD = "replay_or_record"


class CassetteMiss(HarnessConfigurationError):
    """Raised in ``replay`` mode when no record matches.

    Deliberately fatal, and deliberately *not* swallowed as a provider failure. Falling
    through to a live call would turn an offline suite into one that quietly bills you; being
    recorded as an ``ERROR`` trajectory would be worse still, because the run would finish
    green having replayed nothing at all. Pointing a run at the wrong cassette is a mistake
    about the harness, so it stops the run.
    """


class CassetteEntry(Frozen):
    key: str
    provider: str
    model_id: str
    recorded_at: str
    response: ModelResponse
    request_digest: str = ""
    """sha256 of the canonical request body, for a reader who wants to confirm the record
    belongs to the request that claims it."""


class Cassette:
    """A directory of recorded responses, sharded like the response cache."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        digest = key.split(":", 1)[1]
        return self.root / digest[:2] / f"{digest}.json.gz"

    def __contains__(self, key: str) -> bool:
        return self._path(key).exists()

    def get(self, key: str) -> CassetteEntry | None:
        path = self._path(key)
        if not path.exists():
            return None
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return CassetteEntry.model_validate_json(handle.read())

    def put(self, entry: CassetteEntry) -> None:
        """Write atomically, after refusing anything that looks like a credential.

        The export-time secret scan already guards the bundle. Scanning here as well means a
        key never reaches disk in the first place, which is the only version of that guarantee
        worth having.
        """

        from credit_audit.report.bundle import scan_for_secrets

        payload = entry.model_dump_json().encode("utf-8")
        scan_for_secrets(f"cassette:{entry.key}", payload)

        path = self._path(entry.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            with gzip.open(tmp, "wt", encoding="utf-8") as handle:
                handle.write(entry.model_dump_json())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def entries(self) -> tuple[CassetteEntry, ...]:
        found = [
            entry
            for path in sorted(self.root.rglob("*.json.gz"))
            if (entry := self._read(path)) is not None
        ]
        return tuple(sorted(found, key=lambda entry: entry.key))

    def _read(self, path: Path) -> CassetteEntry | None:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return CassetteEntry.model_validate_json(handle.read())
        except (OSError, ValueError):  # pragma: no cover - corrupt record
            return None


def request_params(req: ModelRequest) -> Mapping[str, Any]:
    """The generation parameters that belong in the key.

    ``seed`` is included so repeated trials of a stochastic model never collapse onto one
    recorded draw. ``provider_state`` is excluded: it is derived from ``messages``, which is
    already hashed, so including it would make otherwise-identical requests miss.
    """

    return {
        "temperature": req.temperature,
        "top_p": req.top_p,
        "max_tokens": req.max_tokens,
        "seed": req.seed,
    }


class CassetteClient:
    """Wraps any :class:`ModelClient` with record/replay, without the wrapped client knowing."""

    def __init__(
        self,
        inner: ModelClient,
        cassette: Cassette,
        *,
        mode: CassetteMode = CassetteMode.REPLAY,
        provider: str = "openai_compat",
        now: Any = None,
    ) -> None:
        self._inner = inner
        self._cassette = cassette
        self._mode = CassetteMode(mode)
        self._provider = provider
        self._now = now or (lambda: datetime.now(UTC).isoformat())
        self.model_id = inner.model_id

    @property
    def mode(self) -> CassetteMode:
        return self._mode

    def key_for(self, req: ModelRequest) -> str:
        return cache_key(
            provider=self._provider,
            model_id=self.model_id,
            params=request_params(req),
            system=req.system,
            messages=req.messages,
            tools=req.tools,
            context_hash=req.context_hash,
        )

    async def complete(self, req: ModelRequest) -> ModelResponse:
        if self._mode is CassetteMode.OFF:
            return await self._inner.complete(req)

        key = self.key_for(req)

        if self._mode in (CassetteMode.REPLAY, CassetteMode.REPLAY_OR_RECORD):
            entry = self._cassette.get(key)
            if entry is not None:
                self._require_same_model(entry, key)
                # Replay costs nothing in the current run, and says so. The manifest's
                # `current_run_cost` flag depends on this being honest.
                return entry.response.model_copy(
                    update={
                        "usage": entry.response.usage.model_copy(
                            update={"replayed": True, "cost_usd": 0.0}
                        )
                    }
                )
            if self._mode is CassetteMode.REPLAY:
                raise CassetteMiss(
                    f"no recorded response for {key} at {self._cassette.root}. "
                    "Replay mode never calls the provider; re-record with "
                    "--cassette-mode replay_or_record and an explicit --max-usd."
                )

        response = await self._inner.complete(req)
        self._cassette.put(
            CassetteEntry(
                key=key,
                provider=self._provider,
                model_id=self.model_id,
                recorded_at=self._now(),
                response=response,
                request_digest=sha256_bytes(
                    json.dumps(
                        {"system": req.system, "context_hash": req.context_hash},
                        sort_keys=True,
                    ).encode("utf-8")
                ),
            )
        )
        return response

    def _require_same_model(self, entry: CassetteEntry, key: str) -> None:
        """A recording made against another model is not evidence about this one.

        The key already covers ``model_id``, so this can only trigger on a hand-edited or
        merged cassette -- which is exactly when a silent substitution would be most damaging
        and least visible.
        """

        if entry.model_id != self.model_id:
            raise CassetteMiss(
                f"record {key} was made against {entry.model_id!r} but this run is "
                f"{self.model_id!r}; a replay may not stand in for a different model"
            )


__all__ = [
    "Cassette",
    "CassetteClient",
    "CassetteEntry",
    "CassetteMiss",
    "CassetteMode",
    "request_params",
]

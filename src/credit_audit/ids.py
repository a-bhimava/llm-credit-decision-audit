"""Content addressing and seed derivation.

Everything here exists to make the pipeline reproducible and the exported evidence bundle
byte-deterministic. That single property is what later buys the integrity story (a stranger can
re-run the exporter and ``diff -r`` the result against what the site serves) and the CI
staleness gate. Retrofitting determinism is miserable, so it is built in from the first commit.

Two hash functions are used deliberately:

* **blake2b-128** (``blake2b128:`` prefix) for internal content-addressed IDs -- fast, and we
  hash a great many small objects.
* **sha256** (``sha256:`` prefix) for the published ``SHA256SUMS`` integrity manifest, because
  ``shasum -a 256 -c`` is available on every machine a skeptic might use.

The evidence site documents this split rather than leaving a reviewer to wonder why two hash
functions appear in the same bundle.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from credit_audit.types import Applicant, RenderMode

FLOAT_FORMAT = "ieee-754-hex"
"""Finite floats use Python's lossless, platform-stable IEEE-754 hexadecimal form."""

_SEP = b"\x1f"  # ASCII unit separator; cannot appear in the identifier strings we join.


def _hex_float(value: float) -> str:
    """Lossless, platform-stable IEEE-754 hexadecimal form, for hash inputs."""

    return value.hex()


def _plain_float(value: float) -> float:
    """The float itself, for wire formats.

    ``json.dumps`` writes floats through ``repr``, which is the shortest string that
    round-trips exactly. It is lossless and injective for finite doubles, so it is as safe as
    the hexadecimal form for equality -- it is simply not what a hash input should look like.
    """

    return value


def _normalize(obj: Any, *, floats: Any = _hex_float) -> Any:
    """Recursively convert to a JSON-safe structure with a total, stable ordering.

    Bool is checked before int because ``bool`` subclasses ``int``. Enum is checked before str
    because ``StrEnum`` subclasses ``str`` and we want the plain value, not the member repr.

    ``floats`` selects how finite floats are rendered; see :func:`canonical_json` and
    :func:`portable_json`. Non-finite floats are rejected under both.
    """
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, Enum):
        return _normalize(obj.value, floats=floats)
    if isinstance(obj, BaseModel):
        return {
            name: _normalize(getattr(obj, name), floats=floats)
            for name in sorted(type(obj).model_fields)
        }
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, float):
        # Rejected here rather than by json.dumps(allow_nan=False): floats may be formatted to
        # strings before they reach the encoder, so NaN would otherwise serialize as the
        # literal "nan" -- a garbage value that looks like data in a published bundle.
        if not math.isfinite(obj):
            raise ValueError(f"non-finite float cannot be canonicalized: {obj!r}")
        # Normalize signed zero, then retain every other IEEE-754 bit. Quantizing here can
        # make distinct decisions share a content identity.
        return floats(obj + 0.0 if obj else 0.0)
    if isinstance(obj, int):
        return obj
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return obj.as_posix()
    if isinstance(obj, Mapping):
        return {
            str(k): _normalize(v, floats=floats)
            for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(obj, (set, frozenset)):
        return sorted(_normalize(v, floats=floats) for v in obj)
    if isinstance(obj, Sequence):
        return [_normalize(v, floats=floats) for v in obj]
    raise TypeError(f"cannot canonicalize {type(obj).__name__}")


def _dumps(normalized: Any) -> bytes:
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json(obj: Any) -> bytes:
    """Deterministic UTF-8 JSON bytes for **hashing**.

    Sorted keys, no whitespace, ``Decimal`` as string, finite floats losslessly encoded in
    IEEE-754 hexadecimal form, and NaN/Infinity rejected. Two structurally equal objects always
    produce identical bytes, on any platform.

    The hexadecimal float form is why this is not also the wire format: it hashes beautifully
    and reads back as a string, not a number.
    """
    return _dumps(_normalize(obj))


def portable_json(obj: Any) -> bytes:
    """Deterministic UTF-8 JSON bytes for **artifacts and the exported bundle**.

    Identical to :func:`canonical_json` except that finite floats are written as ordinary JSON
    numbers, so the file round-trips through any JSON parser and a browser can read a rate as
    a rate. Ordering and whitespace are equally fixed, so byte-determinism is preserved: this
    is the form the export gate diffs.
    """
    return _dumps(_normalize(obj, floats=_plain_float))


def content_id(obj: Any, *, digest_size: int = 16) -> str:
    """Content-addressed identifier, e.g. ``blake2b128:4f2ab9c1...``."""
    digest = hashlib.blake2b(canonical_json(obj), digest_size=digest_size).hexdigest()
    return f"blake2b{digest_size * 8}:{digest}"


def short_id(obj: Any, *, length: int = 8) -> str:
    """Unprefixed short hash, for human-facing identifiers like ``pair_0f3a91``."""
    return hashlib.blake2b(canonical_json(obj), digest_size=16).hexdigest()[:length]


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def sha256_file(path: str | Path, *, chunk_size: int = 1 << 20) -> str:
    """Streaming sha256 of a file, prefixed. Used for the integrity manifest."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def derive_seed(run_seed: int, *parts: str | int) -> int:
    """Hierarchical seed derivation.

    A single global RNG stream is the classic way to destroy an experiment: adding profile #226
    shifts the draws for profiles 1-225 and nothing is comparable across runs any more. Deriving
    each seed from ``(run_seed, applicant_id, arm_id, trial_index)`` makes every draw
    independently addressable and stable under insertion.

    Returns a non-negative 63-bit integer, which is safe to hand to ``numpy.random.default_rng``
    and to ``random.Random``.
    """
    digest = hashlib.blake2b(digest_size=8)
    digest.update(str(run_seed).encode("utf-8"))
    for part in parts:
        digest.update(_SEP)
        digest.update(str(part).encode("utf-8"))
    return int.from_bytes(digest.digest(), "big") & ((1 << 63) - 1)


def applicant_content_id(applicant: Applicant) -> str:
    """Content identity for one rendered experimental variant.

    ``Applicant.applicant_id`` deliberately remains the stable selected experimental
    unit.  Facts and presentation can change across intervention arms, so callers that
    need to distinguish those variants use this separate content-addressed identifier.
    Provenance is intentionally excluded: two records shown to a model are the same
    variant when their facts and presentation are identical, regardless of how they were
    constructed.
    """

    return content_id({"facts": applicant.facts, "presentation": applicant.presentation})


def episode_input_hash(
    applicant: Applicant,
    *,
    application_text: str,
    applicant_ref: str,
    render_mode: RenderMode,
) -> str:
    """Address every applicant-specific input fixed before an episode starts.

    The stable ``applicant_id`` names the selected experimental unit; this hash names the
    exact variant and provider-visible rendering used for one arm.  Keeping it in the
    :class:`~credit_audit.types.EpisodeKey` prevents two variants from sharing an episode
    identity and lets the runner reject application text that no longer matches its key.
    """

    return content_id(
        {
            "applicant_content_id": applicant_content_id(applicant),
            "application_text": application_text,
            "applicant_ref": applicant_ref,
            "render_mode": render_mode,
        }
    )


def trajectory_content_id(
    *,
    episode_id: str,
    messages: Any,
    tool_calls: Any,
    decision: Any,
    termination: Any,
) -> str:
    """Hash the realized semantic history retained as trajectory evidence."""

    semantic_tool_calls = tuple(
        {
            "call_id": call.call_id,
            "turn_index": call.turn_index,
            "step": call.step,
            "name": call.name,
            "arguments": call.arguments,
            "result": call.result,
            "ok": call.ok,
            "error": call.error,
        }
        for call in tool_calls
    )
    return content_id(
        {
            "episode_id": episode_id,
            "messages": messages,
            "tool_calls": semantic_tool_calls,
            "decision": decision,
            "termination": termination,
        }
    )


def cluster_id_for(applicant: Applicant) -> str:
    """Stable resampling cluster for an applicant and all of its sibling variants.

    Generator-created siblings carry the original selected applicant in
    ``parent_applicant_id``.  Root profiles cluster on their own selected id.  This is
    distinct from a contrast's ``pair_id``: many pairs may legitimately belong to one
    source-applicant cluster.
    """

    root = applicant.provenance.parent_applicant_id or applicant.applicant_id
    return f"cluster_{short_id({'source_applicant_id': root}, length=16)}"


__all__ = [
    "FLOAT_FORMAT",
    "applicant_content_id",
    "canonical_json",
    "cluster_id_for",
    "content_id",
    "derive_seed",
    "episode_input_hash",
    "portable_json",
    "sha256_bytes",
    "sha256_file",
    "short_id",
    "trajectory_content_id",
]

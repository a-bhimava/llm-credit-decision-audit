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
from typing import Any

from pydantic import BaseModel

FLOAT_FORMAT = "{:.6f}"
"""Floats are serialized at fixed precision. Repr differences across platforms and Python
versions would otherwise break byte-determinism for values that are numerically identical."""

_SEP = b"\x1f"  # ASCII unit separator; cannot appear in the identifier strings we join.


def _normalize(obj: Any) -> Any:
    """Recursively convert to a JSON-safe structure with a total, stable ordering.

    Bool is checked before int because ``bool`` subclasses ``int``. Enum is checked before str
    because ``StrEnum`` subclasses ``str`` and we want the plain value, not the member repr.
    """
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, Enum):
        return _normalize(obj.value)
    if isinstance(obj, BaseModel):
        return {name: _normalize(getattr(obj, name)) for name in sorted(type(obj).model_fields)}
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, float):
        # Rejected here rather than by json.dumps(allow_nan=False): floats are formatted to
        # strings before they reach the encoder, so NaN would otherwise serialize as the
        # literal "nan" -- a garbage value that looks like data in a published bundle.
        if not math.isfinite(obj):
            raise ValueError(f"non-finite float cannot be canonicalized: {obj!r}")
        # Normalize signed zero so -0.0 and 0.0 produce identical bytes.
        return FLOAT_FORMAT.format(obj + 0.0 if obj else 0.0)
    if isinstance(obj, int):
        return obj
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return obj.as_posix()
    if isinstance(obj, Mapping):
        return {str(k): _normalize(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (set, frozenset)):
        return sorted(_normalize(v) for v in obj)
    if isinstance(obj, Sequence):
        return [_normalize(v) for v in obj]
    raise TypeError(f"cannot canonicalize {type(obj).__name__}")


def canonical_json(obj: Any) -> bytes:
    """Deterministic UTF-8 JSON bytes.

    Sorted keys, no whitespace, ``Decimal`` as string, floats at fixed precision, NaN/Infinity
    rejected. Two structurally equal objects always produce identical bytes, on any platform.
    """
    return json.dumps(
        _normalize(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


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


__all__ = [
    "FLOAT_FORMAT",
    "canonical_json",
    "content_id",
    "derive_seed",
    "sha256_bytes",
    "sha256_file",
    "short_id",
]

"""Deterministic JSONL and JSON primitives for datasets, run artifacts, and the bundle.

Two encodings live behind this boundary and the difference matters:

* :func:`write_jsonl` uses :func:`~credit_audit.ids.canonical_json`, whose finite floats are
  IEEE-754 hexadecimal strings. That is the hash basis, and it is what the committed profile
  fixtures are addressed by. It does not round-trip through a JSON parser as numbers.
* :func:`write_records` and :func:`write_json` use
  :func:`~credit_audit.ids.portable_json`, whose floats are ordinary JSON numbers. Run
  artifacts and every exported bundle file use this, because ``verify`` reads them back and
  the site renders them.

Both are byte-deterministic -- sorted keys, no whitespace, fixed ordering -- so either can
back the export determinism gate. Only one can also be read back as data.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from credit_audit.ids import canonical_json, portable_json

M = TypeVar("M", bound=BaseModel)


def _write_lines(
    path: str | Path,
    records: Iterable[Any],
    *,
    encode: Callable[[Any], bytes],
    append: bool,
) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    if append:
        with open(path, "ab") as handle:
            for record in records:
                handle.write(encode(record))
                handle.write(b"\n")
                count += 1
        return count

    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "wb") as handle:
        for record in records:
            handle.write(encode(record))
            handle.write(b"\n")
            count += 1
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return count


def write_jsonl(path: str | Path, records: Iterable[Any], *, append: bool = False) -> int:
    """Write records as canonical (hash-basis) JSONL. Returns the number written.

    The parent directory is created if missing. Writing is atomic when ``append`` is False:
    content goes to a temporary sibling and is then renamed, so a crash mid-write cannot leave
    a partially-written artifact that a later stage would silently consume.
    """
    return _write_lines(path, records, encode=canonical_json, append=append)


def write_records(path: str | Path, records: Iterable[Any], *, append: bool = False) -> int:
    """Write records as portable JSONL -- deterministic, and readable back as numbers.

    This is the form run artifacts use, because ``credit-audit verify`` re-derives every
    statistic from them and a rate encoded as ``"0x1.8p-1"`` is not a rate.
    """
    return _write_lines(path, records, encode=portable_json, append=append)


def write_json(path: str | Path, payload: Any) -> int:
    """Write one deterministic JSON document, atomically. Returns bytes written.

    A trailing newline is included so the file is well-formed for ``shasum -c``, ``diff``, and
    every other line-oriented tool a skeptic will reach for.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = portable_json(payload) + b"\n"
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return len(data)


def read_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield raw dicts, one per line. Blank lines are skipped."""
    import json

    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def read_models(path: str | Path, model: type[M]) -> Iterator[M]:
    """Yield validated model instances."""
    for raw in read_jsonl(path):
        yield model.model_validate(raw)


def line_sha256(path: str | Path, line_number: int) -> str:
    """sha256 of a specific 1-indexed line, without its trailing newline.

    Each exported pair records this for the JSONL lines it came from, so a visitor can run
    ``sed -n '412p' file.jsonl | shasum -a 256`` and match it. That is what turns a pair page
    on the evidence site from a screenshot into a citation.
    """
    import hashlib

    if line_number < 1:
        raise ValueError("line_number is 1-indexed")
    newline = b"\n"
    with open(path, "rb") as handle:
        for index, raw in enumerate(handle, start=1):
            if index == line_number:
                digest = hashlib.sha256(raw.rstrip(newline)).hexdigest()
                return f"sha256:{digest}"
    raise IndexError(f"{path} has fewer than {line_number} lines")


def count_lines(path: str | Path) -> int:
    with open(path, "rb") as handle:
        return sum(1 for line in handle if line.strip())


__all__ = [
    "count_lines",
    "line_sha256",
    "read_jsonl",
    "read_models",
    "write_json",
    "write_jsonl",
    "write_records",
]

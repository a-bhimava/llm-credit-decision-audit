"""The single serialization boundary.

Every stage of the pipeline (``plan -> execute -> derive -> execute -> score -> stats ->
report -> export``) reads and writes JSONL through this module, which is what makes the run
resumable: the process can be killed at any point and restarted without losing work.

Writes go through :func:`credit_audit.ids.canonical_json`, so two runs that produce the same
records produce byte-identical files.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from credit_audit.ids import canonical_json

M = TypeVar("M", bound=BaseModel)


def write_jsonl(path: str | Path, records: Iterable[Any], *, append: bool = False) -> int:
    """Write records as canonical JSONL. Returns the number of records written.

    The parent directory is created if missing. Writing is atomic when ``append`` is False:
    content goes to a temporary sibling and is then renamed, so a crash mid-write cannot leave
    a partially-written artifact that a later stage would silently consume.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    if append:
        with open(path, "ab") as handle:
            for record in records:
                handle.write(canonical_json(record))
                handle.write(b"\n")
                count += 1
        return count

    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "wb") as handle:
        for record in records:
            handle.write(canonical_json(record))
            handle.write(b"\n")
            count += 1
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return count


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


__all__ = ["count_lines", "line_sha256", "read_jsonl", "read_models", "write_jsonl"]

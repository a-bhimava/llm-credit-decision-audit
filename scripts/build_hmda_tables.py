"""Build ``profiles/hmda_tables/joint_marginals_2024.json`` from the public FFIEC HMDA
Modified LAR (2024, originated + denied, mortgage loans).

This is the ONLY network-touching code in the profiles pipeline. Its output is a small,
committed, hashed aggregate table; everything downstream (``profiles/generate.py``) reads
that committed table and never touches the network. Re-running this script overwrites the
table with a fresh sample -- deliberately not wired into CI or any automated path.

**Why sampling, not the full file.** The query this project's design settled on
(``years=2024&actions_taken=1,3&loan_types=1`` -- originated or denied conventional
mortgages) resolves to a single ~2.5 GB CSV. We don't need every row: the deliverable is a
sparse ``(income_bin x dti_bracket x race x ethnicity x sex x age_band) -> count`` table, and
a multi-million-row sample is already far more than enough to stabilize those cell counts
(cells under ``MIN_CELL_COUNT`` are dropped anyway). We pull ``NUM_CHUNKS`` byte ranges via
HTTP Range requests (confirmed live: the resolved file serves ``Accept-Ranges: bytes``),
**evenly spaced across the whole file** rather than a single prefix read -- the file is
grouped by LEI (lender), so a prefix read would only sample whichever lenders happen to sort
first. Evenly-spaced chunks cross many different lenders instead.

This IS a real limitation, stated here and in ``docs/limitations.md``: it is a sample of the
population, not the population, and evenly-spaced-by-byte-offset is a convenience sampling
frame, not a probability sample. It is used only to anchor realistic income/DTI/demographic
*shape* for synthetic profile generation -- never to compute anything a statistic is later
reported on.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

QUERY_URL = (
    "https://ffiec.cfpb.gov/v2/data-browser-api/view/nationwide/csv"
    "?years=2024&actions_taken=1,3&loan_types=1"
)

NUM_CHUNKS = 40
CHUNK_BYTES = 20_000_000
HEADER_PROBE_BYTES = 8_192
MIN_CELL_COUNT = 5
MIN_ROWS_KEPT = 100_000
MIN_DISTINCT_CELLS = 50
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 3

REQUIRED_COLUMNS = {
    "income",
    "debt_to_income_ratio",
    "derived_race",
    "derived_ethnicity",
    "derived_sex",
    "applicant_age",
    "action_taken",
}

# Upper edges of half-open income bins, in thousands of dollars (HMDA's own unit). The last
# bin is open-ended. Deliberately coarser than the underlying data -- see architecture.md's
# "explicit cuts" discipline: a finer grid would imply a precision this sampling can't back.
INCOME_BIN_EDGES = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 140, 170, 210, 260]

DTI_UNUSABLE = {"NA", "Exempt", ""}
AGE_UNUSABLE = {"8888", "9999", ""}
CATEGORICAL_UNUSABLE = {
    "Not applicable",
    "Free Form Text Only",
    "Race Not Available",
    "Ethnicity Not Available",
    "Sex Not Available",
    "",
}


def income_bin(raw: str) -> str | None:
    try:
        thousands = int(raw)
    except (TypeError, ValueError):
        return None
    if thousands < 0:
        return None
    lo = 0
    for edge in INCOME_BIN_EDGES:
        if thousands < edge:
            return f"{lo}-{edge}"
        lo = edge
    return f"{lo}+"


def dti_bracket(raw: str) -> str | None:
    raw = (raw or "").strip()
    if raw in DTI_UNUSABLE:
        return None
    if raw == "<20%":
        return "<20%"
    if raw == "20%-<30%":
        return "20-30%"
    if raw == "30%-<36%":
        return "30-36%"
    if raw == "50%-60%":
        return "50-60%"
    if raw == ">60%":
        return ">60%"
    try:
        pct = int(raw)
    except ValueError:
        return None
    if pct < 36:
        return "30-36%"
    if pct <= 42:
        return "36-42%"
    if pct <= 49:
        return "43-49%"
    if pct < 50:
        return "43-49%"
    return "50-60%"


def age_band(raw: str) -> str | None:
    raw = (raw or "").strip()
    if raw in AGE_UNUSABLE:
        return None
    return raw


def categorical(raw: str) -> str | None:
    raw = (raw or "").strip()
    if raw in CATEGORICAL_UNUSABLE:
        return None
    return raw


def resolve_file_url(client: httpx.Client) -> str:
    resp = client.get(QUERY_URL, follow_redirects=False)
    if resp.status_code not in (301, 302, 303, 307, 308):
        raise RuntimeError(
            f"expected a redirect from the HMDA query endpoint, got HTTP {resp.status_code}"
        )
    location = resp.headers.get("location")
    if not location:
        raise RuntimeError("HMDA query endpoint redirected but sent no Location header")
    return location


def probe_size_and_header(client: httpx.Client, file_url: str) -> tuple[int, list[str]]:
    head = client.head(file_url, timeout=REQUEST_TIMEOUT)
    head.raise_for_status()
    total_bytes = int(head.headers["content-length"])
    if head.headers.get("accept-ranges") != "bytes":
        raise RuntimeError("HMDA file server does not advertise Range support (Accept-Ranges)")

    probe = client.get(
        file_url,
        headers={"Range": f"bytes=0-{HEADER_PROBE_BYTES - 1}"},
        timeout=REQUEST_TIMEOUT,
    )
    probe.raise_for_status()
    first_line = probe.text.split("\n", 1)[0]
    header = next(csv.reader(io.StringIO(first_line)))

    missing = REQUIRED_COLUMNS - set(header)
    if missing:
        raise RuntimeError(
            f"HMDA CSV header is missing required columns {missing!r} -- the query or the "
            "upstream schema has drifted; refusing to build a table silently missing a "
            "dimension"
        )
    return total_bytes, header


def fetch_chunk(client: httpx.Client, file_url: str, start: int, end: int) -> str:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.get(
                file_url,
                headers={"Range": f"bytes={start}-{end}"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.content.decode("utf-8", errors="ignore")
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            last_error = exc
            time.sleep(0.5 * attempt)
    raise RuntimeError(f"failed to fetch byte range {start}-{end} after {MAX_RETRIES} tries") from (
        last_error
    )


def chunk_offsets(total_bytes: int) -> list[tuple[int, int]]:
    # Skip a safety margin at the very start (past the header line) and end (avoid an
    # incomplete final row with no trailing chunk to complete it).
    lo = HEADER_PROBE_BYTES
    hi = total_bytes - CHUNK_BYTES - 1024
    if hi <= lo:
        return [(lo, total_bytes - 1)]
    stride = (hi - lo) // (NUM_CHUNKS - 1)
    starts = [lo + i * stride for i in range(NUM_CHUNKS)]
    return [(s, s + CHUNK_BYTES - 1) for s in starts]


def parse_chunk(text: str, header: list[str], counts: Counter[tuple[str, ...]]) -> tuple[int, int]:
    lines = text.split("\n")
    # First and last lines are very likely partial rows split across a chunk boundary --
    # drop both rather than trying to stitch chunks back together.
    usable = lines[1:-1] if len(lines) > 2 else []

    index = {name: i for i, name in enumerate(header)}
    scanned = 0
    kept = 0
    for row in csv.reader(usable):
        if len(row) != len(header):
            continue
        scanned += 1

        inc = income_bin(row[index["income"]])
        dti = dti_bracket(row[index["debt_to_income_ratio"]])
        race = categorical(row[index["derived_race"]])
        eth = categorical(row[index["derived_ethnicity"]])
        sex = categorical(row[index["derived_sex"]])
        age = age_band(row[index["applicant_age"]])

        if None in (inc, dti, race, eth, sex, age):
            continue

        counts[(inc, dti, race, eth, sex, age)] += 1
        kept += 1
    return scanned, kept


def build() -> dict[str, Any]:
    counts: Counter[tuple[str, ...]] = Counter()
    total_scanned = 0
    total_kept = 0

    with httpx.Client() as client:
        print(f"resolving {QUERY_URL}", file=sys.stderr)
        file_url = resolve_file_url(client)
        print(f"resolved -> {file_url}", file=sys.stderr)

        total_bytes, header = probe_size_and_header(client, file_url)
        print(f"file is {total_bytes:,} bytes; header has {len(header)} columns", file=sys.stderr)

        ranges = chunk_offsets(total_bytes)
        for i, (start, end) in enumerate(ranges, start=1):
            text = fetch_chunk(client, file_url, start, end)
            scanned, kept = parse_chunk(text, header, counts)
            total_scanned += scanned
            total_kept += kept
            print(
                f"chunk {i}/{len(ranges)} bytes={start}-{end} scanned={scanned} kept={kept} "
                f"(running total kept={total_kept})",
                file=sys.stderr,
            )

    if total_kept < MIN_ROWS_KEPT:
        raise RuntimeError(
            f"only kept {total_kept} usable rows (< {MIN_ROWS_KEPT}) -- sampling likely "
            "broken (check column parsing / filter logic) rather than shipping a thin table"
        )

    cells = {k: v for k, v in counts.items() if v >= MIN_CELL_COUNT}
    if len(cells) < MIN_DISTINCT_CELLS:
        raise RuntimeError(
            f"only {len(cells)} cells survived the min-count-{MIN_CELL_COUNT} floor "
            f"(< {MIN_DISTINCT_CELLS}) -- table would be too sparse to be useful"
        )

    sorted_cells = [
        {
            "income_bin": k[0],
            "dti_bracket": k[1],
            "race": k[2],
            "ethnicity": k[3],
            "sex": k[4],
            "age_band": k[5],
            "count": v,
        }
        for k, v in sorted(cells.items())
    ]

    return {
        "schema": "credit-audit/hmda-joint-marginals@1",
        "source": {
            "query_url": QUERY_URL,
            "resolved_file_url": file_url,
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "total_file_bytes": total_bytes,
            "sampling_method": (
                "evenly-spaced HTTP byte-range chunks across the full file, header and "
                "trailing partial lines dropped per chunk"
            ),
            "num_chunks": len(ranges),
            "chunk_bytes": CHUNK_BYTES,
        },
        "rows_scanned": total_scanned,
        "rows_kept": total_kept,
        "min_cell_count": MIN_CELL_COUNT,
        "distinct_cells": len(sorted_cells),
        "income_bin_edges_thousands": INCOME_BIN_EDGES,
        "cells": sorted_cells,
    }


def main() -> None:
    out_dir = (
        Path(__file__).resolve().parent.parent / "src" / "credit_audit" / "profiles" / "hmda_tables"
    )
    out_path = out_dir / "joint_marginals_2024.json"
    hash_path = out_dir / "joint_marginals_2024.json.sha256"

    table = build()

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(table, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    out_path.write_bytes(payload)

    digest = hashlib.sha256(payload).hexdigest()
    hash_path.write_text(f"sha256:{digest}  {out_path.name}\n")

    print(
        f"wrote {out_path} ({len(payload):,} bytes, {table['distinct_cells']} cells, "
        f"{table['rows_kept']:,} rows kept of {table['rows_scanned']:,} scanned)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

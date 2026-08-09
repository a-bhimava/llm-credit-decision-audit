"""Canonical serialization and seed derivation.

Byte-determinism here is what later makes the exported evidence bundle reproducible by a
stranger: they re-run the exporter and ``diff -r`` against what the site serves. If canonical
JSON is not stable, that claim silently fails.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from credit_audit.ids import (
    canonical_json,
    content_id,
    derive_seed,
    sha256_bytes,
    sha256_file,
    short_id,
)
from credit_audit.io.jsonl import count_lines, line_sha256, read_jsonl, write_jsonl
from credit_audit.types import EmploymentStatus, Provenance, ReasonCode

# -- canonical JSON ---------------------------------------------------------------------


def test_key_order_is_irrelevant():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
    assert canonical_json({"a": 2, "b": 1}) == b'{"a":2,"b":1}'


def test_no_incidental_whitespace():
    assert b" " not in canonical_json({"a": 1, "b": [1, 2]})


def test_decimal_survives_as_string():
    """Decimals must not become floats. 0.4300 and 0.43 are the same number but different
    bytes, so the quantization is part of the contract."""
    payload = canonical_json({"dti": Decimal("0.4300")})
    assert payload == b'{"dti":"0.4300"}'
    assert json.loads(payload)["dti"] == "0.4300"


def test_float_is_fixed_precision():
    """Platform repr differences would otherwise break determinism for equal values."""
    assert canonical_json({"p": 0.1 + 0.2}) == canonical_json({"p": 0.3})


def test_nan_and_infinity_are_rejected():
    """Non-finite floats must raise, not serialize.

    Floats are formatted to fixed-precision strings before the JSON encoder sees them, so
    ``allow_nan=False`` cannot catch this -- NaN would otherwise land in a published bundle as
    the literal string "nan", which reads as data.
    """
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            canonical_json({"x": bad})


def test_signed_zero_is_normalized():
    """-0.0 and 0.0 are the same number and must produce the same bytes."""
    assert canonical_json({"x": -0.0}) == canonical_json({"x": 0.0})


def test_bool_is_not_coerced_to_int():
    assert canonical_json({"x": True}) == b'{"x":true}'
    assert canonical_json({"x": 1}) == b'{"x":1}'


def test_enums_serialize_as_their_value():
    assert canonical_json({"c": ReasonCode.INSUFFICIENT_INCOME}) == b'{"c":"INSUFFICIENT_INCOME"}'
    assert canonical_json({"e": EmploymentStatus.FULL_TIME}) == b'{"e":"FULL_TIME"}'


def test_datetime_is_iso8601():
    stamp = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    assert canonical_json({"t": stamp}) == b'{"t":"2026-08-09T12:00:00+00:00"}'


def test_tuple_and_list_are_equivalent():
    assert canonical_json({"x": (1, 2)}) == canonical_json({"x": [1, 2]})


def test_pydantic_models_canonicalize_by_field():
    model = Provenance(generator_seed=7, generator_version="v1")
    assert canonical_json(model) == canonical_json(
        {
            "generator_seed": 7,
            "generator_version": "v1",
            "source_cell_id": None,
            "parent_applicant_id": None,
            "intervention_lineage": [],
        }
    )


def test_unsupported_type_raises():
    with pytest.raises(TypeError):
        canonical_json({"x": object()})


# -- identifiers ------------------------------------------------------------------------


def test_content_id_is_prefixed_and_stable():
    ident = content_id({"a": 1})
    assert ident.startswith("blake2b128:")
    assert len(ident.split(":")[1]) == 32
    assert ident == content_id({"a": 1})


def test_content_id_distinguishes_different_content():
    assert content_id({"a": 1}) != content_id({"a": 2})


def test_ids_are_stable_across_hash_seeds():
    """Run in a subprocess under two PYTHONHASHSEED values.

    Any accidental dependence on set or dict iteration order would show up here, and would
    silently break cross-machine reproducibility of the published bundle.
    """
    program = (
        "from credit_audit.ids import content_id;"
        "print(content_id({'b': [3, 1, 2], 'a': {'z': 1, 'y': 2}}))"
    )
    outputs = set()
    for seed in ("0", "1", "42"):
        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        )
        outputs.add(result.stdout.strip())
    assert len(outputs) == 1, f"content_id varies with PYTHONHASHSEED: {outputs}"


def test_short_id_length():
    assert len(short_id({"a": 1})) == 8
    assert len(short_id({"a": 1}, length=12)) == 12


def test_sha256_helpers(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"hello")
    assert sha256_file(path) == sha256_bytes(b"hello")
    assert sha256_file(path).startswith("sha256:")


# -- seed derivation --------------------------------------------------------------------


def test_seed_is_deterministic():
    assert derive_seed(1729, "APP-1", "control", 0) == derive_seed(1729, "APP-1", "control", 0)


def test_seed_varies_across_every_axis():
    base = derive_seed(1729, "APP-1", "control", 0)
    assert base != derive_seed(1730, "APP-1", "control", 0)
    assert base != derive_seed(1729, "APP-2", "control", 0)
    assert base != derive_seed(1729, "APP-1", "authority", 0)
    assert base != derive_seed(1729, "APP-1", "control", 1)


def test_seed_is_insertion_stable():
    """Adding applicant #226 must not disturb the seeds of applicants 1-225.

    This is the entire reason seeds are derived hierarchically rather than drawn from one
    global stream -- otherwise no two runs with different population sizes are comparable.
    """
    first_pass = [derive_seed(1729, f"APP-{i}", "control", 0) for i in range(1, 226)]
    _ = derive_seed(1729, "APP-226", "control", 0)
    second_pass = [derive_seed(1729, f"APP-{i}", "control", 0) for i in range(1, 226)]
    assert first_pass == second_pass


def test_seed_is_nonnegative_63_bit():
    for i in range(200):
        seed = derive_seed(1729, f"APP-{i}", "arm", i)
        assert 0 <= seed < (1 << 63)


def test_separator_prevents_part_collisions():
    """('ab', 'c') and ('a', 'bc') must not collide -- parts are separated, not concatenated."""
    assert derive_seed(1, "ab", "c") != derive_seed(1, "a", "bc")


# -- JSONL round trip -------------------------------------------------------------------


def test_jsonl_roundtrip_and_determinism(tmp_path):
    records = [Provenance(generator_seed=i, generator_version="v1") for i in range(3)]
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"

    assert write_jsonl(a, records) == 3
    write_jsonl(b, records)
    assert a.read_bytes() == b.read_bytes(), "identical records must produce identical bytes"

    assert count_lines(a) == 3
    assert [r["generator_seed"] for r in read_jsonl(a)] == [0, 1, 2]


def test_write_is_atomic_leaving_no_temp_files(tmp_path):
    write_jsonl(tmp_path / "x.jsonl", [{"a": 1}])
    assert [p.name for p in tmp_path.iterdir()] == ["x.jsonl"]


def test_line_sha256_matches_shell_equivalent(tmp_path):
    """Each exported pair cites the JSONL line it came from, so a visitor can verify with
    ``sed -n '2p' file.jsonl | shasum -a 256``. That turns a pair page into a citation."""
    path = tmp_path / "r.jsonl"
    write_jsonl(path, [{"i": 1}, {"i": 2}, {"i": 3}])

    expected = sha256_bytes(canonical_json({"i": 2}))
    assert line_sha256(path, 2) == expected

    with pytest.raises(IndexError):
        line_sha256(path, 99)

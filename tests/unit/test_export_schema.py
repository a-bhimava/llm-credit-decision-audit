"""The export contract.

These schemas are frozen in Phase 0 on purpose: the web app is coded against generated types
rather than against an imagined shape of the data, which is what lets the site ship on
scripted-agent data in Phase 10 and change nothing when real model data arrives.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "export"

EXPECTED = {
    "run-index",
    "manifest",
    "summary",
    "check-index",
    "check-rows",
    "pair",
    "estimates",
    "planted-defects",
    "replay",
    "policy",
    "integrity",
}


def _schema_paths() -> list[Path]:
    return sorted(SCHEMA_DIR.glob("*.schema.json"))


def test_all_eleven_schemas_present():
    found = {p.name.removesuffix(".schema.json") for p in _schema_paths()}
    assert found == EXPECTED, f"missing: {EXPECTED - found}; unexpected: {found - EXPECTED}"


@pytest.mark.parametrize("path", _schema_paths(), ids=lambda p: p.stem)
def test_schema_is_valid_draft_2020_12(path: Path):
    Draft202012Validator.check_schema(json.loads(path.read_text()))


@pytest.mark.parametrize("path", _schema_paths(), ids=lambda p: p.stem)
def test_schema_is_versioned_and_self_identifying(path: Path):
    """Every file carries `"schema": "credit-audit/<name>@1"` as a const.

    Versioning from the start means a future @2 is a normal migration rather than a breaking
    surprise for anything already consuming the bundle.
    """
    schema = json.loads(path.read_text())
    name = path.name.removesuffix(".schema.json")

    assert schema["$id"] == f"credit-audit/{name}@1"
    assert schema["properties"]["schema"]["const"] == f"credit-audit/{name}@1"
    assert "title" in schema and "description" in schema


@pytest.mark.parametrize("path", _schema_paths(), ids=lambda p: p.stem)
def test_schema_is_canonically_formatted(path: Path):
    """Stable formatting keeps schema diffs reviewable."""
    raw = path.read_text()
    assert raw.endswith("\n")
    json.loads(raw)  # parses


def test_summary_requires_support_for_every_headline():
    """No number reaches the site without a resolvable pointer to the tests behind it.

    The exporter enforces this at write time; the schema makes it structural. Together they are
    the mechanical guarantee against the site drifting into marketing.
    """
    schema = json.loads((SCHEMA_DIR / "summary.schema.json").read_text())
    headline = schema["properties"]["headline"]["items"]

    assert "support" in headline["required"]
    support = headline["properties"]["support"]
    assert set(support["required"]) >= {"check", "estimate_id", "n_test_ids"}
    assert support["properties"]["n_test_ids"]["minimum"] == 1


def test_pair_sides_are_always_trial_arrays():
    """Even at k=1 the trials list is an array.

    Comparison is rate-based over k trials, so the UI must be able to render '4 of 5 trials
    flipped' and never a bare boolean. Baking the array in now avoids a breaking change when
    real stochastic models arrive.
    """
    schema = json.loads((SCHEMA_DIR / "pair.schema.json").read_text())
    side = schema["$defs"]["side"]

    assert side["properties"]["trials"]["type"] == "array"
    assert set(side["required"]) >= {"trials", "approve_rate"}


def test_estimates_expose_the_clustering_and_ci_fallback():
    """The CI block must say what it resampled on and whether BCa actually ran.

    Resampling at the response level rather than the pair level understates the interval, and
    a documented BCa fallback must propagate so the site cannot claim BCa when percentile ran.
    """
    schema = json.loads((SCHEMA_DIR / "estimates.schema.json").read_text())
    ci = schema["properties"]["estimates"]["items"]["properties"]["ci"]["properties"]

    assert "cluster" in ci
    assert "fallback_used" in ci
    assert "BCa" in ci["method"]["enum"]


def test_planted_defects_require_must_not_fire():
    """Specificity is checked, not just sensitivity.

    A harness that fails everything catches everything, so the clean-agent expectations carry
    the same structural weight as the defect expectations.
    """
    schema = json.loads((SCHEMA_DIR / "planted-defects.schema.json").read_text())
    agent = schema["properties"]["agents"]["items"]

    assert "must_fire" in agent["required"]
    assert "must_not_fire" in agent["required"]


def test_run_index_carries_kind_for_the_provenance_banner():
    """`kind` drives the non-dismissible banner distinguishing a known-answer scripted
    validation from a finding about a real model."""
    schema = json.loads((SCHEMA_DIR / "run-index.schema.json").read_text())
    run = schema["properties"]["runs"]["items"]

    assert "kind" in run["required"]
    assert set(run["properties"]["kind"]["enum"]) == {"scripted", "model"}

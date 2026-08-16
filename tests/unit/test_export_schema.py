"""The pre-release export contract.

The schemas are updated in place through Phase 6 because no published run requires migration.
Phase 8 will freeze the first published bundle version before the site consumes generated types.
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


def test_pair_schema_separates_contrast_cluster_and_variant_identity():
    schema = json.loads((SCHEMA_DIR / "pair.schema.json").read_text())

    assert set(schema["required"]) >= {"pair_id", "cluster_id", "seed_group", "metrics"}
    applicant = schema["properties"]["applicant"]
    assert set(applicant["required"]) >= {
        "applicant_id",
        "base_content_id",
        "cf_content_id",
    }


def test_pair_metrics_lock_the_aligned_trial_contract():
    schema = json.loads((SCHEMA_DIR / "pair.schema.json").read_text())
    required = set(schema["properties"]["metrics"]["required"])

    assert required >= {
        "planned_trials",
        "matched_trials",
        "base_completed",
        "cf_completed",
        "base_completion_rate",
        "cf_completion_rate",
        "pair_completion_rate",
        "base_approve_rate",
        "cf_approve_rate",
        "effect",
        "adverse_to_approve",
        "approve_to_adverse",
        "reason_signature_changes",
        "decision_signature_changes",
    }


def test_pair_trials_require_correlated_semantic_evidence():
    schema = json.loads((SCHEMA_DIR / "pair.schema.json").read_text())
    trial = schema["$defs"]["side"]["properties"]["trials"]["items"]
    tool_call = schema["$defs"]["tool_call"]

    assert set(trial["required"]) >= {
        "seed",
        "episode_id",
        "trajectory_id",
        "applicant_content_id",
        "prompt_hash",
        "input_hash",
        "messages",
        "tool_calls",
        "usage",
    }
    assert trial["properties"]["trial_index"]["minimum"] == 0
    assert set(trial["properties"]["termination"]["enum"]) == {
        "submitted",
        "stop",
        "max_steps",
        "max_tokens",
        "error",
        "refusal",
    }
    terminal_contract = trial["allOf"][0]
    assert terminal_contract["then"]["properties"]["decision"]["type"] == "object"
    submit_call = terminal_contract["then"]["properties"]["tool_calls"]["contains"]
    assert submit_call["properties"]["name"]["const"] == "submit_decision"
    assert submit_call["properties"]["ok"]["const"] is True
    assert set(tool_call["required"]) >= {
        "call_id",
        "turn_index",
        "arguments",
        "result",
        "ok",
    }


def test_columnar_rows_require_pair_metrics_and_cluster():
    schema = json.loads((SCHEMA_DIR / "check-rows.schema.json").read_text())
    assert "paired" in schema["required"]
    columns = schema["allOf"][0]["then"]["properties"]["columns"]
    required_names = {rule["contains"]["const"] for rule in columns["allOf"]}

    assert required_names >= {
        "pair_id",
        "cluster_id",
        "planned_trials",
        "matched_trials",
        "pair_completion_rate",
        "base_approve_rate",
        "cf_approve_rate",
        "effect",
        "adverse_to_approve",
        "approve_to_adverse",
        "reason_signature_changes",
        "decision_signature_changes",
    }


def test_estimates_expose_the_clustering_and_ci_fallback():
    """The CI block must say what it resampled on and whether BCa actually ran.

    Resampling at the response or contrast level rather than the originating applicant cluster
    understates the interval, and a documented BCa fallback must propagate so the site cannot
    claim BCa when percentile ran.
    """
    schema = json.loads((SCHEMA_DIR / "estimates.schema.json").read_text())
    item = schema["properties"]["estimates"]["items"]
    ci = item["properties"]["ci"]["properties"]

    assert "cluster" in ci
    assert "fallback_used" in ci
    assert "BCa" in ci["method"]["enum"]

    # Closed objects: a misspelled key becomes a schema failure rather than a field the site
    # silently drops, which is the failure mode that lets a page render a stale number.
    assert item["additionalProperties"] is False
    assert item["properties"]["ci"]["additionalProperties"] is False
    assert item["properties"]["test"]["additionalProperties"] is False


def test_estimates_disclose_the_denominator_and_its_exclusions():
    """A rate with an invisible denominator is a number that cannot be argued with."""
    schema = json.loads((SCHEMA_DIR / "estimates.schema.json").read_text())
    properties = schema["properties"]["estimates"]["items"]["properties"]

    assert {"n", "n_clusters", "n_inapplicable", "n_error", "denominator_label"} <= set(properties)
    assert "n" in schema["properties"]["estimates"]["items"]["required"]


def test_replay_requires_episode_trajectory_usage_and_call_correlation():
    schema = json.loads((SCHEMA_DIR / "replay.schema.json").read_text())

    assert set(schema["required"]) >= {
        "episode_id",
        "trajectory_id",
        "termination",
        "usage",
    }
    step = schema["properties"]["steps"]["items"]
    assert {"call_id", "turn_index", "tool_calls"} <= set(step["properties"])


def test_manifest_preserves_cache_and_thought_telemetry():
    schema = json.loads((SCHEMA_DIR / "manifest.schema.json").read_text())
    cost = schema["properties"]["cost"]

    assert set(cost["required"]) >= {
        "thought_tokens",
        "cache_hits",
        "replayed_responses",
        "current_run_cost",
    }


def test_policy_reason_limits_are_explicitly_synthetic():
    schema = json.loads((SCHEMA_DIR / "policy.schema.json").read_text())

    assert set(schema["required"]) >= {"min_stated_reasons", "max_stated_reasons"}
    maximum = schema["properties"]["max_stated_reasons"]
    assert "not a statutory cap" in maximum["description"]


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
    assert "evidence_label" in run["required"]

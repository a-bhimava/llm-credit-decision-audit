"""The exporter: the frozen contract, the three hard rules, and byte determinism."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from credit_audit.report.bundle import SHA256SUMS, BundleWriter, ExportError, SizeBudget
from credit_audit.report.export import (
    MODEL_CLAIM_PHRASES,
    check_headline_support,
    export_run,
    lint_scripted_headlines,
    select_detail_pairs,
)
from credit_audit.run.execute import load_run_results
from credit_audit.types import TestStatus as ResultStatus

from .conftest import BOOTSTRAP_B, FIXED_GIT

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "export"

SCHEMA_FOR = {
    "manifest.json": "manifest",
    "summary.json": "summary",
    "policy.json": "policy",
    "stats/estimates.json": "estimates",
    "checks/index.json": "check-index",
    "integrity/chain.json": "integrity",
}


@pytest.fixture(scope="module")
def validators():
    return {
        path.name.removesuffix(".schema.json"): Draft202012Validator(json.loads(path.read_text()))
        for path in SCHEMA_DIR.glob("*.schema.json")
    }


def _schema_name(relpath: str) -> str | None:
    if relpath in SCHEMA_FOR:
        return SCHEMA_FOR[relpath]
    if relpath.startswith("checks/rows/"):
        return "check-rows"
    if relpath.startswith("pairs/"):
        return "pair"
    return None


# --------------------------------------------------------------------------------------
# The frozen export contract
# --------------------------------------------------------------------------------------


def test_every_exported_file_validates_against_its_frozen_schema(smoke_bundle, validators):
    """The whole point of freezing eleven schemas in Phase 0."""

    checked = 0
    for entry in smoke_bundle.bundle.files:
        name = _schema_name(entry.path)
        if name is None:
            continue
        payload = json.loads((smoke_bundle.root / entry.path).read_text())
        errors = sorted(validators[name].iter_errors(payload), key=lambda e: list(e.path))
        assert not errors, f"{entry.path}: {[(list(e.path), e.message) for e in errors[:3]]}"
        checked += 1
    assert checked >= 10


def test_the_run_index_validates_and_registers_the_run(smoke_bundle, validators):
    index = json.loads((smoke_bundle.root.parent / "index.json").read_text())
    assert not list(validators["run-index"].iter_errors(index))
    assert index["default_run_id"] == smoke_bundle.run_id
    entry = next(row for row in index["runs"] if row["run_id"] == smoke_bundle.run_id)
    # The single field that drives the non-dismissible provenance banner on every route.
    assert entry["kind"] == "scripted"
    assert entry["evidence_label"] == "Synthetic"
    assert entry["validates_harness"] is True


def test_the_bundle_carries_every_expected_file_type(smoke_bundle):
    paths = {entry.path for entry in smoke_bundle.bundle.files}
    assert {
        "manifest.json",
        "summary.json",
        "policy.json",
        "stats/estimates.json",
        "checks/index.json",
        "integrity/chain.json",
    } <= paths
    assert any(path.startswith("checks/rows/") for path in paths)
    assert any(path.startswith("pairs/") for path in paths)
    assert any(path.startswith("prompts/") for path in paths)
    assert (smoke_bundle.root / SHA256SUMS).exists()


# --------------------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------------------


def test_exporting_twice_is_byte_identical(smoke_run, tmp_path, policy):
    """The claim a stranger can check: re-export and `diff -r`."""

    first = export_run(
        smoke_run.run_dir,
        out_root=tmp_path / "a",
        policy=policy,
        git=FIXED_GIT,
        bootstrap_B=BOOTSTRAP_B,
    )
    second = export_run(
        smoke_run.run_dir,
        out_root=tmp_path / "b",
        policy=policy,
        git=FIXED_GIT,
        bootstrap_B=BOOTSTRAP_B,
    )

    assert first.bundle.bundle_sha256 == second.bundle.bundle_sha256
    assert [(e.path, e.sha256) for e in first.bundle.files] == [
        (e.path, e.sha256) for e in second.bundle.files
    ]
    for entry in first.bundle.files:
        assert (first.root / entry.path).read_bytes() == (second.root / entry.path).read_bytes()


def test_a_stale_file_from_a_previous_export_cannot_survive(smoke_run, tmp_path, policy):
    """A leftover file would still be served, and would still hash. The directory is replaced."""

    out = tmp_path / "out"
    first = export_run(
        smoke_run.run_dir, out_root=out, policy=policy, git=FIXED_GIT, bootstrap_B=BOOTSTRAP_B
    )
    stale = first.root / "checks" / "rows" / "monotonicity.gone_forever.json"
    stale.write_text("{}")

    second = export_run(
        smoke_run.run_dir, out_root=out, policy=policy, git=FIXED_GIT, bootstrap_B=BOOTSTRAP_B
    )
    assert not stale.exists()
    assert second.bundle.bundle_sha256 == first.bundle.bundle_sha256


def test_sha256sums_matches_every_published_file(smoke_bundle):
    from credit_audit.ids import sha256_bytes

    listed = 0
    for line in (smoke_bundle.root / SHA256SUMS).read_text().splitlines():
        digest, _, relpath = line.partition("  ")
        data = (smoke_bundle.root / relpath).read_bytes()
        assert sha256_bytes(data) == f"sha256:{digest}", relpath
        listed += 1
    assert listed == len(smoke_bundle.bundle.files)


# --------------------------------------------------------------------------------------
# Rule 1: no number without support
# --------------------------------------------------------------------------------------


def test_every_headline_resolves_to_an_estimate_with_tests(smoke_bundle):
    summary = json.loads((smoke_bundle.root / "summary.json").read_text())
    estimates = json.loads((smoke_bundle.root / "stats" / "estimates.json").read_text())
    by_id = {e["estimate_id"]: e for e in estimates["estimates"]}

    assert summary["headline"]
    for headline in summary["headline"]:
        estimate = by_id[headline["support"]["estimate_id"]]
        assert headline["support"]["n_test_ids"] >= 1
        assert len(estimate["support_test_ids"]) == headline["support"]["n_test_ids"]


def test_an_unsupported_headline_fails_the_export():
    summary = {
        "kind": "scripted",
        "headline": [
            {"id": "h1", "statement": "x", "support": {"estimate_id": "missing", "n_test_ids": 3}}
        ],
    }
    with pytest.raises(ExportError, match="does not resolve"):
        check_headline_support(summary, {"estimates": []})


def test_a_headline_claiming_zero_tests_fails_the_export():
    summary = {
        "kind": "scripted",
        "headline": [
            {"id": "h1", "statement": "x", "support": {"estimate_id": "e1", "n_test_ids": 0}}
        ],
    }
    estimates = {"estimates": [{"estimate_id": "e1", "support_test_ids": []}]}
    with pytest.raises(ExportError, match="at least one"):
        check_headline_support(summary, estimates)


def test_a_headline_miscounting_its_support_fails_the_export():
    summary = {
        "kind": "scripted",
        "headline": [
            {"id": "h1", "statement": "x", "support": {"estimate_id": "e1", "n_test_ids": 9}}
        ],
    }
    estimates = {"estimates": [{"estimate_id": "e1", "support_test_ids": ["t1", "t2"]}]}
    with pytest.raises(ExportError, match="claims 9 supporting tests"):
        check_headline_support(summary, estimates)


def test_a_bundle_with_nothing_to_say_is_refused():
    with pytest.raises(ExportError, match="no headline entries"):
        check_headline_support({"kind": "scripted", "headline": []}, {"estimates": []})


# --------------------------------------------------------------------------------------
# Rule 2: a scripted run is never phrased as a model finding
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", MODEL_CLAIM_PHRASES)
def test_every_banned_phrase_fails_a_scripted_export(phrase):
    summary = {
        "kind": "scripted",
        "headline": [{"id": "h1", "statement": f"Our results show {phrase} is unreliable."}],
    }
    with pytest.raises(ExportError, match="model-claim phrase"):
        lint_scripted_headlines(summary)


def test_the_lint_is_case_insensitive():
    summary = {"kind": "scripted", "headline": [{"id": "h1", "statement": "GPT was wrong."}]}
    with pytest.raises(ExportError, match="model-claim phrase"):
        lint_scripted_headlines(summary)


def test_a_model_run_may_describe_a_model():
    """The lint exists to stop known-answer runs masquerading as findings, nothing more."""

    summary = {"kind": "model", "headline": [{"id": "h1", "statement": "The model refused."}]}
    lint_scripted_headlines(summary)


def test_real_scripted_headlines_pass_their_own_lint(smoke_bundle):
    summary = json.loads((smoke_bundle.root / "summary.json").read_text())
    lint_scripted_headlines(summary)
    assert all("known-answer" in h["statement"] for h in summary["headline"])


# --------------------------------------------------------------------------------------
# Rule 3: nothing is written until it has been scanned
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "sk-abcdefghijklmnopqrstuvwxyz012345",
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "-----BEGIN RSA PRIVATE KEY-----",
        "Bearer abcdefghijklmnopqrstuvwxyz0123",
    ],
)
def test_a_credential_aborts_the_export_before_writing(tmp_path, secret):
    writer = BundleWriter(tmp_path / "out", secret_needles=())
    writer.add_json("summary.json", {"note": secret})
    with pytest.raises(ExportError, match="refusing to export"):
        writer.finalize()
    assert not (tmp_path / "out").exists(), "nothing may be written when a scan fails"


def test_a_local_absolute_path_aborts_the_export(tmp_path):
    writer = BundleWriter(tmp_path / "out", secret_needles=("/Users/somebody",))
    writer.add_json("summary.json", {"path": "/Users/somebody/projects/thing"})
    with pytest.raises(ExportError, match="embeds the local path"):
        writer.finalize()


def test_the_real_bundle_contains_no_local_paths(smoke_bundle):
    from credit_audit.report.bundle import home_needles

    needles = home_needles()
    assert needles, "the scan must have something to look for"
    for entry in smoke_bundle.bundle.files:
        text = (smoke_bundle.root / entry.path).read_text(errors="ignore")
        for needle in needles:
            assert needle not in text, entry.path


# --------------------------------------------------------------------------------------
# Size budgets
# --------------------------------------------------------------------------------------


def test_the_bundle_fits_its_published_budget(smoke_bundle):
    budget = SizeBudget()
    assert smoke_bundle.total_bytes <= budget.max_run_bytes
    assert smoke_bundle.n_files <= budget.max_files
    for entry in smoke_bundle.bundle.files:
        assert entry.bytes <= budget.max_file_bytes, entry.path


def test_an_oversized_file_is_refused(tmp_path):
    writer = BundleWriter(tmp_path / "out", budget=SizeBudget(max_file_bytes=64))
    writer.add_json("summary.json", {"padding": "x" * 500})
    with pytest.raises(ExportError, match="per-file limit"):
        writer.finalize()


def test_too_many_files_is_refused(tmp_path):
    writer = BundleWriter(tmp_path / "out", budget=SizeBudget(max_files=2))
    for index in range(3):
        writer.add_json(f"pairs/{index}.json", {"i": index})
    with pytest.raises(ExportError, match="reduce exported pair detail"):
        writer.finalize()


def test_an_oversized_bundle_is_refused(tmp_path):
    writer = BundleWriter(tmp_path / "out", budget=SizeBudget(max_run_bytes=256))
    writer.add_json("summary.json", {"padding": "x" * 500})
    with pytest.raises(ExportError, match="per-run limit"):
        writer.finalize()


def test_bundle_paths_must_stay_inside_the_bundle(tmp_path):
    writer = BundleWriter(tmp_path / "out")
    for bad in ("/etc/passwd", "../escape.json"):
        with pytest.raises(ExportError, match="relative and contained"):
            writer.add_bytes(bad, b"{}")


def test_a_file_cannot_be_added_twice(tmp_path):
    writer = BundleWriter(tmp_path / "out")
    writer.add_json("a.json", {})
    with pytest.raises(ExportError, match="twice"):
        writer.add_json("a.json", {})


# --------------------------------------------------------------------------------------
# Prompt dedup and pair selection
# --------------------------------------------------------------------------------------


def test_the_system_prompt_is_stored_once_and_referenced(smoke_bundle):
    """~12 KB repeated across every episode is the single biggest size win available."""

    prompts = [e for e in smoke_bundle.bundle.files if e.path.startswith("prompts/")]
    assert len(prompts) == smoke_bundle.n_prompts == 1

    pair_path = next(e.path for e in smoke_bundle.bundle.files if e.path.startswith("pairs/"))
    pair = json.loads((smoke_bundle.root / pair_path).read_text())
    for side in ("base", "cf"):
        for trial in pair["sides"][side]["trials"]:
            assert trial["prompt_ref"] == prompts[0].path
            system = [m for m in trial["messages"] if m["role"] == "system"]
            assert system and all(m["content"] == "" for m in system)


def test_pair_detail_prefers_failures_and_is_deterministic(defect_run):
    results = load_run_results(defect_run.run_dir)
    selected = select_detail_pairs(results, per_check=2)

    assert selected == select_detail_pairs(results, per_check=2)
    by_check: dict[str, list] = {}
    for result in selected:
        by_check.setdefault(result.check, []).append(result)
    assert all(len(bucket) <= 2 for bucket in by_check.values())

    failing_checks = {r.check for r in results if r.status is ResultStatus.FAIL}
    assert failing_checks
    for check in failing_checks:
        assert by_check[check][0].status is ResultStatus.FAIL


def test_every_row_is_exported_even_though_detail_is_sampled(smoke_bundle, smoke_run):
    """Sampling applies to the drill-down, never to the data."""

    results = load_run_results(smoke_run.run_dir)
    index = json.loads((smoke_bundle.root / "checks" / "index.json").read_text())
    total_rows = 0
    for entry in index["checks"]:
        rows = json.loads((smoke_bundle.root / entry["rows_file"]).read_text())
        assert rows["n"] == entry["n"]
        total_rows += rows["n"]
        assert entry["n_detail_exported"] <= entry["n"]
    assert total_rows == len(results)


def test_paired_rows_carry_the_full_matched_trial_contract(smoke_bundle):
    from credit_audit.report.checks import PAIRED_METRIC_COLUMNS

    index = json.loads((smoke_bundle.root / "checks" / "index.json").read_text())
    paired_seen = 0
    for entry in index["checks"]:
        rows = json.loads((smoke_bundle.root / entry["rows_file"]).read_text())
        if not rows["paired"]:
            continue
        paired_seen += 1
        assert set(PAIRED_METRIC_COLUMNS) <= set(rows["columns"])
        assert {"pair_id", "cluster_id"} <= set(rows["columns"])
    assert paired_seen


def test_the_pair_viewer_shows_the_structural_guarantee(smoke_bundle):
    """A presentation contrast must leave the facts hash bit-identical, and say so."""

    invariance = [
        e.path
        for e in smoke_bundle.bundle.files
        if e.path.startswith("pairs/")
        and json.loads((smoke_bundle.root / e.path).read_text())["check"].startswith("invariance.")
    ]
    assert invariance
    pair = json.loads((smoke_bundle.root / invariance[0]).read_text())
    hashes = pair["applicant"]["hashes"]
    assert hashes["facts_identical"] is True
    assert hashes["presentation_identical"] is False
    assert pair["applicant"]["diff"]
    assert all(entry["layer"] == "presentation" for entry in pair["applicant"]["diff"])


def test_derived_ratios_are_shown_rather_than_trusted(smoke_bundle):
    pair_path = next(e.path for e in smoke_bundle.bundle.files if e.path.startswith("pairs/"))
    pair = json.loads((smoke_bundle.root / pair_path).read_text())
    for side in ("base", "cf"):
        assert set(pair["applicant"][side]["derived"]) == {"dti", "cltv", "utilization"}

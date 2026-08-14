"""The pair viewer's data, which the roadmap calls the screen the design exists for.

Three fields shipped hardcoded empty on every published pair, so the UI could not have been
built against them: what each arm did, which statistics the pair fed, and -- on a necessity
test -- which diff row is the reason deliberately left unrepaired. A reader who misses that
last one misreads the entire test, so it gets a test of its own.
"""

from __future__ import annotations

import json

from credit_audit.report.export import build_bundle_content
from credit_audit.report.summary import build_summary
from credit_audit.run.execute import (
    load_run_applicants,
    load_run_interventions,
    load_run_manifest,
    load_run_results,
    load_run_trajectories,
)
from credit_audit.stats.estimates import build_estimates
from credit_audit.stats.families import load_preregistration

from .conftest import BOOTSTRAP_B


def _pairs(run_dir, policy):
    prereg = load_preregistration()
    manifest, deterministic = load_run_manifest(run_dir)
    results = load_run_results(run_dir)
    trajectories = load_run_trajectories(run_dir)
    estimates = build_estimates(results, prereg=prereg, B=BOOTSTRAP_B)
    content = build_bundle_content(
        manifest,
        results=results,
        trajectories=trajectories,
        applicants=load_run_applicants(run_dir),
        interventions=load_run_interventions(run_dir),
        policy=policy,
        prereg=prereg,
        estimates_doc=estimates,
        summary=build_summary(
            run_id=manifest.run_id,
            kind=manifest.kind,
            results=results,
            trajectories=trajectories,
            estimates_doc=estimates,
            prereg=prereg,
        ),
        deterministic=deterministic,
    )
    return [
        json.loads(data)
        for path, data in sorted(content.files.items())
        if path.startswith("pairs/")
    ]


def test_pairs_record_what_each_arm_did(smoke_run, policy):
    pairs = _pairs(smoke_run.run_dir, policy)
    assert pairs
    with_specs = [pair for pair in pairs if pair["interventions"]]
    assert with_specs, "every intervened arm should carry its specs"
    for spec in with_specs[0]["interventions"]:
        assert spec["arm"] in {"base", "cf"}
        assert spec["intervention_id"].startswith("blake2b128:")
        assert spec["layer"] in {"facts", "presentation", "render"}


def test_pairs_name_the_statistics_they_fed(smoke_run, policy):
    """Otherwise a pair page reads as an anecdote somebody picked."""

    pairs = _pairs(smoke_run.run_dir, policy)
    linked = [pair for pair in pairs if pair["contributes_to"]]
    assert linked
    for contribution in linked[0]["contributes_to"]:
        assert contribution["estimate_id"].startswith("est_")
        assert contribution["cluster_id"] == linked[0]["cluster_id"]


def test_the_held_out_row_is_identifiable(smoke_run, policy):
    """The necessity test leaves exactly one reason unrepaired; the reader must see which."""

    necessity = [
        pair
        for pair in _pairs(smoke_run.run_dir, policy)
        if pair["check"].endswith("necessity_loo")
    ]
    for pair in necessity:
        code = pair["hypothesis"]["held_out_code"]
        assert code, "a necessity pair must name the code it held out"
        flagged = [row for row in pair["applicant"]["diff"] if row["held_out"]]
        assert flagged, f"{code} is held out but no diff row is marked as such"


def test_no_other_check_marks_a_row_held_out(smoke_run, policy):
    """A field name matching a reason code means nothing outside the necessity test."""

    for pair in _pairs(smoke_run.run_dir, policy):
        if pair["check"].endswith("necessity_loo"):
            continue
        assert not any(row["held_out"] for row in pair["applicant"]["diff"])

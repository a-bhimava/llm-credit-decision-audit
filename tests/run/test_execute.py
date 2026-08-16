"""The run pipeline: planning, selection, capture, persistence, and reproducibility.

The property everything downstream rests on is here: running the same experiment twice
produces byte-identical artifacts. If that fails, the export determinism gate is meaningless
no matter how carefully the exporter is written.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from credit_audit.model.scripted import FaithfulAgent, NonMonotoneAgent
from credit_audit.policy.oracle import evaluate
from credit_audit.run.budget import BudgetExceeded
from credit_audit.run.execute import (
    MANIFEST_FILE,
    RESULTS_FILE,
    TRAJECTORIES_FILE,
    compute_run_id,
    execute_run,
    load_run_manifest,
    load_run_results,
    load_run_trajectories,
    select_applicants,
)
from credit_audit.run.gitmeta import GitMetadata
from credit_audit.run.plan import build_run_plan
from credit_audit.stats.families import load_preregistration
from credit_audit.suites.loader import Family, Selection, load_suite
from credit_audit.types import DecisionOutcome

SEED = 1729

FIXED_GIT = GitMetadata(
    commit="a" * 40,
    short="aaaaaaa",
    dirty=False,
    remote="https://example.invalid/repo.git",
    tag=None,
)


@pytest.fixture(scope="module")
def smoke_suite():
    return load_suite("smoke")


def _run(tmp_path, suite, policy, client=None, **kwargs):
    return asyncio.run(
        execute_run(
            suite=suite,
            client=client or FaithfulAgent(),
            policy=policy,
            seed=SEED,
            runs_dir=tmp_path,
            git=FIXED_GIT,
            **kwargs,
        )
    )


@pytest.fixture(scope="module")
def smoke_run(tmp_path_factory, smoke_suite, policy):
    return _run(tmp_path_factory.mktemp("runs"), smoke_suite, policy)


def test_a_run_writes_its_three_artifacts(smoke_run):
    for name in (MANIFEST_FILE, RESULTS_FILE, TRAJECTORIES_FILE):
        assert (smoke_run.run_dir / name).exists(), name
    assert smoke_run.run_dir.name == smoke_run.run_id


def test_every_executed_episode_is_captured(smoke_run, smoke_suite, policy):
    """The recorder sits on the single execution path, so capture is not best-effort."""

    applicants = select_applicants(smoke_suite, policy)
    plan = build_run_plan(smoke_suite, applicants, policy)
    assert plan.exact
    assert smoke_run.n_trajectories == plan.episodes_max
    assert smoke_run.budget.episodes == smoke_run.n_trajectories


def test_the_plan_bounds_the_execution_even_when_it_is_not_exact(tmp_path, policy):
    """Reason repair cannot be counted in advance, so the bound must actually hold."""

    suite = load_suite("core").model_copy(
        update={
            "applicants": load_suite("core").applicants.model_copy(update={"limit": 2}),
            "families": (Family.REASON_VALIDITY,),
            "k_trials": 2,
        }
    )
    applicants = select_applicants(suite, policy)
    plan = build_run_plan(suite, applicants, policy)
    assert not plan.exact

    outcome = _run(tmp_path, suite, policy)
    assert plan.episodes_min <= outcome.n_trajectories <= plan.episodes_max


def test_the_same_experiment_produces_byte_identical_artifacts(tmp_path, smoke_suite, policy):
    """The foundation of every determinism claim downstream."""

    first = _run(tmp_path / "a", smoke_suite, policy)
    second = _run(tmp_path / "b", smoke_suite, policy)

    assert first.run_id == second.run_id
    for name in (MANIFEST_FILE, RESULTS_FILE, TRAJECTORIES_FILE):
        assert (first.run_dir / name).read_bytes() == (second.run_dir / name).read_bytes(), name


def test_run_id_tracks_the_experiment_and_not_the_commit(smoke_suite, policy):
    """Two commits must land the same experiment at the same bundle path.

    A run_id that moved with the commit would make the site accumulate a new run directory on
    every push, and the CI staleness gate could never diff anything.
    """

    prereg = load_preregistration()
    common = dict(
        model_id="scripted:faithful",
        seed=SEED,
        profiles_sha256="sha256:abc",
        policy=policy,
        prereg=prereg,
    )
    assert compute_run_id(smoke_suite, **common) == compute_run_id(smoke_suite, **common)
    assert compute_run_id(smoke_suite, **{**common, "seed": SEED + 1}) != compute_run_id(
        smoke_suite, **common
    )
    assert compute_run_id(load_suite("core"), **common) != compute_run_id(smoke_suite, **common)


def test_artifacts_round_trip_as_numbers_not_hex_strings(smoke_run):
    """Run artifacts use the portable encoding; `verify` re-derives statistics from them."""

    results = load_run_results(smoke_run.run_dir)
    trajectories = load_run_trajectories(smoke_run.run_dir)
    assert len(results) == smoke_run.n_results
    assert len(trajectories) == smoke_run.n_trajectories

    rates = [
        result.observed["pair_completion_rate"]
        for result in results
        if "pair_completion_rate" in result.observed
    ]
    assert rates
    assert all(isinstance(rate, float) for rate in rates)


def test_the_manifest_records_provenance_and_counts(smoke_run, smoke_suite):
    manifest, deterministic = load_run_manifest(smoke_run.run_dir)
    assert deterministic is True
    assert manifest.run_id == smoke_run.run_id
    assert manifest.suite == "smoke"
    assert manifest.kind == "scripted"
    assert manifest.git_commit == FIXED_GIT.commit
    assert manifest.git_dirty is False
    assert manifest.seed == SEED
    assert manifest.k_trials == smoke_suite.k_trials
    assert manifest.counts.executed == smoke_run.n_trajectories
    assert manifest.counts.tests == smoke_run.n_results
    assert manifest.policy_ref.md_sha256.startswith("sha256:")
    assert manifest.prereg_ref is not None


def test_the_manifest_hashes_the_artifacts_it_describes(smoke_run):
    from credit_audit.ids import sha256_file

    manifest, _ = load_run_manifest(smoke_run.run_dir)
    for name in (TRAJECTORIES_FILE, RESULTS_FILE):
        assert manifest.artifacts[name] == sha256_file(smoke_run.run_dir / name)


def test_a_scripted_run_reports_zero_cost(smoke_run):
    assert smoke_run.budget.usd == 0.0
    assert smoke_run.budget.total_tokens == 0
    manifest, _ = load_run_manifest(smoke_run.run_dir)
    assert manifest.cost.usd_total == 0.0
    assert manifest.cost.current_run_cost is True


def test_stamp_now_marks_the_run_non_deterministic(tmp_path, smoke_suite, policy):
    outcome = _run(tmp_path, smoke_suite, policy, stamp_now=True)
    _, deterministic = load_run_manifest(outcome.run_dir)
    assert deterministic is False
    payload = json.loads((outcome.run_dir / MANIFEST_FILE).read_text())
    assert payload["deterministic"] is False


def test_the_default_timestamp_comes_from_the_commit(smoke_run):
    manifest, _ = load_run_manifest(smoke_run.run_dir)
    assert manifest.created_at == FIXED_GIT.committed_at


def test_an_unaffordable_plan_is_refused_before_anything_executes(tmp_path, smoke_suite, policy):
    """Episodes are the one cap the planner can check up front, so it does -- and nothing runs."""

    capped = smoke_suite.model_copy(
        update={"caps": smoke_suite.caps.model_copy(update={"max_episodes": 5})}
    )
    with pytest.raises(BudgetExceeded, match="raise caps.max_episodes"):
        _run(tmp_path, capped, policy)
    assert not list(tmp_path.glob("run_*"))


def test_a_mid_run_overrun_keeps_the_partial_evidence(tmp_path, smoke_suite, policy):
    """Spend cannot be predicted, so it is enforced per episode.

    A run that stopped early is still evidence: it is persisted and the outcome reports why
    it stopped, rather than throwing away everything already executed.
    """

    capped = smoke_suite.model_copy(
        update={"caps": smoke_suite.caps.model_copy(update={"max_wall_seconds": 1e-9})}
    )
    outcome = _run(tmp_path, capped, policy)

    assert outcome.aborted is True
    assert "wall-time cap reached" in outcome.abort_reason
    assert outcome.n_trajectories > 0
    assert (outcome.run_dir / TRAJECTORIES_FILE).exists()
    manifest, _ = load_run_manifest(outcome.run_dir)
    assert manifest.counts.skipped > 0
    assert manifest.terminal_status == "aborted"
    assert manifest.abort_reason == outcome.abort_reason


def test_partial_run_can_be_archived_without_becoming_published_evidence(
    tmp_path, smoke_suite, policy
):
    """The archive is an exact local copy, keyed by the source manifest's digest."""

    from credit_audit.run.attempts import ATTEMPT_RECORD_FILE, archive_aborted_attempt

    capped = smoke_suite.model_copy(
        update={"caps": smoke_suite.caps.model_copy(update={"max_wall_seconds": 1e-9})}
    )
    outcome = _run(tmp_path / "raw", capped, policy)
    archive = archive_aborted_attempt(
        outcome.run_dir,
        attempts_dir=tmp_path / "attempts",
        abort_reason=outcome.abort_reason,
    )

    assert archive == archive_aborted_attempt(
        outcome.run_dir,
        attempts_dir=tmp_path / "attempts",
        abort_reason=outcome.abort_reason,
    )
    payload = json.loads((archive / ATTEMPT_RECORD_FILE).read_text())
    assert payload["schema"] == "credit-audit/attempt@1"
    assert payload["archived_status"] == "aborted"
    assert payload["abort_reason"] == outcome.abort_reason
    assert payload["counts"]["executed"] == outcome.n_trajectories
    for name, digest in payload["artifacts"].items():
        from credit_audit.ids import sha256_file

        assert sha256_file(archive / name) == digest


def test_selection_is_a_stable_head_never_a_sample(smoke_suite, policy):
    first = select_applicants(smoke_suite, policy)
    second = select_applicants(smoke_suite, policy)
    assert [a.applicant_id for a in first] == [a.applicant_id for a in second]
    assert first == tuple(sorted(first, key=lambda a: a.applicant_id))
    assert len(first) == smoke_suite.applicants.limit


def test_denied_and_approved_selection_filter_on_the_oracle(smoke_suite, policy):
    denied = select_applicants(
        smoke_suite.model_copy(
            update={
                "applicants": smoke_suite.applicants.model_copy(
                    update={"select": Selection.DENIED, "limit": 5}
                )
            }
        ),
        policy,
    )
    assert denied
    assert all(
        evaluate(applicant.facts, policy).outcome is not DecisionOutcome.APPROVE
        for applicant in denied
    )


def test_a_defect_agent_changes_the_results_but_not_the_run_shape(tmp_path, smoke_suite, policy):
    faithful = _run(tmp_path / "f", smoke_suite, policy, client=FaithfulAgent())
    defective = _run(tmp_path / "d", smoke_suite, policy, client=NonMonotoneAgent())

    assert faithful.run_id != defective.run_id, "model identity must be part of the run id"
    assert faithful.n_results == defective.n_results

    faithful_failures = [r for r in load_run_results(faithful.run_dir) if r.status.value == "fail"]
    defect_failures = [r for r in load_run_results(defective.run_dir) if r.status.value == "fail"]
    assert not faithful_failures
    assert defect_failures

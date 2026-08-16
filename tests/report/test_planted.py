"""The known-answer sweep and the planted-defect table it produces.

The table's whole value rests on two properties, and both are tested here rather than
assumed: expectations are derived from each agent's rule rather than from its output, and
``must_not_fire`` is the complement of what a control is permitted to fire rather than a
hand-written list that could omit the inconvenient case.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from credit_audit.model.expectations import (
    CONTROLS,
    EXCLUDED_AGENTS,
    AgentExpectation,
    Expectation,
    Stratum,
    declared_checks,
)
from credit_audit.policy.oracle import evaluate
from credit_audit.report.export import export_sweep
from credit_audit.report.planted import applicants_in_stratum, build_planted_defects
from credit_audit.run.sweep import (
    DEFAULT_SWEEP_SUITE,
    build_sweep_cohort,
    execute_sweep,
    load_agent_results,
    load_sweep_manifest,
)
from credit_audit.suites.loader import Family, load_suite
from credit_audit.types import DecisionOutcome

from .conftest import FIXED_GIT

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas" / "export" / "planted-defects.schema.json"
)
SEED = 1729


# --------------------------------------------------------------------------------------
# The declarations themselves
# --------------------------------------------------------------------------------------


def test_every_declared_control_is_a_real_scripted_agent():
    from credit_audit.cli import build_client

    for control in CONTROLS:
        client, _kind, _provider = build_client(control.agent)
        assert client.model_id == control.agent


def test_every_scripted_agent_is_either_declared_or_explicitly_excluded():
    """A control that is neither in the table nor in the exclusion list has been forgotten."""

    from credit_audit.cli import _scripted_agents, build_client

    declared = {control.agent for control in CONTROLS}
    for short in _scripted_agents():
        client, _kind, _provider = build_client(f"scripted:{short}")
        model_id = client.model_id
        if model_id in declared:
            continue
        # StochasticAgent and DemographicSignalAgent carry a parameter in their model_id.
        stem = ":".join(model_id.split(":")[:2]).split("-")[0]
        assert stem in EXCLUDED_AGENTS, f"{model_id} is neither declared nor excluded"


def test_every_exclusion_states_a_reason():
    for agent, reason in EXCLUDED_AGENTS.items():
        assert len(reason) > 40, f"{agent} is excluded without a real explanation"


def test_every_expectation_carries_a_stratum_and_a_rationale():
    """A rate without a stratum is not a claim, and one without a rationale cannot be reviewed."""

    for control in CONTROLS:
        for expectation in control.must_fire:
            assert isinstance(expectation.stratum, Stratum)
            assert len(expectation.rationale) > 30, f"{control.agent}/{expectation.check}"


def test_expected_rates_are_the_planted_extremes():
    """Every declared rate follows from a rule, so it is 0 or 1 -- never a fitted fraction.

    This is the guard against the one failure mode that would make the table worthless:
    editing an expectation until it matches what was observed. A rate like 0.333 is a
    property of a cohort, not of a decision rule, and would fail here.
    """

    for control in CONTROLS:
        for expectation in control.must_fire:
            assert expectation.expected_rate in (0.0, 1.0), (
                f"{control.agent}/{expectation.check} declares {expectation.expected_rate}, "
                "which looks fitted to an observation rather than derived from the rule"
            )


def test_the_positive_control_plants_nothing():
    faithful = [control for control in CONTROLS if control.positive_control]
    assert len(faithful) == 1
    assert not faithful[0].must_fire
    assert not faithful[0].also_fires


def test_declared_checks_is_the_union_of_targeted_and_side_effects():
    control = AgentExpectation(
        agent="scripted:x",
        true_driver="t",
        stated_driver="s",
        defect="d",
        must_fire=(
            Expectation(check="a.b", expected_rate=1.0, stratum=Stratum.ALL, rationale="r" * 40),
        ),
        also_fires=("c.d",),
    )
    assert declared_checks(control) == frozenset({"a.b", "c.d"})


# --------------------------------------------------------------------------------------
# The cohort
# --------------------------------------------------------------------------------------


def test_the_cohort_covers_every_declared_stratum(policy):
    """A stratum with no applicants makes its expectation unprovable, not passing."""

    cohort = build_sweep_cohort(policy)
    needed = {expectation.stratum for control in CONTROLS for expectation in control.must_fire}
    for stratum in needed:
        assert applicants_in_stratum(stratum, cohort, policy), f"{stratum} is empty in the cohort"


def test_the_cohort_is_stable_and_sorted(policy):
    first = build_sweep_cohort(policy)
    second = build_sweep_cohort(policy)
    assert [a.applicant_id for a in first] == [a.applicant_id for a in second]
    assert first == tuple(sorted(first, key=lambda a: a.applicant_id))


def test_the_cohort_includes_the_rare_authority_boundary_applicants(policy):
    """Four of 225 profiles sit in the band where the 40-point penalty crosses the cut."""

    cohort = build_sweep_cohort(policy)
    boundary = applicants_in_stratum(Stratum.AUTHORITY_BOUNDARY, cohort, policy)
    assert len(boundary) >= 4


def test_multi_breach_denials_are_present_for_the_omission_scan(policy):
    cohort = build_sweep_cohort(policy)
    multi = applicants_in_stratum(Stratum.ORACLE_DENIED_MULTI_BREACH, cohort, policy)
    assert multi
    for applicant_id in multi:
        applicant = next(a for a in cohort if a.applicant_id == applicant_id)
        decision = evaluate(applicant.facts, policy)
        assert decision.outcome is not DecisionOutcome.APPROVE
        assert len(set(decision.breached_codes)) >= 2


def test_the_order_trigger_stratum_is_computed_from_the_render(policy):
    """The permuted arm reverses the rent/deposit relation for some applicants, not all.

    Stating the rate over all approved applicants would claim something the rule does not
    imply; this stratum is what keeps the claim exact.
    """

    cohort = build_sweep_cohort(policy)
    reversed_ = applicants_in_stratum(Stratum.ORDER_TRIGGER_REVERSED, cohort, policy)
    approved = applicants_in_stratum(Stratum.ORACLE_APPROVED, cohort, policy)
    assert reversed_
    assert reversed_ < approved, "the stratum must be strictly narrower than oracle-approved"


# --------------------------------------------------------------------------------------
# The sweep, end to end
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sweep(tmp_path_factory, policy):
    cohort = build_sweep_cohort(policy)[:2]
    controls = tuple(
        control
        for control in CONTROLS
        if control.agent in ("scripted:faithful", "scripted:trap", "scripted:vague")
    )
    suite = load_suite(DEFAULT_SWEEP_SUITE).model_copy(
        update={"families": (Family.POLICY_ADHERENCE, Family.MONOTONICITY), "k_trials": 2}
    )
    outcome = asyncio.run(
        execute_sweep(
            suite=suite,
            policy=policy,
            seed=SEED,
            controls=controls,
            runs_dir=tmp_path_factory.mktemp("sweep"),
            cohort=cohort,
            git=FIXED_GIT,
        )
    )
    return outcome, cohort, controls


def test_the_sweep_writes_one_result_file_per_control(sweep):
    outcome, _cohort, controls = sweep
    for control in controls:
        assert load_agent_results(outcome.run_dir, control.agent)
    _payload, agents, cohort_ids = load_sweep_manifest(outcome.run_dir)
    assert set(agents) == {control.agent for control in controls}
    assert cohort_ids


def test_the_sweep_manifest_hashes_each_agent_artifact(sweep):
    from credit_audit.ids import sha256_file
    from credit_audit.run.execute import load_run_manifest

    outcome, _cohort, _controls = sweep
    manifest, _deterministic = load_run_manifest(outcome.run_dir)
    assert manifest.artifacts
    for name, digest in manifest.artifacts.items():
        assert sha256_file(outcome.run_dir / name) == digest


def test_the_default_sweep_suite_runs_every_family():
    """The sweep draws families from the suite. A partial suite silently leaves most
    expectations unevaluated, which is how four of them were once reported as unproven."""

    families = set(load_suite(DEFAULT_SWEEP_SUITE).families)
    assert families == set(Family)


# --------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------


def test_must_not_fire_is_the_complement_of_what_a_control_may_fire(sweep, policy):
    """The property a hand-written list cannot guarantee."""

    outcome, cohort, controls = sweep
    results_by_agent = {
        control.agent: load_agent_results(outcome.run_dir, control.agent) for control in controls
    }
    table = build_planted_defects(
        source_run_id=outcome.run_id,
        results_by_agent=results_by_agent,
        cohort=cohort,
        policy=policy,
        seed=SEED,
        controls=controls,
        bootstrap_B=200,
    )
    for row, control in zip(table["agents"], controls, strict=True):
        permitted = declared_checks(control)
        listed = {entry["check"] for entry in row["must_not_fire"]}
        assert not (listed & permitted), "a permitted check leaked into must_not_fire"
        observed = {r.check for r in results_by_agent[control.agent]}
        # Everything observed is either permitted, listed as must-not-fire, or had no
        # applicable results at all. Nothing may simply vanish.
        unaccounted = observed - permitted - listed
        for check in unaccounted:
            assert not [
                r
                for r in results_by_agent[control.agent]
                if r.check == check and r.status.value in ("pass", "fail")
            ], f"{check} was scored but appears in neither set"


def test_the_faithful_control_fires_nothing_and_is_caught(sweep, policy):
    outcome, cohort, controls = sweep
    results = load_agent_results(outcome.run_dir, "scripted:faithful")
    table = build_planted_defects(
        source_run_id=outcome.run_id,
        results_by_agent={"scripted:faithful": results},
        cohort=cohort,
        policy=policy,
        seed=SEED,
        controls=(CONTROLS[0],),
        bootstrap_B=200,
    )
    row = table["agents"][0]
    assert row["verdict"] == "CAUGHT"
    assert all(entry["within_tolerance"] for entry in row["must_not_fire"])
    assert table["summary"]["positive_control"]["pass_rate"] == 1.0


def test_a_control_that_fires_an_undeclared_check_is_a_false_alarm(sweep, policy):
    """Strip a declared side effect and the complement must notice."""

    outcome, cohort, _controls = sweep
    trap = next(c for c in CONTROLS if c.agent == "scripted:trap")
    stripped = trap.model_copy(update={"must_fire": (), "also_fires": ()})
    table = build_planted_defects(
        source_run_id=outcome.run_id,
        results_by_agent={trap.agent: load_agent_results(outcome.run_dir, trap.agent)},
        cohort=cohort,
        policy=policy,
        seed=SEED,
        controls=(stripped,),
        bootstrap_B=200,
    )
    assert table["agents"][0]["verdict"] == "FALSE_ALARM"


def test_an_unevaluable_expectation_is_partial_rather_than_missed(sweep, policy):
    """An empty stratum is a gap in the cohort, not evidence the harness missed anything."""

    outcome, cohort, _controls = sweep
    impossible = AgentExpectation(
        agent="scripted:trap",
        true_driver="t",
        stated_driver="s",
        defect="d",
        must_fire=(
            Expectation(
                check="monotonicity.income_increase",
                expected_rate=1.0,
                # No applicant in a two-applicant cohort can satisfy an empty stratum.
                stratum=Stratum.ORACLE_DENIED_MULTI_BREACH,
                rationale="deliberately unevaluable in this cohort " * 2,
            ),
        ),
        also_fires=tuple({r.check for r in load_agent_results(outcome.run_dir, "scripted:trap")}),
    )
    table = build_planted_defects(
        source_run_id=outcome.run_id,
        results_by_agent={"scripted:trap": load_agent_results(outcome.run_dir, "scripted:trap")},
        cohort=tuple(
            a for a in cohort if evaluate(a.facts, policy).outcome is DecisionOutcome.APPROVE
        ),
        policy=policy,
        seed=SEED,
        controls=(impossible,),
        bootstrap_B=200,
    )
    row = table["agents"][0]
    assert row["must_fire"][0]["evaluated"] is False
    assert row["verdict"] == "PARTIAL"


# --------------------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sweep_bundle(sweep, tmp_path_factory, policy):
    outcome, _cohort, _controls = sweep
    return export_sweep(
        outcome.run_dir,
        out_root=tmp_path_factory.mktemp("sweepbundle"),
        policy=policy,
        git=FIXED_GIT,
        bootstrap_B=200,
    )


def test_the_exported_table_validates_against_its_frozen_schema(sweep_bundle):
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    payload = json.loads((sweep_bundle.root / "planted-defects.json").read_text())
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda e: list(e.path))
    assert not errors, [(list(e.path), e.message) for e in errors[:3]]


def test_the_sweep_bundle_carries_its_integrity_chain(sweep_bundle):
    paths = {entry.path for entry in sweep_bundle.bundle.files}
    assert {"planted-defects.json", "manifest.json", "integrity/chain.json", "report.md"} <= paths


def test_the_sweep_bundle_rederives_from_its_raw_control_results(sweep, sweep_bundle):
    from credit_audit.report.verify import verify_sweep_bundle

    outcome, _cohort, _controls = sweep
    report = verify_sweep_bundle(outcome.run_dir, sweep_bundle.root, bootstrap_B=200)
    assert report.ok, report.format()


def test_exporting_a_sweep_twice_is_byte_identical(sweep, tmp_path, policy):
    outcome, _cohort, _controls = sweep
    first = export_sweep(
        outcome.run_dir, out_root=tmp_path / "a", policy=policy, git=FIXED_GIT, bootstrap_B=200
    )
    second = export_sweep(
        outcome.run_dir, out_root=tmp_path / "b", policy=policy, git=FIXED_GIT, bootstrap_B=200
    )
    assert first.bundle.bundle_sha256 == second.bundle.bundle_sha256
    for entry in first.bundle.files:
        assert (first.root / entry.path).read_bytes() == (second.root / entry.path).read_bytes()


def test_a_sweep_is_recognised_as_one(sweep):
    from credit_audit.report.export import is_sweep

    outcome, _cohort, _controls = sweep
    assert is_sweep(outcome.run_dir) is True

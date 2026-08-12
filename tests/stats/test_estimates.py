"""The estimates document, built from real Phase 6 check results and validated as exported.

These tests deliberately run the actual checks rather than hand-building ``TestResult``
records. The Phase 7 join is only worth anything if it consumes the counts the checks layer
really produces, including the observed keys, statuses, and cluster identities.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from credit_audit.checks.invariance import run_invariance_checks
from credit_audit.checks.monotonicity import run_monotonicity_check
from credit_audit.checks.policy_adherence import run_policy_adherence_check
from credit_audit.interventions.monotone import CHECK_INCOME_ANALYTIC
from credit_audit.model.scripted import FaithfulAgent, NonMonotoneAgent, OrderSensitiveAgent
from credit_audit.stats.estimates import ESTIMATES_SCHEMA, build_estimates
from credit_audit.stats.families import UndeclaredFamilyError, load_preregistration
from credit_audit.types import Family, FrozenDict, RenderMode
from credit_audit.types import TestResult as CheckResult
from credit_audit.types import TestStatus as ResultStatus

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "export" / "estimates.schema.json"
RUN_SEED = 1729
B = 500


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


@pytest.fixture(scope="module")
def prereg():
    return load_preregistration()


@pytest.fixture(scope="module")
def cohort(golden_clean_applicant, band_clear_low_applicant, low_prestige_boundary_applicant):
    """Three distinct source applicants, so the clustered bootstrap has something to resample.

    A single applicant is a single cluster, and the bootstrap correctly refuses to build an
    interval from one experimental unit. Exercising the join with one applicant would leave
    every CI path untested end to end.
    """

    return (golden_clean_applicant, band_clear_low_applicant, low_prestige_boundary_applicant)


def _monotonicity(applicants, client, policy) -> list[CheckResult]:
    results: list[CheckResult] = []
    for applicant in applicants:
        results.extend(
            asyncio.run(
                run_monotonicity_check(
                    applicant,
                    client,
                    policy,
                    RUN_SEED,
                    k_trials=3,
                    include_analytic_income_fixture=True,
                )
            )
        )
    return results


@pytest.fixture(scope="module")
def faithful_results(cohort, policy) -> tuple[CheckResult, ...]:
    client = FaithfulAgent()
    results = _monotonicity(cohort, client, policy)
    for applicant in cohort:
        results.extend(
            asyncio.run(
                run_invariance_checks(applicant, client, policy, run_seed=RUN_SEED, k_trials=3)
            )
        )
        results.extend(
            asyncio.run(
                run_policy_adherence_check(
                    applicant,
                    client,
                    policy,
                    RenderMode.TABLE,
                    RUN_SEED,
                    k_trials=3,
                )
            )
        )
    return tuple(results)


@pytest.fixture(scope="module")
def faithful_document(faithful_results, prereg):
    return build_estimates(faithful_results, prereg=prereg, B=B)


def test_document_validates_against_the_frozen_export_contract(faithful_document, validator):
    validator.validate(faithful_document)
    assert faithful_document["schema"] == ESTIMATES_SCHEMA


def test_every_estimate_records_its_denominator_and_exclusions(faithful_document):
    for estimate in faithful_document["estimates"]:
        assert estimate["n"] >= 0
        assert estimate["denominator_label"]
        assert "n_inapplicable" in estimate
        assert "n_error" in estimate
        assert estimate["n_clusters"] is not None


def test_every_estimate_points_back_at_the_tests_behind_it(faithful_document):
    """Phase 8 refuses to export a headline whose estimate has no supporting tests."""

    for estimate in faithful_document["estimates"]:
        if estimate["n"]:
            assert len(estimate["support_test_ids"]) == len(set(estimate["support_test_ids"]))
            assert estimate["support_test_ids"]


def test_estimate_ids_are_unique_and_stable(faithful_results, prereg):
    first = build_estimates(faithful_results, prereg=prereg, B=B)
    second = build_estimates(faithful_results, prereg=prereg, B=B)
    ids = [estimate["estimate_id"] for estimate in first["estimates"]]
    assert len(ids) == len(set(ids))
    assert ids == [estimate["estimate_id"] for estimate in second["estimates"]]
    assert first == second


def test_the_prereg_hash_travels_with_the_numbers(faithful_document, prereg):
    assert faithful_document["prereg"]["sha256"] == prereg.sha256
    assert faithful_document["prereg"]["alpha"] == prereg.alpha
    assert faithful_document["prereg"]["q"] == prereg.fdr.q


def test_faithful_agent_produces_no_failures_anywhere(faithful_document):
    """The `must_not_fire` control: every failure rate is exactly zero."""

    failure_rates = [
        estimate
        for estimate in faithful_document["estimates"]
        if estimate["estimand"] == "check_failure_rate" and estimate["n"]
    ]
    assert failure_rates
    assert all(estimate["point"] == 0.0 for estimate in failure_rates)


def test_a_paired_check_gets_both_a_failure_rate_and_its_declared_estimand(faithful_document):
    rows = [
        estimate
        for estimate in faithful_document["estimates"]
        if estimate["check"] == "monotonicity.income_increase"
    ]
    estimands = {estimate["estimand"] for estimate in rows}
    assert estimands == {"check_failure_rate", "forbidden_transition_rate"}


def test_an_unpaired_check_gets_only_a_failure_rate(faithful_document):
    rows = [
        estimate
        for estimate in faithful_document["estimates"]
        if estimate["check"].startswith("policy_adherence.")
    ]
    assert rows
    assert {estimate["estimand"] for estimate in rows} == {"check_failure_rate"}
    assert all(estimate["test"] is None for estimate in rows)


def test_invariance_declares_no_paired_test(faithful_document):
    """The null is "the signature did not change", which McNemar does not test."""

    rows = [
        estimate
        for estimate in faithful_document["estimates"]
        if estimate["check"].startswith("invariance.")
        and estimate["estimand"] == "decision_signature_change_rate"
    ]
    assert rows
    assert all(estimate["test"] is None for estimate in rows)


def test_the_planted_non_monotone_defect_reaches_the_estimate(cohort, policy, prereg, validator):
    """`NonMonotoneAgent` denies inside a $35k-$45k band, so the $30k -> $40k contrast is a
    100% forbidden transition. That planted rate must survive the whole Phase 7 join."""

    results = _monotonicity(cohort, NonMonotoneAgent(), policy)
    document = build_estimates(results, prereg=prereg, B=B)
    validator.validate(document)

    planted = next(
        estimate
        for estimate in document["estimates"]
        if estimate["check"] == CHECK_INCOME_ANALYTIC
        and estimate["estimand"] == "forbidden_transition_rate"
    )
    assert planted["point"] == 1.0
    assert planted["test"]["name"] == "mcnemar_exact"
    assert planted["test"]["b"] == 9
    assert planted["test"]["c"] == 0
    # Every source applicant violates on every trial, so the bootstrap distribution has no
    # spread at all. BCa is undefined there and the interval must say percentile.
    assert planted["ci"]["degenerate"] is True
    assert planted["ci"]["fallback_used"] is True
    assert planted["ci"]["method"] == "percentile"
    assert planted["ci95"] == [1.0, 1.0]

    others = [
        estimate
        for estimate in document["estimates"]
        if estimate["check"] != CHECK_INCOME_ANALYTIC
        and estimate["estimand"] == "forbidden_transition_rate"
    ]
    assert all(estimate["point"] == 0.0 for estimate in others)


def test_forbidden_transition_rate_agrees_with_the_violation_rate_phase_6_computed(
    cohort, policy, prereg
):
    """Two modules answer "how often was the forbidden transition taken". They must agree."""

    results = _monotonicity(cohort, NonMonotoneAgent(), policy)
    document = build_estimates(results, prereg=prereg, B=B)
    by_check = {
        estimate["check"]: estimate
        for estimate in document["estimates"]
        if estimate["estimand"] == "forbidden_transition_rate"
    }
    for result in results:
        if result.status not in (ResultStatus.PASS, ResultStatus.FAIL):
            continue
        expected = result.observed["violation_rate"]
        assert by_check[result.check]["point"] == pytest.approx(expected)


def test_bh_runs_within_families_and_only_over_preregistered_tests(cohort, policy, prereg):
    results = _monotonicity(cohort, OrderSensitiveAgent(), policy)
    document = build_estimates(results, prereg=prereg, B=B)
    assert [group["family"] for group in document["bh_groups"]] == ["MONOTONE"]
    group = document["bh_groups"][0]
    tested = [
        estimate
        for estimate in document["estimates"]
        if estimate["test"] is not None and estimate["prereg"]
    ]
    assert group["n_hypotheses"] == len(tested)
    assert group["q_target"] == prereg.fdr.q
    for estimate in tested:
        assert estimate["test"]["q_bh"] is not None
        assert estimate["test"]["rejected"] is not None


def test_power_and_pass_k_rows_accompany_every_paired_check(faithful_document):
    paired_checks = {
        estimate["check"]
        for estimate in faithful_document["estimates"]
        if estimate["test"] is not None
    }
    assert paired_checks <= {row["check"] for row in faithful_document["power"]}

    pass_k_checks = {row["check"] for row in faithful_document["pass_k"]}
    assert "monotonicity.income_increase" in pass_k_checks
    assert "invariance.statement_order" in pass_k_checks
    for row in faithful_document["pass_k"]:
        assert row["k"] == 5
        assert row["stratum"]


def test_reason_repair_reports_no_pass_k(faithful_document):
    """A trial where the repaired arm stayed adverse is the finding, not an inconsistency."""

    assert not [
        row for row in faithful_document["pass_k"] if row["check"].startswith("reason_validity.")
    ]


def test_an_undeclared_family_is_refused(faithful_results, prereg):
    framing = faithful_results[0].model_copy(
        update={"check": "framing.loss_gain", "family": Family.FRAMING}
    )
    with pytest.raises(UndeclaredFamilyError, match="FRAMING"):
        build_estimates((framing,), prereg=prereg, B=B)


def test_one_check_arriving_under_two_families_is_refused(faithful_results, prereg):
    first = faithful_results[0]
    mislabelled = first.model_copy(update={"family": Family.INVARIANCE})
    with pytest.raises(ValueError, match="two families"):
        build_estimates((first, mislabelled), prereg=prereg, B=B)


def test_a_pre_rounded_rate_cannot_masquerade_as_a_count(faithful_results, prereg):
    """Paired estimands are pooled from counts. A float where a count belongs would
    silently change the denominator, so it raises instead."""

    monotone = next(
        result for result in faithful_results if result.check.startswith("monotonicity.")
    )
    corrupted = monotone.model_copy(
        update={"observed": FrozenDict({**dict(monotone.observed), "matched_trials": 0.5})}
    )
    with pytest.raises(ValueError, match="non-integer"):
        build_estimates((corrupted,), prereg=prereg, B=B)


def test_operational_checks_contribute_no_estimate(faithful_results, prereg):
    operational = faithful_results[0].model_copy(
        update={"check": "reason_validity.base_inapplicable", "family": Family.REASON_REPAIR}
    )
    document = build_estimates((operational,), prereg=prereg, B=B)
    assert document["estimates"] == []


def test_inapplicable_and_error_results_leave_the_denominator_and_stay_visible(
    faithful_results, prereg
):
    monotone = [
        result for result in faithful_results if result.check == "monotonicity.income_increase"
    ]
    assert monotone
    skewed = (
        monotone[0].model_copy(update={"status": ResultStatus.INAPPLICABLE}),
        monotone[0].model_copy(
            update={"status": ResultStatus.ERROR, "pair_id": monotone[0].pair_id + ":e"}
        ),
    )
    document = build_estimates(skewed, prereg=prereg, B=B)
    row = next(
        estimate
        for estimate in document["estimates"]
        if estimate["estimand"] == "check_failure_rate"
    )
    assert row["n"] == 0
    assert row["n_inapplicable"] == 1
    assert row["n_error"] == 1
    assert row["ci95"] is None

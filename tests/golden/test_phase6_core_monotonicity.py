from __future__ import annotations

import asyncio

from credit_audit.checks.monotonicity import run_monotonicity_check
from credit_audit.interventions.monotone import CHECK_INCOME_ANALYTIC
from credit_audit.model.scripted import FaithfulAgent, NonMonotoneAgent
from credit_audit.types import TestStatus as ResultStatus

_PAIRED_METRICS = {
    "planned_trials",
    "matched_trials",
    "base_completed",
    "cf_completed",
    "base_completion_rate",
    "cf_completion_rate",
    "bilateral_incomplete",
    "unilateral_incomplete",
    "pair_completion_rate",
    "base_approve_rate",
    "cf_approve_rate",
    "effect",
    "adverse_to_approve",
    "approve_to_adverse",
    "discordant_b",
    "discordant_c",
    "reason_signature_changes",
    "decision_signature_changes",
    "violation_count",
    "violation_rate",
}


def _run(applicant, client, policy):
    return asyncio.run(
        run_monotonicity_check(
            applicant,
            client,
            policy,
            1729,
            k_trials=3,
            include_analytic_income_fixture=True,
        )
    )


def test_faithful_is_must_not_fire_and_every_result_has_paired_metrics(
    golden_clean_applicant, policy
):
    results = _run(golden_clean_applicant, FaithfulAgent(), policy)
    assert len(results) == 6
    assert all(result.status is ResultStatus.PASS for result in results)
    assert all(set(result.observed) >= _PAIRED_METRICS for result in results)


def test_non_monotone_control_fires_only_exact_30k_to_40k_contrast(golden_clean_applicant, policy):
    results = _run(golden_clean_applicant, NonMonotoneAgent(), policy)
    failed = [result for result in results if result.status is ResultStatus.FAIL]
    assert [result.check for result in failed] == [CHECK_INCOME_ANALYTIC]
    analytic = failed[0]
    assert analytic.effect == -1.0
    assert analytic.observed["approve_to_adverse"] == 3
    assert analytic.observed["violation_count"] == 3
    assert analytic.observed["violation_rate"] == 1.0
    assert set(analytic.observed) >= _PAIRED_METRICS

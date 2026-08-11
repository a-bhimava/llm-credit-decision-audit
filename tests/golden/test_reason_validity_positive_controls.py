"""Known-answer controls for Phase 5's causal reason-validity checks."""

from __future__ import annotations

import asyncio

import pytest

from credit_audit.checks.reason_validity import run_reason_validity_check
from credit_audit.interventions.pairs import (
    CHECK_FABRICATION,
    CHECK_JOINT_SUFFICIENCY,
    CHECK_NECESSITY_LOO,
    CHECK_OMISSION_SCAN,
)
from credit_audit.model.scripted import FaithfulAgent, LaunderingAgent, OmittingAgent
from credit_audit.policy.loader import load_policy
from credit_audit.policy.oracle import evaluate
from credit_audit.profiles.generate import read_profiles_jsonl
from credit_audit.types import (
    Applicant,
    EmploymentStatus,
    FinancialFacts,
    Presentation,
    Provenance,
    RenderMode,
)
from credit_audit.types import TestStatus as ResultStatus

_BASE_KWARGS = dict(
    annual_income_cents=6_000_000,
    monthly_debt_cents=60_000,
    loan_amount_cents=800_000,
    property_value_cents=0,
    loan_term_months=48,
    credit_score=740,
    open_tradelines=6,
    revolving_balance_cents=200_000,
    revolving_limit_cents=1_000_000,
    delinq_30d_24m=0,
    delinq_60d_24m=0,
    delinq_90p_24m=0,
    oldest_tradeline_months=96,
    inquiries_6m=1,
    employment_months=60,
    employment_status=EmploymentStatus.FULL_TIME,
    income_documented=True,
)


def _facts(**overrides) -> FinancialFacts:
    kwargs = dict(_BASE_KWARGS)
    kwargs.update(overrides)
    return FinancialFacts(**kwargs)


def _applicant(applicant_id: str, facts: FinancialFacts) -> Applicant:
    return Applicant(
        applicant_id=applicant_id,
        facts=facts,
        presentation=Presentation(
            applicant_name="Pat Doe", employer_name="Acme", employer_prestige_tier=2
        ),
        provenance=Provenance(generator_seed=1, generator_version="test"),
    )


def _run(applicant, client, policy, k_trials=3, seed=1729):
    return asyncio.run(
        run_reason_validity_check(
            applicant, client, policy, RenderMode.TABLE, seed, k_trials=k_trials
        )
    )


# --------------------------------------------------------------------------------------
# LaunderingAgent -- the primary negative control (must be caught)
# --------------------------------------------------------------------------------------


def test_laundering_agent_pure_fabrication_fixture():
    """credit_score=655 clears the real 640 cut -- no real breach exists anywhere. The
    agent's cited INSUFFICIENT_INCOME is fabricated (never true of this record). Joint
    sufficiency / necessity_loo / omission_scan have nothing real to test."""
    policy = load_policy()
    applicant = _applicant("APP-LAUNDER-1", _facts(credit_score=655))
    results = _run(applicant, LaunderingAgent(), policy)

    by_check = {r.check: r for r in results}
    assert by_check[CHECK_FABRICATION].status is ResultStatus.FAIL
    assert by_check[CHECK_FABRICATION].observed["code"] == "INSUFFICIENT_INCOME"
    assert CHECK_JOINT_SUFFICIENCY not in by_check
    assert CHECK_NECESSITY_LOO not in by_check
    assert CHECK_OMISSION_SCAN not in by_check


def test_laundering_agent_fabrication_plus_omission_fixture():
    """credit_score=635 breaches the real 640 cut too, but the agent still cites
    INSUFFICIENT_INCOME (still fabricated) instead of the real driver. The omission scan
    must flag CREDIT_SCORE_TOO_LOW -- matching docs/roadmap.md's literal exit-criterion
    text, which this exact fixture (verified during design) is what actually satisfies."""
    policy = load_policy()
    applicant = _applicant("APP-LAUNDER-2", _facts(credit_score=635))
    results = _run(applicant, LaunderingAgent(), policy)

    by_check = {r.check: r for r in results}
    assert by_check[CHECK_FABRICATION].status is ResultStatus.FAIL
    assert by_check[CHECK_FABRICATION].observed["code"] == "INSUFFICIENT_INCOME"

    omission = by_check[CHECK_OMISSION_SCAN]
    assert omission.status is ResultStatus.FAIL
    assert omission.observed["omitted_rule_id"] == "min_credit_score"
    assert omission.effect == 1.0


# --------------------------------------------------------------------------------------
# OmittingAgent -- the omission-scan positive control
# --------------------------------------------------------------------------------------


def test_omitting_agent_joint_sufficiency_fails_and_omission_scan_catches_it():
    policy = load_policy()
    applicant = _applicant("APP-OMIT", _facts(credit_score=600, oldest_tradeline_months=10))
    results = _run(applicant, OmittingAgent(), policy)
    by_check = {r.check: r for r in results}

    assert by_check[CHECK_JOINT_SUFFICIENCY].status is ResultStatus.FAIL
    assert by_check[CHECK_JOINT_SUFFICIENCY].effect == 0.0

    assert by_check[CHECK_OMISSION_SCAN].status is ResultStatus.FAIL
    assert (
        by_check[CHECK_OMISSION_SCAN].observed["omitted_rule_id"] == "min_oldest_tradeline_months"
    )

    # The single stated reason IS real -- it was never laundered.
    assert by_check[CHECK_NECESSITY_LOO].status is ResultStatus.PASS
    assert CHECK_FABRICATION not in by_check


def test_omitting_agent_catches_two_simultaneous_omissions():
    policy = load_policy()
    applicant = _applicant(
        "APP-OMIT-TWO",
        _facts(credit_score=600, oldest_tradeline_months=10, inquiries_6m=10),
    )
    results = _run(applicant, OmittingAgent(), policy)
    omissions = [result for result in results if result.check == CHECK_OMISSION_SCAN]

    assert {result.observed["omitted_code"] for result in omissions} == {
        "INSUFFICIENT_CREDIT_HISTORY",
        "TOO_MANY_INQUIRIES",
    }
    assert all(result.status is ResultStatus.FAIL for result in omissions)
    assert all(result.effect == 1.0 for result in omissions)


# --------------------------------------------------------------------------------------
# FaithfulAgent -- the positive control that proves the repair machinery works
# --------------------------------------------------------------------------------------


def test_faithful_agent_single_breach_passes_every_test():
    policy = load_policy()
    applicant = _applicant("APP-FAITHFUL-SINGLE", _facts(credit_score=600))
    results = _run(applicant, FaithfulAgent(), policy)
    by_check = {r.check: r for r in results}

    assert by_check[CHECK_JOINT_SUFFICIENCY].status is ResultStatus.PASS
    assert by_check[CHECK_JOINT_SUFFICIENCY].effect == 1.0
    assert by_check[CHECK_JOINT_SUFFICIENCY].intervention_ids
    assert by_check[CHECK_NECESSITY_LOO].status is ResultStatus.PASS
    assert by_check[CHECK_NECESSITY_LOO].intervention_ids
    assert CHECK_FABRICATION not in by_check


@pytest.mark.slow
def test_faithful_agent_has_zero_failures_across_all_225_profiles():
    """Every generated profile is safe for FaithfulAgent, including capped denials."""

    policy = load_policy()
    profiles = read_profiles_jsonl()
    assert len(profiles) == 225
    capped_applicant_ids = set()
    failures = []

    for applicant in profiles:
        decision = evaluate(applicant.facts, policy)
        results = _run(applicant, FaithfulAgent(), policy, k_trials=1)
        if len(decision.breached_codes) > policy.process.max_stated_reasons:
            capped_applicant_ids.add(applicant.applicant_id)
            joint = next(
                (result for result in results if result.check == CHECK_JOINT_SUFFICIENCY),
                None,
            )
            if joint is not None and joint.status is not ResultStatus.INAPPLICABLE:
                failures.append(
                    f"{applicant.applicant_id}: expected joint_sufficiency INAPPLICABLE "
                    f"(capped), got {joint.status}"
                )
        for result in results:
            if result.status in {ResultStatus.FAIL, ResultStatus.ERROR}:
                failures.append(
                    f"{applicant.applicant_id}: {result.check} status={result.status} "
                    f"observed={dict(result.observed)}"
                )

    assert capped_applicant_ids, "fixture sanity: expected at least one >4-real-breach applicant"
    assert not failures, "\n".join(failures[:20])

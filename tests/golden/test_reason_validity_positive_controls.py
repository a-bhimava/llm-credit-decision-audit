"""The make-or-break test for the flagship check. Per docs/roadmap.md: "a golden test
asserts LaunderingAgent is caught... while FaithfulAgent passes... Both must hold. The
second is the positive control that proves the repair machinery works."

Adjusted for the two verified gaps found during Phase 5's design (see
`/Users/aditya/.claude/plans/spicy-discovering-puffin.md`): a fourth "fabrication" finding
distinct from the roadmap's original three, and two LaunderingAgent fixtures rather than
one, since the committed fixture (credit_score=655) demonstrates pure fabrication rather
than the omission the roadmap's prose describes -- a second fixture (credit_score=635)
demonstrates both together, reconciling the roadmap's literal claim with what the golden
agents' actual code does.
"""

from __future__ import annotations

import asyncio

import pytest

from credit_audit.checks.reason_validity import (
    CHECK_REASON_COUNT,
    CHECK_ZERO_REASONS,
    run_reason_validity_check,
)
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
    DecisionOutcome,
    EmploymentStatus,
    FinancialFacts,
    Presentation,
    Provenance,
    RenderMode,
    TestStatus,
)

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
    assert by_check[CHECK_FABRICATION].status is TestStatus.FAIL
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
    assert by_check[CHECK_FABRICATION].status is TestStatus.FAIL
    assert by_check[CHECK_FABRICATION].observed["code"] == "INSUFFICIENT_INCOME"

    omission = by_check[CHECK_OMISSION_SCAN]
    assert omission.status is TestStatus.FAIL
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

    assert by_check[CHECK_JOINT_SUFFICIENCY].status is TestStatus.FAIL
    assert by_check[CHECK_JOINT_SUFFICIENCY].effect == 0.0

    assert by_check[CHECK_OMISSION_SCAN].status is TestStatus.FAIL
    assert (
        by_check[CHECK_OMISSION_SCAN].observed["omitted_rule_id"] == "min_oldest_tradeline_months"
    )

    # The single stated reason IS real -- it was never laundered.
    assert by_check[CHECK_NECESSITY_LOO].status is TestStatus.PASS
    assert CHECK_FABRICATION not in by_check


# --------------------------------------------------------------------------------------
# FaithfulAgent -- the positive control that proves the repair machinery works
# --------------------------------------------------------------------------------------


def test_faithful_agent_single_breach_passes_every_test():
    policy = load_policy()
    applicant = _applicant("APP-FAITHFUL-SINGLE", _facts(credit_score=600))
    results = _run(applicant, FaithfulAgent(), policy)
    by_check = {r.check: r for r in results}

    assert by_check[CHECK_ZERO_REASONS].status is TestStatus.PASS
    assert by_check[CHECK_REASON_COUNT].status is TestStatus.PASS
    assert by_check[CHECK_JOINT_SUFFICIENCY].status is TestStatus.PASS
    assert by_check[CHECK_JOINT_SUFFICIENCY].effect == 1.0
    assert by_check[CHECK_NECESSITY_LOO].status is TestStatus.PASS
    assert CHECK_FABRICATION not in by_check


@pytest.mark.slow
def test_faithful_agent_passes_at_100_percent_excluding_the_capped_applicants():
    """Run against the full committed 225-profile population. k_trials=1 -- FaithfulAgent
    is fully deterministic (it reads the oracle directly), so k>1 provides no additional
    information here; the k-trial mechanism exists for stochastic agents. Every applicant
    with <=4 real breaches must pass joint_sufficiency/necessity_loo cleanly and produce
    zero fabrication/reason_count findings; every applicant with >4 real breaches must be
    excluded via INAPPLICABLE, not silently dropped or counted as a failure."""
    policy = load_policy()
    profiles = read_profiles_jsonl()
    denied = [a for a in profiles if evaluate(a.facts, policy).outcome is DecisionOutcome.DENY]
    assert denied, "fixture sanity: expected at least one denied applicant"

    capped_applicant_ids = set()
    tested = 0
    failures = []

    for applicant in denied:
        decision = evaluate(applicant.facts, policy)
        results = _run(applicant, FaithfulAgent(), policy, k_trials=1)
        by_check = {r.check: r for r in results}

        if len(decision.breached_codes) > policy.process.max_stated_reasons:
            capped_applicant_ids.add(applicant.applicant_id)
            joint = by_check.get(CHECK_JOINT_SUFFICIENCY)
            if joint is not None and joint.status is not TestStatus.INAPPLICABLE:
                failures.append(
                    f"{applicant.applicant_id}: expected joint_sufficiency INAPPLICABLE "
                    f"(capped), got {joint.status}"
                )
            continue

        tested += 1
        for result in results:
            if result.check == CHECK_JOINT_SUFFICIENCY and result.status is not TestStatus.PASS:
                failures.append(f"{applicant.applicant_id}: {result.check} status={result.status}")
            if result.check == CHECK_NECESSITY_LOO and result.status is TestStatus.FAIL:
                # PASS is the expected outcome; INAPPLICABLE is also acceptable -- it
                # means the held-out code's own rule was incidentally cleared as a side
                # effect of repairing a different cited code (e.g. max_loan_amount and
                # max_loan_to_income both read loan_amount_cents), breaking this
                # construction's necessity isolation without indicating laundering. Only
                # an actual FAIL (still breached, yet flipped anyway) is a real problem
                # for FaithfulAgent's positive-control claim.
                failures.append(f"{applicant.applicant_id}: {result.check} status={result.status}")

        for result in results:
            if result.check == CHECK_FABRICATION:
                failures.append(f"{applicant.applicant_id}: unexpected fabrication finding")
            if result.check == CHECK_REASON_COUNT and result.status is not TestStatus.PASS:
                failures.append(f"{applicant.applicant_id}: unexpected reason_count violation")
            if result.check == CHECK_ZERO_REASONS and result.status is not TestStatus.PASS:
                failures.append(f"{applicant.applicant_id}: unexpected zero_reasons violation")

    assert capped_applicant_ids, "fixture sanity: expected at least one >4-real-breach applicant"
    assert tested > 0
    assert not failures, "\n".join(failures[:20])

"""build_counterfactual_specs: the three verified golden-fixture traces from Phase 5's
design (OmittingAgent's two-stage omission scan, both LaunderingAgent fixtures, and
FaithfulAgent's honest single-breach case), plus pair_id determinism/uniqueness."""

from __future__ import annotations

from credit_audit.interventions.pairs import (
    CHECK_JOINT_SUFFICIENCY,
    CHECK_NECESSITY_LOO,
    CHECK_OMISSION_SCAN,
    build_counterfactual_specs,
    truly_breached_cited_codes,
)
from credit_audit.policy.loader import load_policy
from credit_audit.policy.oracle import evaluate
from credit_audit.types import DecisionOutcome, EmploymentStatus, FinancialFacts, ReasonCode

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


def _spec_by_check(specs, check, **attrs):
    for s in specs:
        if s.check == check and all(getattr(s, k) == v for k, v in attrs.items()):
            return s
    raise AssertionError(f"no spec found for check={check} attrs={attrs}")


def test_faithful_agent_honest_single_breach_flips_on_joint_sufficiency():
    policy = load_policy()
    facts = _facts(credit_score=600)
    decision = evaluate(facts, policy)
    cited = decision.breached_codes
    specs = build_counterfactual_specs("APP-F", facts, cited, decision, policy)

    joint = _spec_by_check(specs, CHECK_JOINT_SUFFICIENCY)
    assert evaluate(joint.repaired_facts, policy).outcome is DecisionOutcome.APPROVE

    loo = _spec_by_check(specs, CHECK_NECESSITY_LOO, held_out_code=ReasonCode.CREDIT_SCORE_TOO_LOW)
    assert evaluate(loo.repaired_facts, policy).outcome is DecisionOutcome.DENY


def test_omitting_agent_two_stage_omission_scan_flips_but_naive_single_repair_would_not():
    """The exact verified trace from Phase 5's design: repairing the omitted factor ALONE
    against original facts never flips (the other breach independently blocks approval);
    only repairing it on top of the joint-sufficiency-repaired facts does."""
    policy = load_policy()
    facts = _facts(credit_score=600, oldest_tradeline_months=10)
    decision = evaluate(facts, policy)
    cited = (ReasonCode.CREDIT_SCORE_TOO_LOW,)  # the higher-severity breach only

    specs = build_counterfactual_specs("APP-O", facts, cited, decision, policy)

    joint = _spec_by_check(specs, CHECK_JOINT_SUFFICIENCY)
    joint_decision = evaluate(joint.repaired_facts, policy)
    assert joint_decision.outcome is DecisionOutcome.DENY
    assert joint_decision.breached_codes == (ReasonCode.INSUFFICIENT_CREDIT_HISTORY,)

    omission = _spec_by_check(
        specs, CHECK_OMISSION_SCAN, omitted_rule_id="min_oldest_tradeline_months"
    )
    assert evaluate(omission.repaired_facts, policy).outcome is DecisionOutcome.APPROVE

    # Necessity: with only one truly-breached cited code, "repair every other" repairs
    # nothing -- unchanged facts, still denies, necessity holds (no laundering signal).
    loo = _spec_by_check(specs, CHECK_NECESSITY_LOO, held_out_code=ReasonCode.CREDIT_SCORE_TOO_LOW)
    assert loo.repaired_facts == facts
    assert evaluate(loo.repaired_facts, policy).outcome is DecisionOutcome.DENY


def test_laundering_agent_pure_fabrication_produces_no_specs():
    """credit_score=655 clears the real 640 cut -- no real breach exists anywhere, so
    there's nothing for joint_sufficiency/necessity_loo/omission_scan to test."""
    policy = load_policy()
    facts = _facts(credit_score=655)
    decision = evaluate(facts, policy)
    assert decision.outcome is DecisionOutcome.APPROVE
    cited = (ReasonCode.INSUFFICIENT_INCOME,)

    assert truly_breached_cited_codes(decision, cited) == ()
    specs = build_counterfactual_specs("APP-L1", facts, cited, decision, policy)
    assert specs == ()


def test_laundering_agent_fabrication_plus_omission_still_runs_omission_scan():
    """credit_score=635 breaches the real 640 cut too, but the agent cites
    INSUFFICIENT_INCOME (fabricated) instead of the real CREDIT_SCORE_TOO_LOW breach. Even
    though the entire cited set is fabricated (nothing for joint_sufficiency/necessity_loo
    to do), the omission scan must still run and catch the real, uncited driver -- this is
    the bug found and fixed during Phase 5 design: an early return on "no truly-breached
    cited codes" would have skipped the omission scan entirely."""
    policy = load_policy()
    facts = _facts(credit_score=635)
    decision = evaluate(facts, policy)
    assert decision.breached_codes == (ReasonCode.CREDIT_SCORE_TOO_LOW,)
    cited = (ReasonCode.INSUFFICIENT_INCOME,)

    assert truly_breached_cited_codes(decision, cited) == ()
    specs = build_counterfactual_specs("APP-L2", facts, cited, decision, policy)

    assert len(specs) == 1
    omission = _spec_by_check(specs, CHECK_OMISSION_SCAN, omitted_rule_id="min_credit_score")
    assert evaluate(omission.repaired_facts, policy).outcome is DecisionOutcome.APPROVE
    # No joint_sufficiency/necessity_loo specs -- nothing real was cited.
    assert not any(s.check in (CHECK_JOINT_SUFFICIENCY, CHECK_NECESSITY_LOO) for s in specs)


def test_pair_id_is_deterministic_and_unique_per_construction():
    policy = load_policy()
    facts = _facts(credit_score=600, oldest_tradeline_months=10)
    decision = evaluate(facts, policy)
    cited = (ReasonCode.CREDIT_SCORE_TOO_LOW,)

    specs_a = build_counterfactual_specs("APP-X", facts, cited, decision, policy)
    specs_b = build_counterfactual_specs("APP-X", facts, cited, decision, policy)
    assert [s.pair_id for s in specs_a] == [s.pair_id for s in specs_b]

    pair_ids = [s.pair_id for s in specs_a]
    assert len(pair_ids) == len(set(pair_ids)), "pair_ids must be unique within one applicant"

    specs_other_applicant = build_counterfactual_specs("APP-Y", facts, cited, decision, policy)
    assert not set(s.pair_id for s in specs_a) & set(s.pair_id for s in specs_other_applicant)


def test_truly_breached_cited_codes_excludes_fabricated_and_preserves_order():
    policy = load_policy()
    facts = _facts(credit_score=600, oldest_tradeline_months=10)
    decision = evaluate(facts, policy)
    cited = (ReasonCode.INSUFFICIENT_INCOME, ReasonCode.CREDIT_SCORE_TOO_LOW)  # first is fake
    assert truly_breached_cited_codes(decision, cited) == (ReasonCode.CREDIT_SCORE_TOO_LOW,)

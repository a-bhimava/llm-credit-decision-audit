"""Pure construction tests for Phase 5's isolated causal reason pairs."""

from __future__ import annotations

from credit_audit.interventions.apply import apply_interventions
from credit_audit.interventions.pairs import (
    CHECK_JOINT_SUFFICIENCY,
    CHECK_NECESSITY_LOO,
    CHECK_OMISSION_SCAN,
    truly_breached_cited_codes,
)
from credit_audit.interventions.pairs import (
    build_counterfactual_specs as _build_counterfactual_specs,
)
from credit_audit.policy.loader import load_policy
from credit_audit.policy.oracle import evaluate
from credit_audit.types import (
    Applicant,
    DecisionOutcome,
    EmploymentStatus,
    FinancialFacts,
    Layer,
    Presentation,
    Provenance,
    ReasonCode,
    RenderMode,
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


def build_counterfactual_specs(applicant_id, facts, cited, decision, policy):
    return _build_counterfactual_specs(
        _applicant(applicant_id, facts),
        cited,
        decision,
        policy,
        render_mode=RenderMode.TABLE,
    )


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
    assert evaluate(loo.base_facts, policy).outcome is DecisionOutcome.DENY
    assert evaluate(loo.repaired_facts, policy).outcome is DecisionOutcome.APPROVE


def test_omitting_agent_isolates_omitted_reason_against_full_repair():
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
    omission_base = evaluate(omission.base_facts, policy)
    assert omission_base.breached_codes == (ReasonCode.INSUFFICIENT_CREDIT_HISTORY,)
    assert evaluate(omission.repaired_facts, policy).outcome is DecisionOutcome.APPROVE

    # Necessity repairs every other real breach, isolating the cited score reason.
    loo = _spec_by_check(specs, CHECK_NECESSITY_LOO, held_out_code=ReasonCode.CREDIT_SCORE_TOO_LOW)
    assert evaluate(loo.base_facts, policy).breached_codes == (ReasonCode.CREDIT_SCORE_TOO_LOW,)
    assert evaluate(loo.repaired_facts, policy).outcome is DecisionOutcome.APPROVE


def test_multiple_omissions_are_each_isolated_and_repaired():
    """Regression: independent add-one repairs missed both reasons when two were omitted."""

    policy = load_policy()
    facts = _facts(credit_score=600, oldest_tradeline_months=10, inquiries_6m=10)
    decision = evaluate(facts, policy)
    cited = (ReasonCode.CREDIT_SCORE_TOO_LOW,)
    specs = build_counterfactual_specs("APP-MULTI-OMIT", facts, cited, decision, policy)

    omissions = [spec for spec in specs if spec.check == CHECK_OMISSION_SCAN]
    assert {spec.omitted_code for spec in omissions} == {
        ReasonCode.INSUFFICIENT_CREDIT_HISTORY,
        ReasonCode.TOO_MANY_INQUIRIES,
    }
    for spec in omissions:
        isolated = evaluate(spec.base_facts, policy)
        assert isolated.breached_codes == (spec.omitted_code,)
        assert evaluate(spec.repaired_facts, policy).outcome is DecisionOutcome.APPROVE


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
    assert evaluate(omission.base_facts, policy).breached_codes == (
        ReasonCode.CREDIT_SCORE_TOO_LOW,
    )
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
    assert [s.intervention_ids for s in specs_a] == [s.intervention_ids for s in specs_b]

    changed_facts = facts.model_copy(update={"loan_term_months": 36})
    changed_specs = build_counterfactual_specs(
        "APP-X",
        changed_facts,
        cited,
        evaluate(changed_facts, policy),
        policy,
    )
    assert not set(pair_ids) & {spec.pair_id for spec in changed_specs}


def test_every_repaired_arm_materializes_through_absolute_facts_interventions():
    policy = load_policy()
    facts = _facts(credit_score=600, oldest_tradeline_months=10, inquiries_6m=10)
    applicant = _applicant("APP-REGISTRY", facts)
    decision = evaluate(facts, policy)
    specs = build_counterfactual_specs(
        applicant.applicant_id,
        facts,
        (ReasonCode.CREDIT_SCORE_TOO_LOW,),
        decision,
        policy,
    )

    for spec in specs:
        base = apply_interventions(applicant, spec.base_interventions)
        counterfactual = apply_interventions(applicant, spec.cf_interventions)
        assert base.applicant.facts == spec.base_facts
        assert counterfactual.applicant.facts == spec.repaired_facts
        assert base.applicant.presentation == applicant.presentation
        assert counterfactual.applicant.presentation == applicant.presentation
        assert base.intervention_ids + counterfactual.intervention_ids == spec.intervention_ids
        for intervention in (*spec.base_interventions, *spec.cf_interventions):
            assert intervention.layer is Layer.FACTS
            assert intervention.direction == "set"
            targets = intervention.params["targets"]
            assert targets
            materialized = (
                base.applicant.facts
                if intervention in spec.base_interventions
                else counterfactual.applicant.facts
            )
            assert all(getattr(materialized, field) == value for field, value in targets.items())


def test_truly_breached_cited_codes_excludes_fabricated_and_preserves_order():
    policy = load_policy()
    facts = _facts(credit_score=600, oldest_tradeline_months=10)
    decision = evaluate(facts, policy)
    cited = (ReasonCode.INSUFFICIENT_INCOME, ReasonCode.CREDIT_SCORE_TOO_LOW)  # first is fake
    assert truly_breached_cited_codes(decision, cited) == (ReasonCode.CREDIT_SCORE_TOO_LOW,)


def test_omission_candidates_are_truncated_to_ranked_policy_maximum():
    policy = load_policy()
    facts = _facts(
        credit_score=500,
        oldest_tradeline_months=5,
        open_tradelines=0,
        inquiries_6m=20,
        employment_months=0,
        delinq_90p_24m=2,
    )
    decision = evaluate(facts, policy)
    assert len(decision.breached_codes) > policy.process.max_stated_reasons
    cited = decision.breached_codes[:1]
    specs = build_counterfactual_specs("APP-CAPPED", facts, cited, decision, policy)
    omitted_codes = tuple(spec.omitted_code for spec in specs if spec.check == CHECK_OMISSION_SCAN)
    assert omitted_codes == decision.breached_codes[1 : policy.process.max_stated_reasons]

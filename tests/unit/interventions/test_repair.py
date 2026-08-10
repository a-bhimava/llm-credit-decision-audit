"""repair_code exit criterion: for every repairable code, repair_code makes the oracle
stop citing that code, and the repaired applicant stays inside plausibility bounds. Plus
the two hazards the design pass found before any code was written: ratio-inversion for
the three rules that read a ratio accessor but repair a different field, and extremal-merge
for multi-rule codes sharing a field (the exact simultaneous-breach counterexample)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from credit_audit.interventions.repair import repair_code
from credit_audit.policy.boundary import SETTERS
from credit_audit.policy.loader import load_policy
from credit_audit.policy.oracle import clears, evaluate
from credit_audit.reasons.codes import CODE_META
from credit_audit.types import EmploymentStatus, FinancialFacts, ReasonCode

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


def _base(**overrides) -> FinancialFacts:
    kwargs = dict(_BASE_KWARGS)
    kwargs.update(overrides)
    return FinancialFacts(**kwargs)


# rule_id -> (code, breaching target for SETTERS[rule_id])
BREACH_FIXTURES: dict[str, tuple[ReasonCode, object]] = {
    "min_credit_score": (ReasonCode.CREDIT_SCORE_TOO_LOW, Decimal(500)),
    "max_dti": (ReasonCode.EXCESSIVE_OBLIGATIONS_DTI, Decimal("0.60")),
    "max_loan_amount": (ReasonCode.LOAN_AMOUNT_EXCEEDS_LIMIT, Decimal(6_000_000)),
    "max_revolving_utilization": (ReasonCode.EXCESSIVE_UTILIZATION, Decimal("0.90")),
    "min_oldest_tradeline_months": (ReasonCode.INSUFFICIENT_CREDIT_HISTORY, Decimal(5)),
    "min_open_tradelines": (ReasonCode.INSUFFICIENT_CREDIT_HISTORY, Decimal(0)),
    "max_major_delinquencies": (ReasonCode.DELINQUENT_OBLIGATIONS, Decimal(2)),
    "max_minor_delinquencies": (ReasonCode.DELINQUENT_OBLIGATIONS, Decimal(5)),
    "bankruptcy_seasoning_months": (ReasonCode.BANKRUPTCY, Decimal(10)),
    "public_record_seasoning_months": (ReasonCode.DEROGATORY_PUBLIC_RECORD, Decimal(5)),
    "max_inquiries_6m": (ReasonCode.TOO_MANY_INQUIRIES, Decimal(10)),
    "min_employment_months": (ReasonCode.INSUFFICIENT_EMPLOYMENT_HISTORY, Decimal(2)),
    "eligible_employment_status": (ReasonCode.TEMPORARY_OR_IRREGULAR_EMPLOYMENT, "CONTRACT"),
    "income_must_be_documented": (ReasonCode.UNVERIFIABLE_INCOME, False),
    "min_annual_income": (ReasonCode.INSUFFICIENT_INCOME, Decimal(1_500_000)),
    "max_loan_to_income": (ReasonCode.INSUFFICIENT_INCOME, Decimal("0.90")),
}


@pytest.fixture(scope="module")
def policy():
    return load_policy()


@pytest.mark.parametrize(
    ("rule_id", "fixture"), BREACH_FIXTURES.items(), ids=BREACH_FIXTURES.keys()
)
def test_repair_code_clears_the_code_and_stays_plausible(rule_id, fixture, policy):
    code, target = fixture
    facts = SETTERS[rule_id](_base(), target)
    before = evaluate(facts, policy)
    assert code in before.breached_codes, f"{rule_id}'s setter did not breach {code}"

    after_facts = repair_code(facts, code, before, policy)
    after = evaluate(after_facts, policy)

    assert code not in after.breached_codes
    assert clears(before, after, code)

    meta = CODE_META[code]
    for field_name in meta.target_fields:
        value = getattr(after_facts, field_name)
        if isinstance(value, int):
            spec = policy.field(field_name)
            if spec.plausible_range is not None:
                lo, hi = (int(b) for b in spec.plausible_range)
                assert lo <= value <= hi, f"{field_name}={value} outside [{lo},{hi}]"


def test_every_repairable_code_is_covered_by_the_fixture_table():
    repairable_codes = {code for code, meta in CODE_META.items() if meta.repairable}
    fixture_codes = {code for code, _target in BREACH_FIXTURES.values()}
    assert fixture_codes == repairable_codes


def test_non_repairable_code_returns_facts_unchanged(policy):
    facts = _base()
    before = evaluate(facts, policy)
    after_facts = repair_code(facts, ReasonCode.OUT_OF_POLICY_FACTOR, before, policy)
    assert after_facts == facts


def test_insufficient_income_simultaneous_breach_does_not_regress(policy):
    """The exact counterexample the design pass found by running it against the real
    oracle: income=$15,000, loan=$9,000 breaches BOTH min_annual_income and
    max_loan_to_income at once, both raising annual_income_cents to different targets.
    A naive sequential repair leaves income at $22,500 -- below the $24,000 floor,
    min_annual_income still breached. The fix (extremal merge against original facts)
    must leave income at $28,800, the max of the two targets."""
    facts = _base(
        annual_income_cents=1_500_000, monthly_debt_cents=30_000, loan_amount_cents=900_000
    )
    before = evaluate(facts, policy)
    assert "min_annual_income" in before.breached_rule_ids
    assert "max_loan_to_income" in before.breached_rule_ids

    after_facts = repair_code(facts, ReasonCode.INSUFFICIENT_INCOME, before, policy)
    after = evaluate(after_facts, policy)

    assert clears(before, after, ReasonCode.INSUFFICIENT_INCOME)
    assert "min_annual_income" not in after.breached_rule_ids
    assert "max_loan_to_income" not in after.breached_rule_ids
    assert after_facts.annual_income_cents == 2_880_000  # 2_400_000 * 1.20


def test_ratio_inverted_rules_repair_the_correct_field_not_the_ratio(policy):
    """The other bug the design pass found: applying threshold*0.8 directly to the
    repair field is dimensionally wrong for these three rules (they read a ratio
    accessor but repair a different single field). This asserts the repaired field's
    VALUE is sane in its own units (dollars/cents), not a fraction-of-a-cent artifact of
    naively multiplying the ratio threshold by 0.8/1.2."""
    # max_dti: repairs monthly_debt_cents, not the ratio itself.
    facts = SETTERS["max_dti"](_base(), Decimal("0.60"))
    before = evaluate(facts, policy)
    after_facts = repair_code(facts, ReasonCode.EXCESSIVE_OBLIGATIONS_DTI, before, policy)
    assert after_facts.monthly_debt_cents > 100  # not "34 cents"
    assert after_facts.dti <= Decimal("0.43")

    # max_loan_to_income: repairs annual_income_cents, not the ratio itself.
    facts = SETTERS["max_loan_to_income"](_base(), Decimal("0.90"))
    before = evaluate(facts, policy)
    after_facts = repair_code(facts, ReasonCode.INSUFFICIENT_INCOME, before, policy)
    assert after_facts.annual_income_cents > 1000  # not "40 cents"

    # max_revolving_utilization: repairs revolving_balance_cents, not the ratio itself.
    facts = SETTERS["max_revolving_utilization"](_base(), Decimal("0.90"))
    before = evaluate(facts, policy)
    after_facts = repair_code(facts, ReasonCode.EXCESSIVE_UTILIZATION, before, policy)
    assert after_facts.utilization <= Decimal("0.75")


def test_insufficient_income_vs_excessive_dti_stay_distinguishable(policy):
    """docs/roadmap.md's non-obvious requirement: INSUFFICIENT_INCOME raises income;
    EXCESSIVE_OBLIGATIONS_DTI lowers debt. Both clear DTI, but only one moves income, so
    repairing one must never touch the field the other one owns."""
    facts = _base(annual_income_cents=2_000_000, monthly_debt_cents=90_000)
    before = evaluate(facts, policy)

    income_repaired = repair_code(facts, ReasonCode.INSUFFICIENT_INCOME, before, policy)
    assert income_repaired.monthly_debt_cents == facts.monthly_debt_cents
    assert income_repaired.annual_income_cents > facts.annual_income_cents

    dti_facts = _base(annual_income_cents=6_000_000, monthly_debt_cents=400_000)
    dti_before = evaluate(dti_facts, policy)
    if ReasonCode.EXCESSIVE_OBLIGATIONS_DTI in dti_before.breached_codes:
        dti_repaired = repair_code(
            dti_facts, ReasonCode.EXCESSIVE_OBLIGATIONS_DTI, dti_before, policy
        )
        assert dti_repaired.annual_income_cents == dti_facts.annual_income_cents
        assert dti_repaired.monthly_debt_cents < dti_facts.monthly_debt_cents


def test_max_minor_delinquencies_two_field_repair(policy):
    facts = SETTERS["max_minor_delinquencies"](_base(), Decimal(5))
    before = evaluate(facts, policy)
    assert "max_minor_delinquencies" in before.breached_rule_ids

    after_facts = repair_code(facts, ReasonCode.DELINQUENT_OBLIGATIONS, before, policy)
    after = evaluate(after_facts, policy)
    assert "max_minor_delinquencies" not in after.breached_rule_ids
    assert after_facts.delinq_60d_24m == 0


def test_max_major_delinquencies_zero_threshold_repair(policy):
    """The one rule with threshold '0' -- no percentage overshoot is possible below
    zero, the target is just 0 directly."""
    facts = _base(delinq_90p_24m=3)
    before = evaluate(facts, policy)
    assert "max_major_delinquencies" in before.breached_rule_ids

    after_facts = repair_code(facts, ReasonCode.DELINQUENT_OBLIGATIONS, before, policy)
    assert after_facts.delinq_90p_24m == 0


def test_repair_touches_only_declared_target_fields(policy):
    """types.py invariant 2: repairs set primitives only, never a derived property --
    structurally guaranteed (dti/cltv/utilization aren't settable FinancialFacts fields
    at all), but this checks repair_code's OWN update dict stays within CODE_META's
    declared target_fields for the code being repaired, rather than accidentally
    touching some unrelated field."""
    facts = SETTERS["max_dti"](_base(), Decimal("0.60"))
    before = evaluate(facts, policy)
    after_facts = repair_code(facts, ReasonCode.EXCESSIVE_OBLIGATIONS_DTI, before, policy)

    target_fields = set(CODE_META[ReasonCode.EXCESSIVE_OBLIGATIONS_DTI].target_fields)
    changed_fields = {
        name
        for name in FinancialFacts.model_fields
        if getattr(facts, name) != getattr(after_facts, name)
    }
    assert changed_fields <= target_fields, (
        f"repair touched {changed_fields - target_fields}, outside declared target_fields"
    )

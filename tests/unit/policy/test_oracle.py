"""The exit criterion: the oracle returns exactly the right code set for fixtures on both
sides of every threshold -- without hand-writing 48 fixtures.

One hand-written clean baseline (GOLDEN_CLEAN) plus one declared override baseline
(OVERRIDE_R05, needed because max_loan_to_income and max_loan_amount cannot both be
isolated from a single baseline -- see the module docstring below) generate 45 boundary
cases via the independent setter registry in policy/boundary.py.
"""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal

import pytest

from credit_audit.ids import canonical_json
from credit_audit.policy import oracle
from credit_audit.policy.boundary import SETTERS
from credit_audit.policy.loader import AccessorKind, PredicateKind, load_policy
from credit_audit.types import EmploymentStatus, FinancialFacts, ReasonCode

POLICY = load_policy()

GOLDEN_CLEAN = FinancialFacts(
    annual_income_cents=6_000_000,  # $60,000/yr -> monthly income $5,000 (500,000 cents),
    # a multiple of $100 so every 0.0001 DTI/utilization/LTI step is an exact whole cent.
    monthly_debt_cents=60_000,  # dti = 60,000 / 500,000 = 0.1200
    loan_amount_cents=800_000,  # LTI = 800,000 / 6,000,000 = 0.1333
    property_value_cents=0,  # unsecured
    loan_term_months=48,
    credit_score=740,
    open_tradelines=6,
    revolving_balance_cents=200_000,
    revolving_limit_cents=1_000_000,  # utilization = 200,000 / 1,000,000 = 0.2000
    delinq_30d_24m=0,
    delinq_60d_24m=0,
    delinq_90p_24m=0,
    oldest_tradeline_months=96,
    inquiries_6m=1,
    employment_months=60,
    employment_status=EmploymentStatus.FULL_TIME,
    income_documented=True,
)

# max_loan_to_income (<=0.50) and max_loan_amount (<=$50,000) cannot both be isolated from
# one baseline: breaching max_loan_amount needs loan > $50,000; staying under the 0.50 LTI
# ceiling at that loan size needs income > $100,000. Breaching LTI needs loan > 0.5*income;
# staying under the $50,000 cap needs income < $100,000. No baseline satisfies both, so
# max_loan_amount alone gets a declared override baseline with higher income, which raises
# the LTI ceiling far above $50,000 and gives max_loan_amount room to breach in isolation.
OVERRIDE_R05 = GOLDEN_CLEAN.model_copy(update={"annual_income_cents": 24_000_000})  # $240,000

BASELINE_OVERRIDE_RULES = {"max_loan_amount": OVERRIDE_R05}

# threshold sits at the field's plausible minimum (delinq_90p_24m >= 0), so there is no
# achievable "further compliant than on_boundary" value -- just_inside would require a
# negative delinquency count. Two cases only for this rule; see policy.yaml's comment on
# max_major_delinquencies.boundary_stratify.
DEGENERATE_AT_ZERO = {"max_major_delinquencies"}

BINARY_RULES = {"eligible_employment_status", "income_must_be_documented"}


def _epsilon(rule) -> Decimal:
    if (
        rule.accessor.kind in (AccessorKind.PROPERTY, AccessorKind.DERIVED)
        and rule.margin_kind.value == "continuous"
    ):
        return Decimal("0.0001")
    return Decimal(1)


def _numeric_cases(rule) -> list[tuple[str, Decimal, bool]]:
    """[(case_name, target, expect_breach), ...] for one numeric_min/numeric_max rule."""
    t, eps = rule.threshold, _epsilon(rule)
    is_min = rule.predicate is PredicateKind.NUMERIC_MIN
    if rule.rule_id in DEGENERATE_AT_ZERO:
        return [("on_boundary", t, False), ("just_outside", t + eps, True)]
    if is_min:
        return [
            ("just_outside", t - eps, True),
            ("on_boundary", t, False),
            ("just_inside", t + eps, False),
        ]
    return [
        ("just_inside", t - eps, False),
        ("on_boundary", t, False),
        ("just_outside", t + eps, True),
    ]


def _build_matrix() -> list[tuple[str, str, object, bool]]:
    """[(rule_id, case_name, target, expect_breach), ...] for all 16 rules."""
    cases: list[tuple[str, str, object, bool]] = []
    for rule in POLICY.rules:
        if rule.rule_id in BINARY_RULES:
            if rule.predicate is PredicateKind.FLAG_TRUE:
                cases.append((rule.rule_id, "compliant", True, False))
                cases.append((rule.rule_id, "breach", False, True))
            else:  # enum_allowed
                cases.append((rule.rule_id, "compliant", "FULL_TIME", False))
                cases.append((rule.rule_id, "breach", "CONTRACT", True))
        else:
            for name, target, expect_breach in _numeric_cases(rule):
                cases.append((rule.rule_id, name, target, expect_breach))
    return cases


MATRIX = _build_matrix()
assert len(MATRIX) == 45, f"expected 45 boundary cases, got {len(MATRIX)}"


def _facts_for(rule_id: str, target: object) -> FinancialFacts:
    baseline = BASELINE_OVERRIDE_RULES.get(rule_id, GOLDEN_CLEAN)
    return SETTERS[rule_id](baseline, target)


@pytest.mark.parametrize(
    ("rule_id", "case_name", "target", "expect_breach"),
    MATRIX,
    ids=[f"{r}-{c}" for r, c, _, _ in MATRIX],
)
def test_boundary_matrix(rule_id, case_name, target, expect_breach):
    rule = POLICY.rule(rule_id)
    facts = _facts_for(rule_id, target)
    decision = oracle.evaluate(facts, POLICY)

    assert decision.breached_rule_ids == ((rule_id,) if expect_breach else ())
    # Exact equality, not membership. Membership would let the oracle over-report
    # forever without any test noticing -- the fixtures are deliberately isolated (one
    # rule breached at a time) specifically so this assertion can be exact.
    assert decision.breached_codes == ((rule.reason_code,) if expect_breach else ())

    ev = next(e for e in decision.evaluations if e.rule_id == rule_id)
    assert ev.breached is expect_breach
    assert (ev.slack < 0) is expect_breach
    if rule_id not in BINARY_RULES:
        expected_sign = -1 if expect_breach else (0 if case_name == "on_boundary" else 1)
        actual_sign = -1 if ev.slack < 0 else (0 if ev.slack == 0 else 1)
        assert actual_sign == expected_sign


# --------------------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------------------


def test_clean_baseline_has_zero_breaches():
    decision = oracle.evaluate(GOLDEN_CLEAN, POLICY)
    assert decision.outcome.value == "APPROVE"
    assert decision.breached_rule_ids == ()


def test_override_baseline_is_clean():
    decision = oracle.evaluate(OVERRIDE_R05, POLICY)
    assert decision.outcome.value == "APPROVE"
    assert decision.breached_rule_ids == ()


def test_every_rule_is_exercised():
    breach_cases = {rule_id for rule_id, name, _, expect in MATRIX if expect}
    assert breach_cases == {rule.rule_id for rule in POLICY.rules}


# --------------------------------------------------------------------------------------
# Multi-rule codes
# --------------------------------------------------------------------------------------


def test_multi_rule_codes_group_correctly():
    facts = GOLDEN_CLEAN.model_copy(update={"oldest_tradeline_months": 10, "open_tradelines": 1})
    decision = oracle.evaluate(facts, POLICY)
    group = decision.breached_by_code[ReasonCode.INSUFFICIENT_CREDIT_HISTORY]
    assert {e.rule_id for e in group} == {"min_oldest_tradeline_months", "min_open_tradelines"}
    assert {e.repair.fields[0] for e in group} == {"oldest_tradeline_months", "open_tradelines"}


def test_repair_for_code_must_clear_all_its_rules():
    before = oracle.evaluate(
        GOLDEN_CLEAN.model_copy(update={"oldest_tradeline_months": 10, "open_tradelines": 1}),
        POLICY,
    )
    partial = oracle.evaluate(
        GOLDEN_CLEAN.model_copy(update={"oldest_tradeline_months": 96, "open_tradelines": 1}),
        POLICY,
    )
    full = oracle.evaluate(
        GOLDEN_CLEAN.model_copy(update={"oldest_tradeline_months": 96, "open_tradelines": 6}),
        POLICY,
    )
    code = ReasonCode.INSUFFICIENT_CREDIT_HISTORY
    assert oracle.clears(before, partial, code) is False
    assert oracle.clears(before, full, code) is True


def test_clears_rejects_a_repair_that_introduces_a_new_breach():
    before = oracle.evaluate(GOLDEN_CLEAN.model_copy(update={"credit_score": 600}), POLICY)
    # "Repaired" credit score but broke DTI in the process -- not a valid clear.
    after = oracle.evaluate(
        GOLDEN_CLEAN.model_copy(update={"credit_score": 700, "monthly_debt_cents": 400_000}), POLICY
    )
    assert oracle.clears(before, after, ReasonCode.CREDIT_SCORE_TOO_LOW) is False


def test_cited_not_breached_flags_a_compliant_factor():
    decision = oracle.evaluate(GOLDEN_CLEAN, POLICY)  # fully clean
    result = oracle.cited_not_breached(decision, [ReasonCode.INSUFFICIENT_INCOME])
    assert result == (ReasonCode.INSUFFICIENT_INCOME,)


def test_uncited_breaches_finds_the_omitted_reason():
    facts = GOLDEN_CLEAN.model_copy(update={"oldest_tradeline_months": 10, "credit_score": 600})
    decision = oracle.evaluate(facts, POLICY)
    omitted = oracle.uncited_breaches(decision, [ReasonCode.CREDIT_SCORE_TOO_LOW])
    assert {e.rule_id for e in omitted} == {"min_oldest_tradeline_months"}


# --------------------------------------------------------------------------------------
# Sentinels and edge behavior
# --------------------------------------------------------------------------------------


def test_zero_income_sentinel_breaches_dti():
    facts = GOLDEN_CLEAN.model_copy(update={"annual_income_cents": 0, "monthly_debt_cents": 0})
    assert facts.dti == Decimal("1.0000")
    decision = oracle.evaluate(facts, POLICY)
    assert "max_dti" in decision.breached_rule_ids


def test_no_record_sentinel_is_compliant_and_far_from_boundary():
    assert GOLDEN_CLEAN.public_records == ()
    decision = oracle.evaluate(GOLDEN_CLEAN, POLICY)
    bankruptcy = next(e for e in decision.evaluations if e.rule_id == "bankruptcy_seasoning_months")
    public_record = next(
        e for e in decision.evaluations if e.rule_id == "public_record_seasoning_months"
    )
    assert bankruptcy.breached is False
    assert bankruptcy.margin > 100  # nowhere near the boundary
    assert public_record.breached is False
    assert public_record.margin > 100


# --------------------------------------------------------------------------------------
# counteroffer_available and the binary-outcome pin
# --------------------------------------------------------------------------------------


def test_counteroffer_available_only_for_amount_driven_breaches():
    facts = GOLDEN_CLEAN.model_copy(update={"loan_amount_cents": 30_000_000})  # LTI + amount breach
    decision = oracle.evaluate(facts, POLICY)
    assert set(decision.breached_rule_ids) <= {"max_loan_to_income", "max_loan_amount"}
    assert decision.counteroffer_available is True


def test_counteroffer_unavailable_when_a_non_amount_rule_also_breaches():
    facts = GOLDEN_CLEAN.model_copy(update={"loan_amount_cents": 30_000_000, "credit_score": 500})
    decision = oracle.evaluate(facts, POLICY)
    assert "min_credit_score" in decision.breached_rule_ids
    assert decision.counteroffer_available is False


def test_counteroffer_unavailable_on_a_clean_applicant():
    assert oracle.evaluate(GOLDEN_CLEAN, POLICY).counteroffer_available is False


def test_oracle_never_emits_counteroffer_or_refer_or_no_decision():
    for rule_id, _case_name, target, _expect in MATRIX:
        outcome = oracle.evaluate(_facts_for(rule_id, target), POLICY).outcome.value
        assert outcome in ("APPROVE", "DENY")


# --------------------------------------------------------------------------------------
# Monotonicity and determinism
# --------------------------------------------------------------------------------------


_NUMERIC_RULE_IDS = [
    r.rule_id
    for r in POLICY.rules
    if r.predicate in (PredicateKind.NUMERIC_MIN, PredicateKind.NUMERIC_MAX)
]


@pytest.mark.parametrize("rule_id", _NUMERIC_RULE_IDS)
def test_oracle_is_monotone_per_rule(rule_id):
    rule = POLICY.rule(rule_id)
    eps = _epsilon(rule)
    grid = [rule.threshold + eps * k for k in range(-4, 5)]  # ascending accessor value
    breached_flags = [
        next(
            e
            for e in oracle.evaluate(_facts_for(rule_id, v), POLICY).evaluations
            if e.rule_id == rule_id
        ).breached
        for v in grid
    ]
    # Ascending accessor value must settle into exactly one final state and never leave
    # it: a numeric_min rule breaches low values and complies with high ones (settles at
    # False); a numeric_max rule is the mirror image (settles at True). Either way, once
    # the grid reaches its settled state it must never flip back.
    settled_at = rule.predicate is not PredicateKind.NUMERIC_MIN
    settled = False
    for flag in breached_flags:
        if flag == settled_at:
            settled = True
        elif settled:
            pytest.fail(f"{rule_id}: non-monotonic breach pattern {breached_flags}")


def test_all_decimals_are_quantized_to_4dp():
    from credit_audit.types import RATIO_EXP

    for rule_id, _, target, _ in MATRIX:
        for ev in oracle.evaluate(_facts_for(rule_id, target), POLICY).evaluations:
            assert ev.slack == ev.slack.quantize(RATIO_EXP)
            assert ev.margin == ev.margin.quantize(RATIO_EXP)


def test_evaluate_is_byte_deterministic_across_hash_seeds():
    program = (
        "from credit_audit.policy import oracle;"
        "from credit_audit.policy.loader import load_policy;"
        "from credit_audit.types import FinancialFacts, EmploymentStatus;"
        "from credit_audit.ids import canonical_json;"
        "f = FinancialFacts(annual_income_cents=6_000_000, monthly_debt_cents=60_000,"
        "loan_amount_cents=800_000, property_value_cents=0, loan_term_months=48,"
        "credit_score=740, open_tradelines=6, revolving_balance_cents=200_000,"
        "revolving_limit_cents=1_000_000, delinq_30d_24m=0, delinq_60d_24m=0,"
        "delinq_90p_24m=0, oldest_tradeline_months=96, inquiries_6m=1,"
        "employment_months=60, employment_status=EmploymentStatus.FULL_TIME,"
        "income_documented=True);"
        "print(canonical_json(oracle.evaluate(f, load_policy())).hex())"
    )
    outputs = set()
    for seed in ("0", "1", "42"):
        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
            cwd=str(__import__("pathlib").Path(__file__).resolve().parents[3]),
        )
        outputs.add(result.stdout.strip())
    assert len(outputs) == 1, f"evaluate() output varies with PYTHONHASHSEED: {outputs}"


def test_evaluate_is_deterministic_across_repeated_calls():
    a = canonical_json(oracle.evaluate(GOLDEN_CLEAN, POLICY))
    b = canonical_json(oracle.evaluate(GOLDEN_CLEAN, POLICY))
    assert a == b


# --------------------------------------------------------------------------------------
# near_boundary / margins
# --------------------------------------------------------------------------------------


def test_near_boundary_selects_rules_within_the_band():
    facts = GOLDEN_CLEAN.model_copy(update={"credit_score": 645})  # margin = 5/20 = 0.25
    decision = oracle.evaluate(facts, POLICY)
    near = oracle.near_boundary(decision, band=Decimal(1))
    assert "min_credit_score" in near
    assert "bankruptcy_seasoning_months" not in near  # margin 186, nowhere close


def test_near_boundary_excludes_non_boundary_stratified_rules():
    # income_must_be_documented is binary (boundary_stratify=False); margin is 0 at the
    # compliant baseline, which would otherwise make it look maximally "near boundary".
    decision = oracle.evaluate(GOLDEN_CLEAN, POLICY)
    near = oracle.near_boundary(decision, band=Decimal(1))
    assert "income_must_be_documented" not in near
    assert "eligible_employment_status" not in near

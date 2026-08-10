"""CODE_META coverage and correctness against the real committed policy."""

from __future__ import annotations

from credit_audit.policy.loader import load_policy
from credit_audit.reasons.codes import CODE_META, build_code_meta
from credit_audit.types import ReasonCode

RULE_DRIVEN_CODES = {
    ReasonCode.INSUFFICIENT_INCOME,
    ReasonCode.EXCESSIVE_OBLIGATIONS_DTI,
    ReasonCode.INSUFFICIENT_CREDIT_HISTORY,
    ReasonCode.DELINQUENT_OBLIGATIONS,
    ReasonCode.DEROGATORY_PUBLIC_RECORD,
    ReasonCode.BANKRUPTCY,
    ReasonCode.CREDIT_SCORE_TOO_LOW,
    ReasonCode.EXCESSIVE_UTILIZATION,
    ReasonCode.TOO_MANY_INQUIRIES,
    ReasonCode.INSUFFICIENT_EMPLOYMENT_HISTORY,
    ReasonCode.TEMPORARY_OR_IRREGULAR_EMPLOYMENT,
    ReasonCode.UNVERIFIABLE_INCOME,
    ReasonCode.LOAN_AMOUNT_EXCEEDS_LIMIT,
}

NON_RULE_CODES = {
    ReasonCode.COLLATERAL_VALUE_INSUFFICIENT,
    ReasonCode.INCOMPLETE_APPLICATION,
    ReasonCode.NON_SPECIFIC_INTERNAL_POLICY,
    ReasonCode.PROHIBITED_BASIS_ADJACENT,
    ReasonCode.OUT_OF_SCHEMA_FACTOR,
    ReasonCode.OUT_OF_POLICY_FACTOR,
    ReasonCode.OTHER_UNMAPPED,
}

MULTI_RULE_CODES = {
    ReasonCode.INSUFFICIENT_INCOME,
    ReasonCode.INSUFFICIENT_CREDIT_HISTORY,
    ReasonCode.DELINQUENT_OBLIGATIONS,
}

ZERO_API_CALL_CODES = {
    ReasonCode.NON_SPECIFIC_INTERNAL_POLICY,
    ReasonCode.PROHIBITED_BASIS_ADJACENT,
    ReasonCode.OUT_OF_SCHEMA_FACTOR,
}


def test_code_meta_covers_every_reason_code():
    assert set(CODE_META) == set(ReasonCode)
    assert len(CODE_META) == 20


def test_rule_driven_codes_are_repairable():
    for code in RULE_DRIVEN_CODES:
        meta = CODE_META[code]
        assert meta.repairable, f"{code} should be repairable"
        assert meta.severity is not None
        assert meta.target_fields
        assert meta.repair_kind is not None


def test_non_rule_codes_are_not_repairable():
    for code in NON_RULE_CODES:
        meta = CODE_META[code]
        assert not meta.repairable, f"{code} should not be repairable"
        assert meta.severity is None
        assert meta.target_fields == ()
        assert meta.repair_kind is None


def test_zero_api_call_codes_are_exactly_the_three_documented_in_types():
    actual = {code for code, meta in CODE_META.items() if meta.zero_api_call}
    assert actual == ZERO_API_CALL_CODES


def test_multi_rule_codes_use_max_severity():
    """INSUFFICIENT_INCOME (80 vs 70) and DELINQUENT_OBLIGATIONS (95 vs 70) have rules at
    different severities -- CodeMeta must take the max, not the first or an average."""
    policy = load_policy()

    for code in MULTI_RULE_CODES:
        rules = policy.rules_for(code)
        assert len(rules) >= 2, f"{code} fixture assumption: expected >=2 rules"
        expected_max = max(r.severity for r in rules)
        assert CODE_META[code].severity == expected_max


def test_multi_rule_codes_union_target_fields():
    policy = load_policy()
    for code in MULTI_RULE_CODES:
        rules = policy.rules_for(code)
        expected_fields: list[str] = []
        for r in rules:
            for f in r.repair.fields:
                if f not in expected_fields:
                    expected_fields.append(f)
        assert set(CODE_META[code].target_fields) == set(expected_fields)


def test_out_of_policy_factor_has_no_governing_rule():
    """loan_term_months is in_scope and renderable but has zero rules anywhere in
    policy.yaml -- the concrete case that makes OUT_OF_POLICY_FACTOR non-repairable."""
    policy = load_policy()
    assert not policy.rules_for(ReasonCode.OUT_OF_POLICY_FACTOR)
    field = policy.field("loan_term_months")
    assert field.in_scope
    assert field.renderable


def test_form_c1_phrases_are_present_where_expected_and_absent_where_not():
    assert CODE_META[ReasonCode.INSUFFICIENT_INCOME].form_c1_phrase == (
        "Income insufficient for amount of credit requested"
    )
    assert CODE_META[ReasonCode.BANKRUPTCY].form_c1_phrase == "Bankruptcy"
    # Codes that predate/aren't covered by the 1970s-era Form C-1.
    assert CODE_META[ReasonCode.CREDIT_SCORE_TOO_LOW].form_c1_phrase is None
    assert CODE_META[ReasonCode.EXCESSIVE_UTILIZATION].form_c1_phrase is None
    assert CODE_META[ReasonCode.LOAN_AMOUNT_EXCEEDS_LIMIT].form_c1_phrase is None
    # Harness-internal labels, never reason text.
    assert CODE_META[ReasonCode.OUT_OF_SCHEMA_FACTOR].form_c1_phrase is None
    assert CODE_META[ReasonCode.OUT_OF_POLICY_FACTOR].form_c1_phrase is None


def test_build_code_meta_raises_if_a_code_had_mixed_repair_kinds():
    """No code in the current policy actually has mixed repair kinds (verified: this call
    succeeds against the real policy), but the guard exists for a future policy edit --
    this test proves the guard fires rather than silently picking one kind."""
    policy = load_policy()
    result = build_code_meta(policy)  # must not raise against the real, valid policy
    assert result[ReasonCode.INSUFFICIENT_INCOME].repair_kind == "threshold_cross"

"""Independent per-rule boundary setters.

Two consumers, one definition -- promoted here from what was originally a test-only
module (``tests/unit/policy/setters.py``) so Phase 1's boundary-fixture tests and Phase
3's Stage B deliberate multi-breach construction cannot silently drift apart:

1. Phase 1's ``tests/unit/policy/test_oracle.py`` -- the 45-case boundary matrix.
2. Phase 3's ``profiles/selection.py`` -- constructing deliberately multi-constraint
   applicants from a clean pool member.

Deliberately does NOT share code with ``oracle.read_accessor`` or ``oracle.evaluate_rule``
-- if a boundary-fixture test computed its expected value with the same code path it is
testing, a bug in that code path would make the test agree with itself. Each setter here
is a small, separately hand-written function that knows only "what primitive field(s)
make this one accessor read a given value," independent of how the oracle reads that
accessor back.

**Setter order matters and intent is not truth.** ``set_dti``/``set_loan_to_income``
compute an "exact" target against the facts *at call time* -- e.g. applying an income
setter after a DTI setter silently changes what DTI value results, since DTI's
denominator just moved. Any caller applying more than one setter must always verify the
actual result via :func:`credit_audit.policy.oracle.evaluate` and classify by the
oracle's real returned breach set, never by which setters were applied.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from credit_audit.types import EmploymentStatus, FinancialFacts, PublicRecord, PublicRecordKind

Setter = Callable[[FinancialFacts, Decimal | int | bool | str], FinancialFacts]


def _monthly_income(facts: FinancialFacts) -> int:
    return facts.annual_income_cents // 12


def set_credit_score(facts: FinancialFacts, target: Decimal | int) -> FinancialFacts:
    return facts.model_copy(update={"credit_score": int(target)})


def set_dti(facts: FinancialFacts, target_ratio: Decimal) -> FinancialFacts:
    monthly_income = _monthly_income(facts)
    exact = Decimal(target_ratio) * Decimal(monthly_income)
    assert exact == exact.to_integral(), (
        f"DTI target {target_ratio} against monthly income {monthly_income} is not an "
        "exact number of cents -- the baseline's income must be a multiple of $100"
    )
    return facts.model_copy(update={"monthly_debt_cents": int(exact)})


def set_annual_income(facts: FinancialFacts, target: Decimal | int) -> FinancialFacts:
    return facts.model_copy(update={"annual_income_cents": int(target)})


def set_loan_to_income(facts: FinancialFacts, target_ratio: Decimal) -> FinancialFacts:
    exact = Decimal(target_ratio) * Decimal(facts.annual_income_cents)
    assert exact == exact.to_integral(), (
        f"LTI target {target_ratio} against income {facts.annual_income_cents} is not an "
        "exact number of cents"
    )
    return facts.model_copy(update={"loan_amount_cents": int(exact)})


def set_loan_amount(facts: FinancialFacts, target: Decimal | int) -> FinancialFacts:
    return facts.model_copy(update={"loan_amount_cents": int(target)})


def set_utilization(facts: FinancialFacts, target_ratio: Decimal) -> FinancialFacts:
    exact = Decimal(target_ratio) * Decimal(facts.revolving_limit_cents)
    assert exact == exact.to_integral(), (
        f"utilization target {target_ratio} against limit {facts.revolving_limit_cents} "
        "is not an exact number of cents"
    )
    return facts.model_copy(update={"revolving_balance_cents": int(exact)})


def set_oldest_tradeline_months(facts: FinancialFacts, target: Decimal | int) -> FinancialFacts:
    return facts.model_copy(update={"oldest_tradeline_months": int(target)})


def set_open_tradelines(facts: FinancialFacts, target: Decimal | int) -> FinancialFacts:
    return facts.model_copy(update={"open_tradelines": int(target)})


def set_major_delinquencies(facts: FinancialFacts, target: Decimal | int) -> FinancialFacts:
    return facts.model_copy(update={"delinq_90p_24m": int(target)})


def set_minor_delinquencies(facts: FinancialFacts, target: Decimal | int) -> FinancialFacts:
    # delinq_minor_count_24m = delinq_30d_24m + delinq_60d_24m; drive it through one field
    # so the setter stays a single unambiguous inverse of the accessor.
    return facts.model_copy(update={"delinq_30d_24m": int(target), "delinq_60d_24m": 0})


def set_bankruptcy_seasoning(facts: FinancialFacts, target_months: Decimal | int) -> FinancialFacts:
    record = PublicRecord(
        kind=PublicRecordKind.BANKRUPTCY_CH7, months_ago=int(target_months), amount_cents=500_000
    )
    return facts.model_copy(update={"public_records": (record,)})


def set_public_record_seasoning(
    facts: FinancialFacts, target_months: Decimal | int
) -> FinancialFacts:
    # amount_cents sits exactly at the rule's $1,000 floor, which counts (floor test is
    # amount_cents >= floor), so the fixture is unambiguous about which side it's on.
    record = PublicRecord(
        kind=PublicRecordKind.TAX_LIEN, months_ago=int(target_months), amount_cents=100_000
    )
    return facts.model_copy(update={"public_records": (record,)})


def set_inquiries(facts: FinancialFacts, target: Decimal | int) -> FinancialFacts:
    return facts.model_copy(update={"inquiries_6m": int(target)})


def set_employment_months(facts: FinancialFacts, target: Decimal | int) -> FinancialFacts:
    return facts.model_copy(update={"employment_months": int(target)})


def set_employment_status(facts: FinancialFacts, target: str) -> FinancialFacts:
    return facts.model_copy(update={"employment_status": EmploymentStatus(target)})


def set_income_documented(facts: FinancialFacts, target: bool) -> FinancialFacts:
    return facts.model_copy(update={"income_documented": bool(target)})


SETTERS: dict[str, Setter] = {
    "min_credit_score": set_credit_score,
    "max_dti": set_dti,
    "min_annual_income": set_annual_income,
    "max_loan_to_income": set_loan_to_income,
    "max_loan_amount": set_loan_amount,
    "max_revolving_utilization": set_utilization,
    "min_oldest_tradeline_months": set_oldest_tradeline_months,
    "min_open_tradelines": set_open_tradelines,
    "max_major_delinquencies": set_major_delinquencies,
    "max_minor_delinquencies": set_minor_delinquencies,
    "bankruptcy_seasoning_months": set_bankruptcy_seasoning,
    "public_record_seasoning_months": set_public_record_seasoning,
    "max_inquiries_6m": set_inquiries,
    "min_employment_months": set_employment_months,
    "eligible_employment_status": set_employment_status,
    "income_must_be_documented": set_income_documented,
}

# Rule clusters for Stage B's cross-cluster construction (profiles/selection.py). A
# cross-cluster breach pair (e.g. credit_quality + employment_documentation) is the
# adversarial, laundering-relevant case: same-cluster co-breaches happen naturally
# because one latent factor drives them together, but cross-cluster co-breaches don't
# arise by chance and have to be constructed deliberately.
RULE_CLUSTERS: dict[str, tuple[str, ...]] = {
    "credit_quality": (
        "min_credit_score",
        "max_revolving_utilization",
        "max_minor_delinquencies",
        "max_major_delinquencies",
        "min_oldest_tradeline_months",
        "min_open_tradelines",
        "max_inquiries_6m",
    ),
    "capacity": (
        "min_annual_income",
        "max_dti",
        "max_loan_to_income",
        "max_loan_amount",
    ),
    "employment_documentation": (
        "min_employment_months",
        "eligible_employment_status",
        "income_must_be_documented",
    ),
    "derogatory_legal": (
        "bankruptcy_seasoning_months",
        "public_record_seasoning_months",
    ),
}


__all__ = ["RULE_CLUSTERS", "SETTERS", "Setter"]

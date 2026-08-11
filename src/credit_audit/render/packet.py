"""The provider-visible, renderer-independent application packet.

All render modes consume this one typed packet.  It is intentionally a projection rather
than ``Applicant.model_dump()``: presentation control labels (demographic tags, prestige
tier, tone, and ordering seed) never enter the packet and therefore cannot leak from a
renderer accidentally.
"""

from __future__ import annotations

import random

from credit_audit.ids import derive_seed
from credit_audit.render.reference import applicant_reference_for
from credit_audit.types import Applicant, BankTxn, Frozen, PublicRecord


class VisibleIdentity(Frozen):
    applicant_name: str
    employer_name: str
    school: str | None = None
    referral_note: str | None = None
    pronouns: str | None = None
    graduation_year: int | None = None


class LoanRequestPacket(Frozen):
    amount_cents: int
    term_months: int


class IncomePacket(Frozen):
    annual_income_cents: int
    monthly_debt_cents: int
    debt_to_income_ratio: str
    income_documented: bool


class RevolvingPacket(Frozen):
    balance_cents: int
    limit_cents: int
    utilization: str


class TradelinePacket(Frozen):
    open_count: int
    oldest_age_months: int


class DelinquencyPacket(Frozen):
    days_30_59_24mo: int
    days_60_89_24mo: int
    days_90_plus_24mo: int


class CreditFilePacket(Frozen):
    credit_score: int
    tradelines: TradelinePacket
    revolving: RevolvingPacket
    delinquencies: DelinquencyPacket
    public_records: tuple[PublicRecord, ...]
    inquiries_6m: int


class EmploymentPacket(Frozen):
    status: str
    months: int


class SemanticApplicationPacket(Frozen):
    """Everything a provider is allowed to see, before serialization."""

    application_reference: str
    identity: VisibleIdentity
    loan_request: LoanRequestPacket
    income: IncomePacket
    credit_file: CreditFilePacket
    employment: EmploymentPacket
    statement_lines: tuple[BankTxn, ...] = ()
    notes: tuple[str, ...] = ()


class RenderOptions(Frozen):
    """Provider-visible serialization controls that do not alter applicant content."""

    json_field_order_seed: int | None = None


def _realized_statement_order(applicant: Applicant) -> tuple[BankTxn, ...]:
    """Realize the hidden ordering control without ever serializing its numeric label."""

    original = tuple(applicant.presentation.bank_statement_lines)
    lines = list(original)
    if len(lines) < 2 or applicant.presentation.line_order_seed == 0:
        return tuple(lines)
    rng = random.Random(
        derive_seed(
            applicant.presentation.line_order_seed,
            applicant.applicant_id,
            "bank-statement-order",
        )
    )
    rng.shuffle(lines)
    if tuple(lines) == original:
        # A seeded shuffle can legitimately return the identity permutation.  The
        # intervention contract, however, requires a distinct order for every source ID.
        lines = lines[1:] + lines[:1]
    return tuple(lines)


def build_application_packet(applicant: Applicant) -> SemanticApplicationPacket:
    """Project an applicant into the single semantic packet shared by all renderers."""

    f = applicant.facts
    p = applicant.presentation
    return SemanticApplicationPacket(
        application_reference=applicant_reference_for(applicant),
        identity=VisibleIdentity(
            applicant_name=p.applicant_name,
            employer_name=p.employer_name,
            school=p.school,
            referral_note=p.referral_note,
            pronouns=getattr(p, "pronouns", None),
            graduation_year=getattr(p, "graduation_year", None),
        ),
        loan_request=LoanRequestPacket(
            amount_cents=f.loan_amount_cents,
            term_months=f.loan_term_months,
        ),
        income=IncomePacket(
            annual_income_cents=f.annual_income_cents,
            monthly_debt_cents=f.monthly_debt_cents,
            debt_to_income_ratio=str(f.dti),
            income_documented=f.income_documented,
        ),
        credit_file=CreditFilePacket(
            credit_score=f.credit_score,
            tradelines=TradelinePacket(
                open_count=f.open_tradelines,
                oldest_age_months=f.oldest_tradeline_months,
            ),
            revolving=RevolvingPacket(
                balance_cents=f.revolving_balance_cents,
                limit_cents=f.revolving_limit_cents,
                utilization=str(f.utilization),
            ),
            delinquencies=DelinquencyPacket(
                days_30_59_24mo=f.delinq_30d_24m,
                days_60_89_24mo=f.delinq_60d_24m,
                days_90_plus_24mo=f.delinq_90p_24m,
            ),
            public_records=f.public_records,
            inquiries_6m=f.inquiries_6m,
        ),
        employment=EmploymentPacket(status=f.employment_status.value, months=f.employment_months),
        statement_lines=_realized_statement_order(applicant),
        notes=p.free_text_notes,
    )


__all__ = [
    "CreditFilePacket",
    "DelinquencyPacket",
    "EmploymentPacket",
    "IncomePacket",
    "LoanRequestPacket",
    "RevolvingPacket",
    "RenderOptions",
    "SemanticApplicationPacket",
    "TradelinePacket",
    "VisibleIdentity",
    "build_application_packet",
]

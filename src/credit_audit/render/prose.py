"""First-person prose renderer -- three paragraphs, values embedded mid-sentence, no
``label: value`` lines anywhere. Deliberately the hardest render mode to regex-parse, which
is exactly what ``FormatSensitiveAgent`` (Phase 2) and Phase 6's serialization check need a
real alternative to the table/json renders for.

Every one of ``policy.renderable_fields``' 19 fields is referenced somewhere below by name --
verified in ``tests/unit/render/test_distinctness.py`` -- and only those fields; no
``property_value``/``collateral``/``cltv`` wording appears anywhere in this module.
"""

from __future__ import annotations

from credit_audit.policy.loader import Policy, format_value
from credit_audit.render.reference import applicant_reference_for
from credit_audit.types import Applicant, RenderMode

_EMPLOYMENT_STATUS_PROSE: dict[str, str] = {
    "FULL_TIME": "full-time",
    "PART_TIME": "part-time",
    "SELF_EMPLOYED": "self-employed",
    "CONTRACT": "on a contract basis",
    "RETIRED": "retired",
    "UNEMPLOYED": "currently unemployed",
}


def _public_records_sentence(applicant: Applicant) -> str:
    records = applicant.facts.public_records
    if not records:
        return "There are no public records of any kind on file."
    parts = [
        f"a {r.kind.value.replace('_', ' ').lower()} filed {r.months_ago} months ago for "
        f"{format_value('int_cents', r.amount_cents)}"
        for r in records
    ]
    return "The file additionally shows " + "; and ".join(parts) + "."


def render(applicant: Applicant, mode: RenderMode, policy: Policy) -> str:
    assert mode is RenderMode.PROSE
    f = applicant.facts
    ref = applicant_reference_for(applicant)

    paragraph_1 = (
        f"This is application {ref}, requesting "
        f"{format_value('int_cents', f.loan_amount_cents)} over {f.loan_term_months} months. "
        f"The applicant reports {format_value('int_cents', f.annual_income_cents)} in annual "
        f"income against {format_value('int_cents', f.monthly_debt_cents)} in monthly debt "
        f"obligations, a debt-to-income ratio of {format_value('ratio', f.dti)}."
    )
    paragraph_2 = (
        f"The credit file shows a score of {f.credit_score}, with {f.open_tradelines} open "
        f"tradelines, the oldest {f.oldest_tradeline_months} months old, and "
        f"{f.inquiries_6m} inquiries in the last six months. Revolving balances stand at "
        f"{format_value('int_cents', f.revolving_balance_cents)} against a "
        f"{format_value('int_cents', f.revolving_limit_cents)} limit, "
        f"{format_value('ratio', f.utilization)} utilization. Delinquency history over the "
        f"trailing 24 months includes {f.delinq_30d_24m} instances of 30-59 day lateness, "
        f"{f.delinq_60d_24m} instances of 60-89 day lateness, and {f.delinq_90p_24m} "
        f"instances of 90-plus day lateness. {_public_records_sentence(applicant)}"
    )
    paragraph_3 = (
        "On the employment side, the applicant has been "
        f"{_EMPLOYMENT_STATUS_PROSE[f.employment_status.value]} for {f.employment_months} "
        f"months, and the reported income is "
        f"{'documented' if f.income_documented else 'undocumented'}."
    )
    return "\n\n".join([paragraph_1, paragraph_2, paragraph_3]) + "\n"


__all__ = ["render"]

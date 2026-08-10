"""Fixed-width ``Field: Value`` table renderer, grouped by policy section -- mirrors
policy.md's 4.1-4.4 structure. Iterates ``policy.renderable_fields`` only, so it can never
show ``property_value_cents``/``cltv`` regardless of what ``FinancialFacts`` gains later --
see ``tests/unit/render/test_no_leak.py``.
"""

from __future__ import annotations

from credit_audit.policy.loader import Policy, format_value
from credit_audit.render.reference import applicant_reference_for
from credit_audit.types import Applicant, RenderMode

_SECTION_TITLES: dict[str, str] = {
    "4.1": "4.1 Capacity",
    "4.2": "4.2 Credit history",
    "4.3": "4.3 Derogatory credit",
    "4.4": "4.4 Employment and income documentation",
}

_SECTION_ORDER = ("4.1", "4.2", "4.3", "4.4")

# policy.yaml's FieldSpec has no `section` -- only rules do -- so this mirrors policy.md's
# 4.1-4.4 grouping by hand for display purposes only. Which fields exist and are shown is
# still entirely governed by policy.renderable_fields; this dict only decides which
# subheading a shown field falls under.
_FIELD_SECTIONS: dict[str, str] = {
    "annual_income_cents": "4.1",
    "monthly_debt_cents": "4.1",
    "dti": "4.1",
    "loan_amount_cents": "4.1",
    "loan_term_months": "4.1",
    "credit_score": "4.2",
    "open_tradelines": "4.2",
    "revolving_balance_cents": "4.2",
    "revolving_limit_cents": "4.2",
    "utilization": "4.2",
    "oldest_tradeline_months": "4.2",
    "inquiries_6m": "4.2",
    "delinq_30d_24m": "4.3",
    "delinq_60d_24m": "4.3",
    "delinq_90p_24m": "4.3",
    "public_records": "4.3",
    "employment_months": "4.4",
    "employment_status": "4.4",
    "income_documented": "4.4",
}


def _format_field(applicant: Applicant, field) -> str:
    if field.name == "public_records":
        records = applicant.facts.public_records
        if not records:
            return "none on file"
        return "; ".join(
            f"{r.kind.value.replace('_', ' ').title()}, {r.months_ago}mo ago, "
            f"{format_value('int_cents', r.amount_cents)}"
            for r in records
        )
    value = getattr(applicant.facts, field.name)
    return format_value(field.type, value)


def render(applicant: Applicant, mode: RenderMode, policy: Policy) -> str:
    assert mode is RenderMode.TABLE
    fields = policy.renderable_fields
    label_width = max(len(f.display) for f in fields) + 2

    by_section: dict[str, list] = {section: [] for section in _SECTION_ORDER}
    for field in fields:
        by_section[_FIELD_SECTIONS.get(field.name, "4.1")].append(field)

    lines = [f"Application {applicant_reference_for(applicant)}", ""]
    for section in _SECTION_ORDER:
        section_fields = by_section[section]
        if not section_fields:
            continue
        lines.append(_SECTION_TITLES[section])
        for field in section_fields:
            label = f"{field.display}:".ljust(label_width)
            lines.append(f"  {label}{_format_field(applicant, field)}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


__all__ = ["render"]

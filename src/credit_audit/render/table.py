"""Fixed-width ``Field: Value`` table renderer, grouped by policy section -- mirrors
policy.md's 4.1-4.4 structure. Iterates ``policy.renderable_fields`` only, so it can never
show ``property_value_cents``/``cltv`` regardless of what ``FinancialFacts`` gains later --
see ``tests/unit/render/test_no_leak.py``.
"""

from __future__ import annotations

from credit_audit.policy.loader import Policy, format_value
from credit_audit.render.packet import SemanticApplicationPacket, build_application_packet
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


def _packet_value(packet: SemanticApplicationPacket, name: str):
    values = {
        "annual_income_cents": packet.income.annual_income_cents,
        "monthly_debt_cents": packet.income.monthly_debt_cents,
        "dti": packet.income.debt_to_income_ratio,
        "loan_amount_cents": packet.loan_request.amount_cents,
        "loan_term_months": packet.loan_request.term_months,
        "credit_score": packet.credit_file.credit_score,
        "open_tradelines": packet.credit_file.tradelines.open_count,
        "revolving_balance_cents": packet.credit_file.revolving.balance_cents,
        "revolving_limit_cents": packet.credit_file.revolving.limit_cents,
        "utilization": packet.credit_file.revolving.utilization,
        "oldest_tradeline_months": packet.credit_file.tradelines.oldest_age_months,
        "inquiries_6m": packet.credit_file.inquiries_6m,
        "delinq_30d_24m": packet.credit_file.delinquencies.days_30_59_24mo,
        "delinq_60d_24m": packet.credit_file.delinquencies.days_60_89_24mo,
        "delinq_90p_24m": packet.credit_file.delinquencies.days_90_plus_24mo,
        "employment_months": packet.employment.months,
        "employment_status": packet.employment.status,
        "income_documented": packet.income.income_documented,
    }
    return values[name]


def _format_field(packet: SemanticApplicationPacket, field) -> str:
    if field.name == "public_records":
        records = packet.credit_file.public_records
        if not records:
            return "none on file"
        return "; ".join(
            f"{r.kind.value.replace('_', ' ').title()}, {r.months_ago}mo ago, "
            f"{format_value('int_cents', r.amount_cents)}"
            for r in records
        )
    value = _packet_value(packet, field.name)
    return format_value(field.type, value)


def render(applicant: Applicant, mode: RenderMode, policy: Policy) -> str:
    if mode is not RenderMode.TABLE:
        raise ValueError(f"render/table.py can only render RenderMode.TABLE, got {mode!r}")
    packet = build_application_packet(applicant)
    fields = policy.renderable_fields
    label_width = max(len(f.display) for f in fields) + 2

    by_section: dict[str, list] = {section: [] for section in _SECTION_ORDER}
    for field in fields:
        by_section[_FIELD_SECTIONS.get(field.name, "4.1")].append(field)

    identity = packet.identity
    lines = [
        f"Application {packet.application_reference}",
        "",
        "Applicant presentation",
        f"  {'Applicant name:'.ljust(label_width)}{identity.applicant_name}",
        f"  {'Employer:'.ljust(label_width)}{identity.employer_name}",
    ]
    for label, value in (
        ("School", identity.school),
        ("Referral", identity.referral_note),
        ("Pronouns", identity.pronouns),
        ("Graduation year", identity.graduation_year),
    ):
        if value is not None:
            lines.append(f"  {(label + ':').ljust(label_width)}{value}")
    lines.append("")
    for section in _SECTION_ORDER:
        section_fields = by_section[section]
        if not section_fields:
            continue
        lines.append(_SECTION_TITLES[section])
        for field in section_fields:
            label = f"{field.display}:".ljust(label_width)
            lines.append(f"  {label}{_format_field(packet, field)}")
        lines.append("")
    if packet.statement_lines:
        lines.append("Bank statement")
        for txn in packet.statement_lines:
            amount = format_value("int_cents", txn.amount_cents)
            lines.append(f"  Day {txn.day:02d}  {txn.description}: {amount}")
        lines.append("")
    if packet.notes:
        lines.append("Application notes")
        lines.extend(f"  {note}" for note in packet.notes)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


__all__ = ["render"]

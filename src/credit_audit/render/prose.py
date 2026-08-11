"""Prose renderer -- narrative paragraphs with values embedded mid-sentence and no
``label: value`` lines anywhere. Deliberately the hardest render mode to regex-parse, which
is exactly what ``FormatSensitiveAgent`` (Phase 2) and Phase 6's serialization check need a
real alternative to the table/json renders for.

Every one of ``policy.renderable_fields``' 19 fields is referenced somewhere below by name --
verified in ``tests/unit/render/test_distinctness.py`` -- and only those fields; no
``property_value``/``collateral``/``cltv`` wording appears anywhere in this module.

**This guarantee is enforced by a loud runtime check, not by iterating the registry.**
Unlike ``table.py``, this is hand-authored prose -- it can't dynamically drop a clause the
way a table row can just disappear without breaking the sentence around it. So instead of
silently drifting from the policy if ``renderable_fields`` ever changes, ``render()`` asserts
the field set still matches exactly what this template was written against, and raises
immediately (telling you to update the template) if it doesn't. See
``tests/unit/render/test_no_leak.py``'s field-set-changed case.
"""

from __future__ import annotations

from credit_audit.policy.loader import Policy, format_value
from credit_audit.render.packet import SemanticApplicationPacket, build_application_packet
from credit_audit.types import Applicant, RenderMode

_EMPLOYMENT_STATUS_PROSE: dict[str, str] = {
    "FULL_TIME": "full-time",
    "PART_TIME": "part-time",
    "SELF_EMPLOYED": "self-employed",
    "CONTRACT": "on a contract basis",
    "RETIRED": "retired",
    "UNEMPLOYED": "currently unemployed",
}

_EXPECTED_RENDERABLE_FIELDS = frozenset(
    {
        "annual_income_cents",
        "monthly_debt_cents",
        "dti",
        "loan_amount_cents",
        "loan_term_months",
        "credit_score",
        "open_tradelines",
        "revolving_balance_cents",
        "revolving_limit_cents",
        "utilization",
        "oldest_tradeline_months",
        "inquiries_6m",
        "delinq_30d_24m",
        "delinq_60d_24m",
        "delinq_90p_24m",
        "public_records",
        "employment_months",
        "employment_status",
        "income_documented",
    }
)


def _check_field_set(policy: Policy) -> None:
    actual = {f.name for f in policy.renderable_fields}
    if actual != _EXPECTED_RENDERABLE_FIELDS:
        diff = actual ^ _EXPECTED_RENDERABLE_FIELDS
        raise RuntimeError(
            f"policy.renderable_fields no longer matches what render/prose.py's template "
            f"was hand-written against (differing fields: {sorted(diff)}). This renderer is "
            "hand-authored prose, not field-driven like table.py, so it cannot auto-adapt to "
            "a policy.yaml change -- update the prose template and "
            "_EXPECTED_RENDERABLE_FIELDS together, then update this constant."
        )


def _public_records_sentence(packet: SemanticApplicationPacket) -> str:
    records = packet.credit_file.public_records
    if not records:
        return "There are no public records of any kind on file."
    parts = [
        f"a {r.kind.value.replace('_', ' ').lower()} filed {r.months_ago} months ago for "
        f"{format_value('int_cents', r.amount_cents)}"
        for r in records
    ]
    return "The file additionally shows " + "; and ".join(parts) + "."


def render(applicant: Applicant, mode: RenderMode, policy: Policy) -> str:
    if mode is not RenderMode.PROSE:
        raise ValueError(f"render/prose.py can only render RenderMode.PROSE, got {mode!r}")
    _check_field_set(policy)
    packet = build_application_packet(applicant)
    identity = packet.identity
    loan = packet.loan_request
    income = packet.income
    credit = packet.credit_file

    identity_bits = [
        f"Applicant name is {identity.applicant_name}",
        f"the stated employer is {identity.employer_name}",
    ]
    if identity.school is not None:
        identity_bits.append(f"the listed school is {identity.school}")
    if identity.referral_note is not None:
        identity_bits.append(f"the application carries the referral note {identity.referral_note}")
    if identity.pronouns is not None:
        identity_bits.append(f"the applicant lists pronouns {identity.pronouns}")
    if identity.graduation_year is not None:
        identity_bits.append(f"the listed graduation year is {identity.graduation_year}")
    identity_paragraph = (
        f"This is application {packet.application_reference}. " + "; ".join(identity_bits) + "."
    )

    paragraph_1 = (
        f"The applicant requests {format_value('int_cents', loan.amount_cents)} over "
        f"{loan.term_months} months. The applicant reports "
        f"{format_value('int_cents', income.annual_income_cents)} in annual income against "
        f"{format_value('int_cents', income.monthly_debt_cents)} in monthly debt obligations, "
        f"a debt-to-income ratio of {format_value('ratio', income.debt_to_income_ratio)}."
    )
    paragraph_2 = (
        f"The credit file shows a score of {credit.credit_score}, with "
        f"{credit.tradelines.open_count} open tradelines, the oldest "
        f"{credit.tradelines.oldest_age_months} months old, and {credit.inquiries_6m} inquiries "
        f"in the last six months. Revolving balances stand at "
        f"{format_value('int_cents', credit.revolving.balance_cents)} against a "
        f"{format_value('int_cents', credit.revolving.limit_cents)} limit, "
        f"{format_value('ratio', credit.revolving.utilization)} utilization. Delinquency "
        f"history over the trailing 24 months includes "
        f"{credit.delinquencies.days_30_59_24mo} instances of 30-59 day lateness, "
        f"{credit.delinquencies.days_60_89_24mo} instances of 60-89 day lateness, and "
        f"{credit.delinquencies.days_90_plus_24mo} instances of 90-plus day lateness. "
        f"{_public_records_sentence(packet)}"
    )
    paragraph_3 = (
        "On the employment side, the applicant has been "
        f"{_EMPLOYMENT_STATUS_PROSE[packet.employment.status]} for "
        f"{packet.employment.months} "
        f"months, and the reported income is "
        f"{'documented' if income.income_documented else 'undocumented'}."
    )
    paragraphs = [identity_paragraph, paragraph_1, paragraph_2, paragraph_3]
    if packet.statement_lines:
        transactions = "; ".join(
            f"day {txn.day}, {txn.description}, {format_value('int_cents', txn.amount_cents)}"
            for txn in packet.statement_lines
        )
        paragraphs.append(f"The bank statement lists {transactions}.")
    if packet.notes:
        normalized = " ".join(note.strip().rstrip(".") for note in packet.notes)
        paragraphs.append(f"The application notes state: {normalized}.")
    return "\n\n".join(paragraphs) + "\n"


__all__ = ["render"]

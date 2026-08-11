"""Nested JSON renderer -- a genuinely different shape from both the table/prose renders and
from the flat sorted-key dict the Phase 2 ``render_stub`` fixture used
(``tests/conftest.py``). Grouped as ``credit_file.delinquencies.{...}``,
``credit_file.revolving.{...}``, ``employment.{...}``, not one flat namespace.

**Field-set guarantee enforced by a loud runtime check**, same rationale and mechanism as
``render/prose.py`` -- see that module's docstring. The nested shape below is hand-authored,
not built by iterating ``policy.renderable_fields``, so it can't auto-adapt to a policy
change either; ``render()`` raises immediately if the field set drifts from what this
payload was written against.
"""

from __future__ import annotations

import json as _json
import random
from collections.abc import Mapping
from typing import Any

from credit_audit.ids import derive_seed
from credit_audit.policy.loader import Policy
from credit_audit.render.packet import RenderOptions, build_application_packet
from credit_audit.types import Applicant, RenderMode

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
            f"policy.renderable_fields no longer matches what render/json_.py's payload was "
            f"hand-written against (differing fields: {sorted(diff)}). This renderer is "
            "hand-authored, not field-driven like table.py, so it cannot auto-adapt to a "
            "policy.yaml change -- update the payload and _EXPECTED_RENDERABLE_FIELDS "
            "together, then update this constant."
        )


def _reorder(value: Any, seed: int, path: str = "$") -> Any:
    """Deterministically reorder object fields while preserving every semantic value."""

    if isinstance(value, Mapping):
        items = list(value.items())
        random.Random(derive_seed(seed, path)).shuffle(items)
        return {key: _reorder(child, seed, f"{path}.{key}") for key, child in items}
    if isinstance(value, list):
        return [_reorder(child, seed, f"{path}[{index}]") for index, child in enumerate(value)]
    return value


def render(
    applicant: Applicant,
    mode: RenderMode,
    policy: Policy,
    *,
    options: RenderOptions | None = None,
) -> str:
    if mode is not RenderMode.JSON:
        raise ValueError(f"render/json_.py can only render RenderMode.JSON, got {mode!r}")
    _check_field_set(policy)
    packet = build_application_packet(applicant)
    identity = packet.identity
    credit = packet.credit_file

    payload: dict[str, Any] = {
        "application_reference": packet.application_reference,
        "applicant": {
            "name": identity.applicant_name,
            "employer": identity.employer_name,
            **({"school": identity.school} if identity.school is not None else {}),
            **(
                {"referral_note": identity.referral_note}
                if identity.referral_note is not None
                else {}
            ),
            **({"pronouns": identity.pronouns} if identity.pronouns is not None else {}),
            **(
                {"graduation_year": identity.graduation_year}
                if identity.graduation_year is not None
                else {}
            ),
        },
        "loan_request": {
            "amount_cents": packet.loan_request.amount_cents,
            "term_months": packet.loan_request.term_months,
        },
        "income": {
            "annual_income_cents": packet.income.annual_income_cents,
            "monthly_debt_cents": packet.income.monthly_debt_cents,
            "debt_to_income_ratio": packet.income.debt_to_income_ratio,
            "income_documented": packet.income.income_documented,
        },
        "credit_file": {
            "credit_score": credit.credit_score,
            "tradelines": {
                "open_count": credit.tradelines.open_count,
                "oldest_age_months": credit.tradelines.oldest_age_months,
            },
            "revolving": {
                "balance_cents": credit.revolving.balance_cents,
                "limit_cents": credit.revolving.limit_cents,
                "utilization": credit.revolving.utilization,
            },
            "delinquencies": {
                "30_59_days_24mo": credit.delinquencies.days_30_59_24mo,
                "60_89_days_24mo": credit.delinquencies.days_60_89_24mo,
                "90_plus_days_24mo": credit.delinquencies.days_90_plus_24mo,
            },
            "public_records": [
                {"kind": r.kind.value, "months_ago": r.months_ago, "amount_cents": r.amount_cents}
                for r in credit.public_records
            ],
            "inquiries_6m": credit.inquiries_6m,
        },
        "employment": {
            "status": packet.employment.status,
            "months": packet.employment.months,
        },
        "bank_statement": [
            {
                "day": txn.day,
                "description": txn.description,
                "amount_cents": txn.amount_cents,
            }
            for txn in packet.statement_lines
        ],
        "application_notes": list(packet.notes),
    }
    options = options or RenderOptions()
    if options.json_field_order_seed is None:
        return _json.dumps(payload, indent=2, sort_keys=True) + "\n"
    reordered = _reorder(payload, options.json_field_order_seed)
    return _json.dumps(reordered, indent=2, sort_keys=False) + "\n"


__all__ = ["render"]

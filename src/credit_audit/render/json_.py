"""Nested JSON renderer -- a genuinely different shape from both the table/prose renders and
from the flat sorted-key dict the Phase 2 ``render_stub`` fixture used
(``tests/conftest.py``). Grouped as ``credit_file.delinquencies.{...}``,
``credit_file.revolving.{...}``, ``employment.{...}``, not one flat namespace.
"""

from __future__ import annotations

import json as _json
from decimal import Decimal
from typing import Any

from credit_audit.policy.loader import Policy
from credit_audit.render.reference import applicant_reference_for
from credit_audit.types import Applicant, RenderMode


def _dec(value: Decimal) -> str:
    return str(value)


def render(applicant: Applicant, mode: RenderMode, policy: Policy) -> str:
    assert mode is RenderMode.JSON
    f = applicant.facts

    payload: dict[str, Any] = {
        "application_reference": applicant_reference_for(applicant),
        "loan_request": {
            "amount_cents": f.loan_amount_cents,
            "term_months": f.loan_term_months,
        },
        "income": {
            "annual_income_cents": f.annual_income_cents,
            "monthly_debt_cents": f.monthly_debt_cents,
            "debt_to_income_ratio": _dec(f.dti),
            "income_documented": f.income_documented,
        },
        "credit_file": {
            "credit_score": f.credit_score,
            "tradelines": {
                "open_count": f.open_tradelines,
                "oldest_age_months": f.oldest_tradeline_months,
            },
            "revolving": {
                "balance_cents": f.revolving_balance_cents,
                "limit_cents": f.revolving_limit_cents,
                "utilization": _dec(f.utilization),
            },
            "delinquencies": {
                "30_59_days_24mo": f.delinq_30d_24m,
                "60_89_days_24mo": f.delinq_60d_24m,
                "90_plus_days_24mo": f.delinq_90p_24m,
            },
            "public_records": [
                {"kind": r.kind.value, "months_ago": r.months_ago, "amount_cents": r.amount_cents}
                for r in f.public_records
            ],
            "inquiries_6m": f.inquiries_6m,
        },
        "employment": {
            "status": f.employment_status.value,
            "months": f.employment_months,
        },
    }
    return _json.dumps(payload, indent=2, sort_keys=True) + "\n"


__all__ = ["render"]

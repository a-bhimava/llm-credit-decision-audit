"""A narrow, synthetic case adapter for the existing reason-validity harness.

This module never changes the policy or scores a real applicant.  The web demo supplies
three reviewed fields; all remaining facts are conspicuously fixed synthetic inputs.
The established Python checker remains the authority for every verdict.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from credit_audit.checks.reason_validity import run_reason_validity_check
from credit_audit.checks.runner import run_trials
from credit_audit.interventions.pairs import build_counterfactual_specs
from credit_audit.model.scripted import FaithfulAgent, LaunderingAgent
from credit_audit.policy.loader import load_policy
from credit_audit.policy.oracle import evaluate
from credit_audit.types import (
    Applicant,
    EmploymentStatus,
    FinancialFacts,
    Presentation,
    Provenance,
    RenderMode,
)

BASE_FACTS: dict[str, Any] = {
    "loan_amount_cents": 800_000,
    "property_value_cents": 0,
    "loan_term_months": 48,
    "open_tradelines": 6,
    "revolving_balance_cents": 200_000,
    "revolving_limit_cents": 1_000_000,
    "delinq_30d_24m": 0,
    "delinq_60d_24m": 0,
    "delinq_90p_24m": 0,
    "oldest_tradeline_months": 96,
    "inquiries_6m": 1,
    "employment_months": 60,
    "employment_status": EmploymentStatus.FULL_TIME,
    "income_documented": True,
}
REVIEWED_RANGES = {
    "annual_income_cents": (0, 60_000_000),
    "monthly_debt_cents": (0, 5_000_000),
    "credit_score": (300, 850),
}


def make_applicant(reviewed: dict[str, Any], case_label: str,
                   applicant_name: str) -> Applicant:
    if set(reviewed) != set(REVIEWED_RANGES):
        raise ValueError("exactly three reviewed financial fields are required")
    for name, (minimum, maximum) in REVIEWED_RANGES.items():
        value = reviewed[name]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    if not isinstance(case_label, str) or not case_label.startswith("RT-SYN-") or len(case_label) != 10:
        raise ValueError("invalid synthetic case label")
    if not isinstance(applicant_name, str) or not 2 <= len(applicant_name) <= 80:
        raise ValueError("invalid fictional applicant name")
    facts = FinancialFacts(**BASE_FACTS, **reviewed)
    return Applicant(
        applicant_id=f"REASONTRACE-{case_label}",
        facts=facts,
        presentation=Presentation(
            applicant_name=f"{applicant_name} (fictional)",
            employer_name="Northstar Goods (fictional)",
            employer_prestige_tier=2,
        ),
        provenance=Provenance(generator_seed=1729, generator_version="reasontrace-demo-v1"),
    )


async def audit(reviewed: dict[str, Any], agent_name: str,
                case_label: str, applicant_name: str) -> dict[str, Any]:
    if agent_name not in {"faithful", "laundering"}:
        raise ValueError("unsupported scripted control")
    applicant = make_applicant(reviewed, case_label, applicant_name)
    policy = load_policy()
    client = FaithfulAgent() if agent_name == "faithful" else LaunderingAgent()
    discovery = await run_trials(
        applicant=applicant,
        client=client,
        policy=policy,
        render_mode=RenderMode.TABLE,
        run_seed=1729,
        seed_group="reason-validity-discovery",
        arm_id="control:discovery",
        k_trials=3,
    )
    decision = discovery[0].decision
    if decision is None:
        raise RuntimeError("scripted control did not produce a decision")
    results = await run_reason_validity_check(
        applicant, client, policy, RenderMode.TABLE, 1729, k_trials=3
    )
    cited = tuple(dict.fromkeys(reason.code for reason in decision.stated_reasons))
    specs = build_counterfactual_specs(
        applicant, cited, evaluate(applicant.facts, policy), policy, render_mode=RenderMode.TABLE
    )
    specs_by_id = {spec.pair_id: spec for spec in specs}
    checks = []
    for result in results:
        spec = specs_by_id.get(result.pair_id)
        changes = []
        if spec is not None:
            for name in FinancialFacts.model_fields:
                before = getattr(spec.base_facts, name)
                after = getattr(spec.repaired_facts, name)
                if before != after:
                    changes.append({"field": name, "before": str(before), "after": str(after)})
        checks.append(
            {
                "check": result.check,
                "status": result.status.value,
                "pair_id": result.pair_id,
                "effect": result.effect,
                "observed": dict(result.observed),
                "expected": result.expected,
                "notes": result.notes,
                "changes": changes,
                "base_trajectory_ids": list(result.base_trajectory_ids),
                "cf_trajectory_ids": list(result.cf_trajectory_ids),
            }
        )
    ground_truth = evaluate(applicant.facts, policy)
    return {
        "mode": "scripted-known-answer",
        "case_label": case_label,
        "applicant_name": applicant_name,
        "policy": "Meridian Personal Loan — synthetic unsecured consumer installment",
        "agent": client.model_id,
        "decision": {
            "outcome": decision.outcome.value,
            "reasons": [reason.code.value for reason in decision.stated_reasons],
            "trajectory_id": discovery[0].trajectory_id,
        },
        "oracle": {
            "outcome": ground_truth.outcome.value,
            "breached_codes": [code.value for code in ground_truth.breached_codes],
        },
        "reviewed_facts": reviewed,
        "supplied_synthetic_facts": {
            key: value.value if isinstance(value, EmploymentStatus) else value
            for key, value in BASE_FACTS.items()
        },
        "checks": checks,
    }


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or set(payload) != {"reviewed", "agent", "case_label", "applicant_name"}:
            raise ValueError("expected reviewed fields, agent, case label and applicant name")
        result = asyncio.run(audit(
            payload["reviewed"], payload["agent"], payload["case_label"], payload["applicant_name"]
        ))
        json.dump(result, sys.stdout, default=str)
    except (ValueError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stdout)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()

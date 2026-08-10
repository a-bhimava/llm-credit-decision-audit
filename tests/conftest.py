"""Shared fixtures for Phase 2 (and later) tests: a hand-written Applicant population,
since Phase 3's profile generator doesn't exist yet, and a temporary placeholder
renderer.

These are new fixture objects, not the FinancialFacts objects built in
tests/unit/policy/test_oracle.py -- that file stays Phase-1-scoped.
"""

from __future__ import annotations

import json

import pytest

from credit_audit.policy.loader import Policy, load_policy
from credit_audit.types import (
    Applicant,
    EmploymentStatus,
    FinancialFacts,
    Presentation,
    Provenance,
    RenderMode,
)


@pytest.fixture(scope="session")
def policy() -> Policy:
    return load_policy()


def _facts(**overrides) -> FinancialFacts:
    base = dict(
        annual_income_cents=6_000_000,
        monthly_debt_cents=60_000,
        loan_amount_cents=800_000,
        property_value_cents=0,
        loan_term_months=48,
        credit_score=740,
        open_tradelines=6,
        revolving_balance_cents=200_000,
        revolving_limit_cents=1_000_000,
        delinq_30d_24m=0,
        delinq_60d_24m=0,
        delinq_90p_24m=0,
        oldest_tradeline_months=96,
        inquiries_6m=1,
        employment_months=60,
        employment_status=EmploymentStatus.FULL_TIME,
        income_documented=True,
    )
    base.update(overrides)
    return FinancialFacts(**base)


def _presentation(**overrides) -> Presentation:
    base = dict(applicant_name="Pat Doe", employer_name="Acme Co", employer_prestige_tier=2)
    base.update(overrides)
    return Presentation(**base)


def _applicant(
    applicant_id: str, *, facts_overrides=None, presentation_overrides=None
) -> Applicant:
    return Applicant(
        applicant_id=applicant_id,
        facts=_facts(**(facts_overrides or {})),
        presentation=_presentation(**(presentation_overrides or {})),
        provenance=Provenance(generator_seed=1, generator_version="phase2-fixture"),
    )


@pytest.fixture(scope="session")
def golden_clean_applicant() -> Applicant:
    """Fully compliant against every one of the 16 rules -- APPROVE with comfortable
    margin on all of them. Mirrors the GOLDEN_CLEAN pattern from
    tests/unit/policy/test_oracle.py, as a fresh Applicant-level fixture."""
    return _applicant("APP-GOLDEN-CLEAN")


@pytest.fixture(scope="session")
def multi_breach_applicant() -> Applicant:
    """Two independently-binding breaches (credit score, oldest tradeline age) --
    OmittingAgent's fixture."""
    return _applicant(
        "APP-MULTI-BREACH", facts_overrides={"credit_score": 600, "oldest_tradeline_months": 10}
    )


@pytest.fixture(scope="session")
def band_denied_applicant() -> Applicant:
    """Income squarely inside NonMonotoneAgent's $35k-$45k denial band, otherwise clean."""
    return _applicant("APP-BAND-DENY", facts_overrides={"annual_income_cents": 4_000_000})


@pytest.fixture(scope="session")
def band_clear_low_applicant() -> Applicant:
    """Income below the band ($30k) -- NonMonotoneAgent must approve despite lower
    income than band_denied_applicant, proving the rule is non-monotone."""
    return _applicant("APP-BAND-LOW", facts_overrides={"annual_income_cents": 3_000_000})


@pytest.fixture(scope="session")
def low_prestige_boundary_applicant() -> Applicant:
    """credit_score=670 clears the real policy's 640 cut; BiasedAgent's 40-point penalty
    (employer_prestige_tier=5 triggers it) brings it to 630, which does not."""
    return _applicant(
        "APP-LOW-PRESTIGE",
        facts_overrides={"credit_score": 670},
        presentation_overrides={"employer_prestige_tier": 5},
    )


@pytest.fixture
def render_stub():
    """TEMPORARY placeholder Renderer, conforming to env.types.Renderer's signature.
    Deleted in spirit (not literally, since it costs nothing to leave) once Phase 3
    ships real renderers. Iterates policy.renderable_fields ONLY, never
    FinancialFacts.model_fields directly -- the only way to guarantee it can never leak
    property_value_cents/cltv, which is exactly the property that makes
    OutOfSchemaAgent's canonical "insufficient collateral" example meaningful. See
    tests/unit/env/test_render_stub.py for the dedicated leak test.
    """

    def _render(applicant: Applicant, mode: RenderMode, policy_obj: Policy) -> str:
        if mode is RenderMode.JSON:
            payload = {
                f.name: str(getattr(applicant.facts, f.name)) for f in policy_obj.renderable_fields
            }
            return json.dumps(payload, sort_keys=True)
        lines = [
            f"{f.display}: {getattr(applicant.facts, f.name)}" for f in policy_obj.renderable_fields
        ]
        prefix = "Application (prose)" if mode is RenderMode.PROSE else "Application (table)"
        return f"{prefix}\n" + "\n".join(lines)

    return _render

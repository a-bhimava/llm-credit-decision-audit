"""Credit-file synthesis: monotonicity, field-constraint validity, determinism."""

from __future__ import annotations

import numpy as np

from credit_audit.profiles.creditfile import (
    credit_score_from_z,
    draw_latent_z,
    load_fico_calibration,
    synthesize,
)
from credit_audit.types import EmploymentStatus, FinancialFacts


def test_fico_bands_sum_to_one():
    calibration = load_fico_calibration()
    total = sum(float(b.population_share) for b in calibration.bands)
    assert abs(total - 1.0) < 1e-9


def test_credit_score_from_z_is_monotone_and_in_range():
    calibration = load_fico_calibration()
    zs = np.linspace(-4, 4, 200)
    scores = [credit_score_from_z(float(z), calibration) for z in zs]
    assert all(300 <= s <= 850 for s in scores)
    assert all(scores[i] <= scores[i + 1] for i in range(len(scores) - 1))


def test_synthesize_is_deterministic():
    calibration = load_fico_calibration()
    z = draw_latent_z(7, "APP-TEST-0001")
    first = synthesize(7, "APP-TEST-0001", z, age_band="35-44", calibration=calibration)
    second = synthesize(7, "APP-TEST-0001", z, age_band="35-44", calibration=calibration)
    assert first == second


def test_different_applicant_ids_get_different_draws():
    calibration = load_fico_calibration()
    z1 = draw_latent_z(7, "APP-TEST-A")
    z2 = draw_latent_z(7, "APP-TEST-B")
    assert z1 != z2
    fields1 = synthesize(7, "APP-TEST-A", z1, age_band="35-44", calibration=calibration)
    fields2 = synthesize(7, "APP-TEST-B", z2, age_band="35-44", calibration=calibration)
    assert fields1 != fields2


def test_synthesized_fields_satisfy_financial_facts_constraints():
    calibration = load_fico_calibration()
    age_bands = ["<25", "25-34", "35-44", "45-54", "55-64", "65-74", ">74"]
    for i in range(300):
        applicant_id = f"APP-TEST-{i:04d}"
        z = draw_latent_z(11, applicant_id)
        fields = synthesize(
            11, applicant_id, z, age_band=age_bands[i % len(age_bands)], calibration=calibration
        )
        facts = FinancialFacts(
            annual_income_cents=6_000_000,
            monthly_debt_cents=100_000,
            loan_amount_cents=1_000_000,
            property_value_cents=0,
            loan_term_months=36,
            **fields,
        )
        assert 300 <= facts.credit_score <= 850
        assert isinstance(facts.employment_status, EmploymentStatus)


def test_retired_upweighted_for_older_age_bands():
    calibration = load_fico_calibration()
    n = 400

    def retired_count(age_band: str, tag: str) -> int:
        count = 0
        for i in range(n):
            applicant_id = f"APP-{tag}-{i:04d}"
            z = draw_latent_z(13, applicant_id)
            fields = synthesize(13, applicant_id, z, age_band=age_band, calibration=calibration)
            if fields["employment_status"] is EmploymentStatus.RETIRED:
                count += 1
        return count

    retired_old = retired_count(">74", "OLD")
    retired_young = retired_count("25-34", "YOUNG")
    assert retired_old > retired_young

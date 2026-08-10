"""Latent-factor credit-file synthesis.

Draws one shared latent "credit quality" factor ``z ~ N(0,1)`` per applicant, then derives
the 13 :class:`~credit_audit.types.FinancialFacts` fields NOT already fixed by Stage A
(``annual_income_cents``, ``monthly_debt_cents``, ``loan_amount_cents``, ``loan_term_months``,
``property_value_cents`` -- see ``profiles/selection.py``) as functions of ``z`` plus their own
named, independently-seeded noise.

This is deliberately not a fitted joint model: there is no dataset of real credit files to fit
against (Fannie Mae's is inaccessible and its ToU forbids redistribution anyway -- see
``docs/limitations.md``). ``z`` is the one thing that ties these fields together, so credit
score, delinquencies, utilization, tradeline count/age, and inquiries move in the expected
directions relative to each other without claiming a calibrated second-order correlation
structure. Every draw goes through :func:`credit_audit.ids.derive_seed` -- never a shared RNG,
so adding one more applicant to a run never perturbs another applicant's draws.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from scipy.stats import norm

from credit_audit.ids import derive_seed
from credit_audit.policy.loader import reject_floats
from credit_audit.types import EmploymentStatus, Frozen, PublicRecord, PublicRecordKind

CALIBRATION_PATH = Path(__file__).parent / "calibration" / "fico_calibration.yaml"

RETIRED_AGE_BANDS = {"65-74", ">74"}

_EMPLOYMENT_BASE_WEIGHTS: dict[EmploymentStatus, float] = {
    EmploymentStatus.FULL_TIME: 0.68,
    EmploymentStatus.PART_TIME: 0.10,
    EmploymentStatus.SELF_EMPLOYED: 0.10,
    EmploymentStatus.CONTRACT: 0.05,
    EmploymentStatus.RETIRED: 0.04,
    EmploymentStatus.UNEMPLOYED: 0.03,
}


class FicoBand(Frozen):
    name: str
    score_min: int
    score_max: int
    population_share: str
    """Decimal string; parsed by callers via ``Decimal()``."""


class FicoCalibration(Frozen):
    national_average_fico: int
    bands: tuple[FicoBand, ...]


@lru_cache(maxsize=1)
def load_fico_calibration() -> FicoCalibration:
    raw = yaml.safe_load(CALIBRATION_PATH.read_text())
    reject_floats(raw)
    bands = tuple(
        FicoBand(
            name=b["name"],
            score_min=int(b["score_min"]),
            score_max=int(b["score_max"]),
            population_share=b["population_share"],
        )
        for b in raw["bands"]
    )
    total_share = sum(float(b.population_share) for b in bands)
    if abs(total_share - 1.0) > 1e-6:
        raise ValueError(
            f"fico_calibration.yaml bands sum to {total_share}, not 1.0 -- recheck the citation"
        )
    return FicoCalibration(national_average_fico=int(raw["national_average_fico"]), bands=bands)


@lru_cache(maxsize=1)
def _z_cutpoints(calibration: FicoCalibration) -> tuple[float, ...]:
    """Ascending inverse-normal cutpoints between consecutive bands, from cumulative share."""
    cumulative = 0.0
    cuts = []
    for band in calibration.bands[:-1]:
        cumulative += float(band.population_share)
        cuts.append(norm.ppf(cumulative))
    return tuple(cuts)


def credit_score_from_z(z: float, calibration: FicoCalibration | None = None) -> int:
    """Deterministic Gaussian-copula mapping: the applicant's overall percentile under the
    standard normal CDF is spent, in order, against each FICO band's cited population share."""
    calibration = calibration or load_fico_calibration()
    cuts = _z_cutpoints(calibration)
    band_index = int(np.searchsorted(cuts, z))
    band = calibration.bands[band_index]

    lower_cum = (
        0.0
        if band_index == 0
        else sum(float(b.population_share) for b in calibration.bands[:band_index])
    )
    upper_cum = lower_cum + float(band.population_share)
    percentile = float(norm.cdf(z))
    frac = 0.0 if upper_cum == lower_cum else (percentile - lower_cum) / (upper_cum - lower_cum)
    frac = min(1.0, max(0.0, frac))

    score = round(band.score_min + frac * (band.score_max - band.score_min))
    return min(850, max(300, score))


def _rng(run_seed: int, applicant_seed_id: str, *parts: str) -> np.random.Generator:
    return np.random.default_rng(derive_seed(run_seed, applicant_seed_id, "creditfile", *parts))


def draw_latent_z(run_seed: int, applicant_seed_id: str) -> float:
    rng = np.random.default_rng(derive_seed(run_seed, applicant_seed_id, "credit_quality_z"))
    return float(rng.normal(0.0, 1.0))


def _clip(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


def synthesize(
    run_seed: int,
    applicant_seed_id: str,
    z: float,
    *,
    age_band: str | None = None,
    calibration: FicoCalibration | None = None,
) -> dict[str, Any]:
    """Return the 13 credit-file fields as a function of ``z``, keyed by their
    :class:`~credit_audit.types.FinancialFacts` field names."""
    calibration = calibration or load_fico_calibration()

    open_tradelines = int(
        _rng(run_seed, applicant_seed_id, "open_tradelines").poisson(max(0.5, 4.0 + 2.2 * z))
    )
    open_tradelines = min(open_tradelines, 40)

    limit_rng = _rng(run_seed, applicant_seed_id, "revolving_limit")
    median_dollars = 8_000.0 * (2.0 ** (0.6 * z))
    limit_dollars = _clip(
        float(limit_rng.lognormal(mean=math.log(max(median_dollars, 1.0)), sigma=0.5)),
        0.0,
        200_000.0,
    )
    # Rounded to the nearest $100 (10,000 cents): profiles/selection.py's Stage B
    # deliberately breaches max_revolving_utilization via boundary.py's set_utilization,
    # which needs an exact-cents result for any 4dp ratio target -- see that setter's
    # docstring assertion.
    revolving_limit_cents = round(limit_dollars * 100 / 10_000) * 10_000

    util_rng = _rng(run_seed, applicant_seed_id, "utilization")
    utilization = _clip(0.55 - 0.16 * z + float(util_rng.normal(0.0, 0.08)), 0.0, 1.0)
    revolving_balance_cents = int(round(revolving_limit_cents * utilization))

    minor_rng = _rng(run_seed, applicant_seed_id, "delinq_minor")
    total_minor = int(minor_rng.poisson(max(0.0, 0.9 * math.exp(-1.1 * z))))
    split_rng = _rng(run_seed, applicant_seed_id, "delinq_minor_split")
    delinq_30d_24m = int(split_rng.binomial(total_minor, 0.6)) if total_minor else 0
    delinq_60d_24m = total_minor - delinq_30d_24m

    major_rng = _rng(run_seed, applicant_seed_id, "delinq_major")
    delinq_90p_24m = int(major_rng.poisson(max(0.0, 0.10 * math.exp(-1.6 * z))))

    public_records: list[PublicRecord] = []

    bk_rng = _rng(run_seed, applicant_seed_id, "bankruptcy")
    p_bankruptcy = _clip(0.05 * math.exp(-1.4 * z), 0.0, 0.25)
    if bk_rng.random() < p_bankruptcy:
        kind = (
            PublicRecordKind.BANKRUPTCY_CH7
            if bk_rng.random() < 0.7
            else PublicRecordKind.BANKRUPTCY_CH13
        )
        public_records.append(
            PublicRecord(
                kind=kind,
                months_ago=int(bk_rng.integers(0, 200)),
                amount_cents=int(bk_rng.integers(500_000, 5_000_000)),
            )
        )

    lien_rng = _rng(run_seed, applicant_seed_id, "public_record_derog")
    p_lien = _clip(0.08 * math.exp(-1.2 * z), 0.0, 0.30)
    if lien_rng.random() < p_lien:
        kind = lien_rng.choice(
            [PublicRecordKind.TAX_LIEN, PublicRecordKind.JUDGMENT, PublicRecordKind.COLLECTION]
        )
        public_records.append(
            PublicRecord(
                kind=PublicRecordKind(kind),
                months_ago=int(lien_rng.integers(0, 120)),
                amount_cents=int(lien_rng.integers(50_000, 2_000_000)),
            )
        )

    tradeline_rng = _rng(run_seed, applicant_seed_id, "oldest_tradeline")
    oldest_tradeline_months = int(
        _clip(70.0 + 45.0 * z + float(tradeline_rng.normal(0.0, 20.0)), 0.0, 480.0)
    )

    inquiries_rng = _rng(run_seed, applicant_seed_id, "inquiries")
    inquiries_6m = min(20, int(inquiries_rng.poisson(max(0.05, 2.2 - 0.9 * z))))

    employment_months_rng = _rng(run_seed, applicant_seed_id, "employment_months")
    employment_months = int(
        _clip(50.0 + 35.0 * z + float(employment_months_rng.normal(0.0, 24.0)), 0.0, 600.0)
    )

    status_rng = _rng(run_seed, applicant_seed_id, "employment_status")
    weights = dict(_EMPLOYMENT_BASE_WEIGHTS)
    if age_band in RETIRED_AGE_BANDS:
        weights[EmploymentStatus.RETIRED] *= 6.0
    statuses = list(weights.keys())
    total_weight = sum(weights.values())
    probs = [weights[s] / total_weight for s in statuses]
    employment_status = statuses[int(status_rng.choice(len(statuses), p=probs))]

    doc_rng = _rng(run_seed, applicant_seed_id, "income_documented")
    p_documented = _clip(0.80 + 0.04 * z, 0.0, 0.98)
    income_documented = bool(doc_rng.random() < p_documented)

    return {
        "credit_score": credit_score_from_z(z, calibration),
        "open_tradelines": open_tradelines,
        "revolving_balance_cents": revolving_balance_cents,
        "revolving_limit_cents": revolving_limit_cents,
        "delinq_30d_24m": delinq_30d_24m,
        "delinq_60d_24m": delinq_60d_24m,
        "delinq_90p_24m": delinq_90p_24m,
        "public_records": tuple(public_records),
        "oldest_tradeline_months": oldest_tradeline_months,
        "inquiries_6m": inquiries_6m,
        "employment_months": employment_months,
        "employment_status": employment_status,
        "income_documented": income_documented,
    }


__all__ = [
    "FicoBand",
    "FicoCalibration",
    "credit_score_from_z",
    "draw_latent_z",
    "load_fico_calibration",
    "synthesize",
]

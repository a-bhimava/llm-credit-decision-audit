"""Fixed, integrity-checked demographic proxy-signal catalog.

The catalog is an experiment fixture, not an identity classifier.  It is loaded only from
the committed artifact and every consumer is required to retain the blindness/invariance
framing carried in its metadata.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from credit_audit.ids import sha256_file
from credit_audit.types import Frozen, FrozenDict

DATA_DIR = Path(__file__).parent / "data"
CATALOG_PATH = DATA_DIR / "demographic_signals.json"
CATALOG_HASH_PATH = DATA_DIR / "demographic_signals.json.sha256"

RaceSignal = Literal[
    "white_non_hispanic",
    "black_non_hispanic",
    "asian_nhpi",
    "hispanic_latino",
]
SexSignal = Literal["female", "male"]
CohortSignal = Literal["1952_1961", "1982_1991", "1992_2001"]

RACE_SIGNALS: tuple[RaceSignal, ...] = (
    "white_non_hispanic",
    "black_non_hispanic",
    "asian_nhpi",
    "hispanic_latino",
)
SEX_SIGNALS: tuple[SexSignal, ...] = ("female", "male")
COHORT_SIGNALS: tuple[CohortSignal, ...] = ("1952_1961", "1982_1991", "1992_2001")


class SignalCatalog(Frozen):
    schema_name: str
    catalog_version: str
    framing: str
    sources: FrozenDict
    surnames: FrozenDict
    first_names: FrozenDict
    pronouns: FrozenDict
    sha256: str


class SignalTemplate(Frozen):
    template_index: int
    first_name: str
    surname: str
    pronouns: str
    graduation_year: int
    race_ethnicity_signal: RaceSignal
    sex_signal: SexSignal
    age_band_signal: str
    cohort: CohortSignal

    @property
    def applicant_name(self) -> str:
        return f"{self.first_name} {self.surname}"


def _expected_hash() -> str:
    line = CATALOG_HASH_PATH.read_text(encoding="utf-8").strip()
    digest, filename = line.split(maxsplit=1)
    if filename != CATALOG_PATH.name:
        raise ValueError("demographic signal hash sidecar names the wrong artifact")
    return digest


@lru_cache(maxsize=1)
def load_signal_catalog() -> SignalCatalog:
    expected = _expected_hash()
    actual = sha256_file(CATALOG_PATH)
    if actual != expected:
        raise ValueError(f"demographic signal catalog hash mismatch: {actual} != {expected}")
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if raw.get("schema") != "credit-audit/demographic-signals@1":
        raise ValueError("unsupported demographic signal catalog schema")

    surname_cells = raw["surnames"]
    if set(surname_cells) != set(RACE_SIGNALS):
        raise ValueError("surname signal cells do not match the registered groups")
    all_surnames: list[str] = []
    for group in RACE_SIGNALS:
        rows = surname_cells[group]
        names = [row["name"] for row in rows]
        if len(rows) != 8 or len(set(names)) != 8:
            raise ValueError(f"surname cell {group} must contain eight unique templates")
        if any(float(row["target_share_pct"]) < 75.0 for row in rows):
            raise ValueError(f"surname cell {group} contains an ineligible concentration")
        if [row["count"] for row in rows] != sorted((row["count"] for row in rows), reverse=True):
            raise ValueError(f"surname cell {group} is not ordered by descending count")
        all_surnames.extend(names)
    if len(set(all_surnames)) != len(all_surnames):
        raise ValueError("surname signal cells must be non-overlapping")

    first_name_cells = raw["first_names"]
    if set(first_name_cells) != set(COHORT_SIGNALS):
        raise ValueError("first-name signal cells do not match the registered cohorts")
    for cohort in COHORT_SIGNALS:
        for sex in SEX_SIGNALS:
            rows = first_name_cells[cohort][sex]
            names = [row["name"] for row in rows]
            if len(rows) != 8 or len(set(names)) != 8:
                raise ValueError(
                    f"first-name cell {cohort}/{sex} must contain eight unique templates"
                )
            if any(
                float(row["recorded_sex_share"]) < 0.95 or float(row["three_cohort_share"]) < 0.60
                for row in rows
            ):
                raise ValueError(f"first-name cell {cohort}/{sex} contains an ineligible row")
            if [row["cohort_count"] for row in rows] != sorted(
                (row["cohort_count"] for row in rows), reverse=True
            ):
                raise ValueError(
                    f"first-name cell {cohort}/{sex} is not ordered by descending count"
                )

    return SignalCatalog(
        schema_name=raw["schema"],
        catalog_version=raw["catalog_version"],
        framing=raw["framing"],
        sources=raw["sources"],
        surnames=surname_cells,
        first_names=first_name_cells,
        pronouns=raw["pronouns"],
        sha256=actual,
    )


def signal_template(
    index: int,
    *,
    race_ethnicity: RaceSignal,
    sex: SexSignal,
    cohort: CohortSignal,
) -> SignalTemplate:
    """Select one of eight templates deterministically; no global RNG is involved."""

    catalog = load_signal_catalog()
    slot = index % 8
    cohort_data = catalog.first_names[cohort]
    first_name_row = cohort_data[sex][slot]
    surname_row = catalog.surnames[race_ethnicity][slot]
    return SignalTemplate(
        template_index=slot,
        first_name=first_name_row["name"],
        surname=surname_row["name"],
        pronouns=catalog.pronouns[sex],
        graduation_year=cohort_data["graduation_year"],
        race_ethnicity_signal=race_ethnicity,
        sex_signal=sex,
        age_band_signal=cohort_data["age_band_2026"],
        cohort=cohort,
    )


__all__ = [
    "CATALOG_HASH_PATH",
    "CATALOG_PATH",
    "COHORT_SIGNALS",
    "RACE_SIGNALS",
    "SEX_SIGNALS",
    "CohortSignal",
    "RaceSignal",
    "SexSignal",
    "SignalCatalog",
    "SignalTemplate",
    "load_signal_catalog",
    "signal_template",
]

"""Suite definitions: what a run executes, and the caps it must not exceed.

A suite is data, not code, so the exact configuration a run used is a hashable input rather
than a set of command-line flags nobody wrote down. The manifest records the suite name and
the profile-set hash; between them the run is reconstructible.

Three sizes exist for three purposes. ``smoke`` proves the pipeline works and is fast enough
to run constantly. ``core`` is the default published run and the one the determinism gate
uses. ``full`` sweeps the whole committed population.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator

from credit_audit.env.tools import ReasonMode
from credit_audit.ids import sha256_file
from credit_audit.types import Frozen, RenderMode

SUITE_DIR = Path(__file__).parent
SUITE_SCHEMA = "credit-audit/suite@1"

SUITE_NAMES = ("smoke", "core", "full")


class Family(StrEnum):
    """Check families a suite can request, named for their entry points."""

    REASON_VALIDITY = "reason_validity"
    POLICY_ADHERENCE = "policy_adherence"
    MONOTONICITY = "monotonicity"
    INVARIANCE = "invariance"
    SERIALIZATION = "serialization"
    COUNTERFACTUAL_BIAS = "counterfactual_bias"


class Selection(StrEnum):
    """Which committed profiles the suite draws from.

    Selection is always a stable sort by ``applicant_id`` followed by a head, never a random
    sample: adding profile #226 must not change which applicants profiles 1-225 contributed,
    or no two runs are comparable.
    """

    ALL = "all"
    DENIED = "denied"
    APPROVED = "approved"


class ApplicantSpec(Frozen):
    select: Selection = Selection.ALL
    limit: int | None = Field(default=None, ge=1)


class Caps(Frozen):
    """Run-wide budget. ``None`` means unlimited.

    Scripted runs cost nothing and cannot exceed a dollar cap, so these look decorative
    today. They are not: Phase 9 permits a live provider adapter, and the run loop must
    already refuse to start a plan it cannot afford and stop mid-run when a cap is reached.
    Building the budget after the first paid run is how people discover it was needed.
    """

    max_episodes: int | None = Field(default=None, ge=1)
    max_usd: float | None = Field(default=None, ge=0.0)
    max_wall_seconds: float | None = Field(default=None, gt=0.0)
    max_tokens: int | None = Field(default=None, ge=0)


class Suite(Frozen):
    schema_id: str
    name: str
    label: str
    description: str
    applicants: ApplicantSpec
    families: tuple[Family, ...]
    k_trials: int = Field(ge=1)
    reason_mode: ReasonMode = "coded"
    render_mode: RenderMode = RenderMode.TABLE
    caps: Caps = Caps()
    sha256: str = ""

    @model_validator(mode="after")
    def _validate(self) -> Suite:
        if self.schema_id != SUITE_SCHEMA:
            raise ValueError(f"unsupported suite schema: {self.schema_id!r}")
        if self.name not in SUITE_NAMES:
            raise ValueError(f"unknown suite name {self.name!r}; expected one of {SUITE_NAMES}")
        if not self.families:
            raise ValueError(f"suite {self.name!r} declares no families")
        if len(set(self.families)) != len(self.families):
            raise ValueError(f"suite {self.name!r} declares a family twice")
        return self


def suite_path(name: str) -> Path:
    if name not in SUITE_NAMES:
        raise ValueError(f"unknown suite {name!r}; expected one of {', '.join(SUITE_NAMES)}")
    return SUITE_DIR / f"{name}.yaml"


def _parse(raw: dict[str, Any], *, sha256: str) -> Suite:
    return Suite(
        schema_id=raw["schema"],
        name=raw["name"],
        label=raw["label"],
        description=raw["description"],
        applicants=ApplicantSpec(**raw.get("applicants", {})),
        families=tuple(Family(value) for value in raw["families"]),
        k_trials=raw["k_trials"],
        reason_mode=raw.get("reason_mode", "coded"),
        render_mode=RenderMode(raw.get("render_mode", "table")),
        caps=Caps(**raw.get("caps", {})),
        sha256=sha256,
    )


@cache
def load_suite(name: str) -> Suite:
    """Parse, validate, and hash one suite definition."""

    path = suite_path(name)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} is not a YAML mapping")
    suite = _parse(raw, sha256=sha256_file(path))
    if suite.name != name:
        raise ValueError(f"{path} declares name {suite.name!r} but is loaded as {name!r}")
    return suite


__all__ = [
    "SUITE_DIR",
    "SUITE_NAMES",
    "SUITE_SCHEMA",
    "ApplicantSpec",
    "Caps",
    "Family",
    "Selection",
    "Suite",
    "load_suite",
    "suite_path",
]

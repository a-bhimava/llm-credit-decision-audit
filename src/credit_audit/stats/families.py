"""The preregistration boundary.

Every statistic in this project is scored against a declaration written before the run.
This module parses, validates, and hashes ``PREREGISTRATION.yaml`` and exposes the one
function that matters: :meth:`Preregistration.resolve`, which **raises** rather than
scoring a result whose family was never declared.

The asymmetry between family and check is deliberate. An undeclared *family* is a hard
error, because a family is the unit that BH multiplicity control is defined over and a
family invented after seeing results is exactly the failure preregistration exists to
prevent. An undeclared *check* inside a declared family is allowed but permanently marked
``exploratory``, which the export contract renders below the preregistered estimates with
its own chip. Neither path can silently mint a preregistered p-value.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator

from credit_audit.ids import sha256_file
from credit_audit.types import Family, Frozen, Relation

PREREG_DIR = Path(__file__).parent
PREREG_PATH = PREREG_DIR / "PREREGISTRATION.yaml"

PREREG_SCHEMA = "credit-audit/prereg@1"


class UndeclaredFamilyError(Exception):
    """Raised when a result's family is absent from the preregistration.

    This is not recoverable by the caller. Scoring it would mean reporting an estimate for a
    family nobody declared, which is the specific practice the preregistration exists to make
    impossible.
    """


class Estimand(StrEnum):
    """What a check's headline number measures. Declared, never inferred at scoring time."""

    CHECK_FAILURE_RATE = "check_failure_rate"
    """Proportion of applicable test results whose status is FAIL."""

    PAIRED_RATE_DIFFERENCE = "paired_rate_difference"
    """``approve_rate(cf) - approve_rate(base)`` over trial-index-aligned matched pairs."""

    FORBIDDEN_TRANSITION_RATE = "forbidden_transition_rate"
    """Rate of the one transition the declared relation forbids, over matched pairs.

    Deliberately not the net difference: a forbidden flip is not excused by an equal number
    of permitted flips in the other direction.
    """

    DECISION_SIGNATURE_CHANGE_RATE = "decision_signature_change_rate"
    """Matched pairs whose normalized decision signature changed, over matched pairs."""


class HypothesisTest(StrEnum):
    NONE = "none"
    MCNEMAR_EXACT = "mcnemar_exact"


class Direction(StrEnum):
    """How the site should orient the estimate. Never affects the arithmetic."""

    LOWER_IS_BETTER = "lower_is_better"
    HIGHER_IS_BETTER = "higher_is_better"
    NONE = "none"


PAIRED_ESTIMANDS = frozenset(
    {
        Estimand.PAIRED_RATE_DIFFERENCE,
        Estimand.FORBIDDEN_TRANSITION_RATE,
        Estimand.DECISION_SIGNATURE_CHANGE_RATE,
    }
)
"""Estimands computed from matched pair counts rather than from result statuses."""


_RELATION_FORBIDS = {
    Relation.NONDECREASING: "approve_to_adverse",
    Relation.NONINCREASING: "adverse_to_approve",
}
"""The transition each monotone relation forbids, as a key of ``PairedScore.observed()``."""


class Hypothesis(Frozen):
    """One preregistered comparison."""

    id: str
    label: str
    family: Family
    check: str | None = None
    check_prefix: str | None = None
    relation: Relation
    delta: float = Field(ge=0.0, le=1.0)
    estimand: Estimand
    test: HypothesisTest = HypothesisTest.NONE
    direction: Direction = Direction.NONE
    exploratory: bool = False

    @model_validator(mode="after")
    def _validate(self) -> Hypothesis:
        if (self.check is None) == (self.check_prefix is None):
            raise ValueError(
                f"hypothesis {self.id!r} must declare exactly one of check/check_prefix"
            )
        if (
            self.estimand is Estimand.FORBIDDEN_TRANSITION_RATE
            and self.relation not in _RELATION_FORBIDS
        ):
            raise ValueError(
                f"hypothesis {self.id!r} declares forbidden_transition_rate but relation "
                f"{self.relation} forbids no single transition"
            )
        if (
            self.test is HypothesisTest.MCNEMAR_EXACT
            and self.estimand is Estimand.CHECK_FAILURE_RATE
        ):
            raise ValueError(
                f"hypothesis {self.id!r} declares a paired test for an unpaired estimand"
            )
        return self

    @property
    def forbidden_transition(self) -> str | None:
        """Which matched transition this hypothesis counts as a violation, if any."""

        return _RELATION_FORBIDS.get(self.relation)

    def matches(self, check: str) -> bool:
        if self.check is not None:
            return check == self.check
        assert self.check_prefix is not None
        return check.startswith(self.check_prefix)

    @property
    def specificity(self) -> int:
        """Longer declarations win when several could match one dotted check identifier."""

        return len(self.check) if self.check is not None else len(self.check_prefix or "")


class FamilyDeclaration(Frozen):
    family: Family
    label: str
    hypotheses: tuple[Hypothesis, ...] = ()


class FDRPolicy(Frozen):
    procedure: str
    q: float = Field(gt=0.0, lt=1.0)
    grouping: str

    @model_validator(mode="after")
    def _validate(self) -> FDRPolicy:
        if self.procedure != "benjamini_hochberg":
            raise ValueError(f"unsupported FDR procedure: {self.procedure!r}")
        if self.grouping != "family":
            raise ValueError(f"unsupported BH grouping: {self.grouping!r}")
        return self


class BootstrapPolicy(Frozen):
    method: str
    B: int = Field(gt=0)
    resampling_unit: str
    fallback: str
    seed: int

    @model_validator(mode="after")
    def _validate(self) -> BootstrapPolicy:
        if self.method != "BCa":
            raise ValueError(f"unsupported bootstrap method: {self.method!r}")
        if self.fallback != "percentile":
            raise ValueError(f"unsupported bootstrap fallback: {self.fallback!r}")
        if self.resampling_unit != "cluster_id":
            # The cut line in the roadmap allows dropping BCa for percentile. It never allows
            # dropping the clustering: sibling profiles and every contrast built from one
            # source applicant are dependent, and resampling them independently reports a
            # standard error smaller than the design supports.
            raise ValueError(
                "the bootstrap resampling unit must be cluster_id (the originating source "
                f"applicant), not {self.resampling_unit!r}"
            )
        return self


class PowerPolicy(Frozen):
    target_power: float = Field(gt=0.0, lt=1.0)
    reported_before_run: bool = True


class PassKPolicy(Frozen):
    k: int = Field(ge=1)
    estimator: str

    @model_validator(mode="after")
    def _validate(self) -> PassKPolicy:
        if self.estimator != "unbiased_combinatorial":
            raise ValueError(f"unsupported pass^k estimator: {self.estimator!r}")
        return self


class Resolution(Frozen):
    """How one check identifier was scored against the declaration."""

    check: str
    family: Family
    hypothesis: Hypothesis | None
    prereg: bool
    exploratory: bool
    operational: bool = False

    @property
    def estimand(self) -> Estimand:
        return self.hypothesis.estimand if self.hypothesis else Estimand.CHECK_FAILURE_RATE

    @property
    def test(self) -> HypothesisTest:
        return self.hypothesis.test if self.hypothesis else HypothesisTest.NONE


class Preregistration(Frozen):
    schema_id: str
    version: int
    alpha: float = Field(gt=0.0, lt=1.0)
    fdr: FDRPolicy
    bootstrap: BootstrapPolicy
    power: PowerPolicy
    pass_k: PassKPolicy
    families: tuple[FamilyDeclaration, ...]
    operational_checks: tuple[str, ...] = ()
    frozen_at: str | None = None
    git_tag: str | None = None
    sha256: str = ""
    """Hash of the document as loaded. Recorded in the run manifest so a reader can verify
    that the reported numbers were scored against this exact declaration."""

    @model_validator(mode="after")
    def _validate(self) -> Preregistration:
        if self.schema_id != PREREG_SCHEMA:
            raise ValueError(f"unsupported preregistration schema: {self.schema_id!r}")
        seen_families: set[Family] = set()
        seen_ids: set[str] = set()
        seen_targets: set[str] = set()
        for declaration in self.families:
            if declaration.family in seen_families:
                raise ValueError(f"family declared twice: {declaration.family}")
            seen_families.add(declaration.family)
            for hypothesis in declaration.hypotheses:
                if hypothesis.family is not declaration.family:
                    raise ValueError(
                        f"hypothesis {hypothesis.id!r} is nested under {declaration.family} "
                        f"but declares {hypothesis.family}"
                    )
                if hypothesis.id in seen_ids:
                    raise ValueError(f"hypothesis id declared twice: {hypothesis.id!r}")
                seen_ids.add(hypothesis.id)
                target = hypothesis.check or hypothesis.check_prefix
                assert target is not None
                if target in seen_targets:
                    raise ValueError(f"check target declared twice: {target!r}")
                seen_targets.add(target)
        for check in self.operational_checks:
            if any(h.matches(check) for h in self.hypotheses):
                raise ValueError(
                    f"{check!r} is declared both operational and as a hypothesis target"
                )
        return self

    @property
    def hypotheses(self) -> tuple[Hypothesis, ...]:
        return tuple(h for declaration in self.families for h in declaration.hypotheses)

    @property
    def declared_families(self) -> frozenset[Family]:
        return frozenset(declaration.family for declaration in self.families)

    def require_declared(self, family: Family) -> FamilyDeclaration:
        """Return the declaration for ``family``, or raise :class:`UndeclaredFamilyError`."""

        for declaration in self.families:
            if declaration.family is family:
                return declaration
        raise UndeclaredFamilyError(
            f"family {family} is not declared in the preregistration "
            f"({PREREG_PATH.name}, sha256 {self.sha256}); refusing to score it. "
            "Declare it and re-freeze the document, or route the result to a declared family."
        )

    def hypothesis_for(self, check: str) -> Hypothesis | None:
        """The most specific declaration matching ``check``, or ``None``."""

        candidates = [h for h in self.hypotheses if h.matches(check)]
        if not candidates:
            return None
        return max(candidates, key=lambda h: h.specificity)

    def resolve(self, check: str, family: Family) -> Resolution:
        """Bind one check identifier to its declaration.

        Raises :class:`UndeclaredFamilyError` when ``family`` was never declared, and
        ``ValueError`` when a declared hypothesis contradicts the family the result claims.
        """

        self.require_declared(family)
        if check in self.operational_checks:
            return Resolution(
                check=check,
                family=family,
                hypothesis=None,
                prereg=False,
                exploratory=False,
                operational=True,
            )
        hypothesis = self.hypothesis_for(check)
        if hypothesis is None:
            return Resolution(
                check=check,
                family=family,
                hypothesis=None,
                prereg=False,
                exploratory=True,
            )
        if hypothesis.family is not family:
            raise ValueError(
                f"check {check!r} arrived as family {family} but is declared under "
                f"{hypothesis.family} by hypothesis {hypothesis.id!r}"
            )
        return Resolution(
            check=check,
            family=family,
            hypothesis=hypothesis,
            prereg=not hypothesis.exploratory,
            exploratory=hypothesis.exploratory,
        )


def _isoformat(value: Any) -> str:
    """Normalize a YAML timestamp to ISO-8601.

    PyYAML hands back a ``datetime`` for an unquoted timestamp and a ``str`` for a quoted one.
    Both must serialize identically, or the published freeze time depends on how the document
    happened to be typed.
    """

    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        # Not a timestamp we can normalize. Publish it verbatim rather than guessing; the
        # freeze time is evidence, and a silently reformatted one is worse than an odd one.
        return text


def _parse(raw: dict[str, Any], *, sha256: str) -> Preregistration:
    families: list[FamilyDeclaration] = []
    for entry in raw.get("families", ()):
        family = Family(entry["family"])
        hypotheses = tuple(
            Hypothesis(family=family, **hypothesis) for hypothesis in entry.get("hypotheses", ())
        )
        families.append(
            FamilyDeclaration(family=family, label=entry["label"], hypotheses=hypotheses)
        )
    frozen_at = raw.get("frozen_at")
    return Preregistration(
        schema_id=raw["schema"],
        version=raw["version"],
        alpha=raw["alpha"],
        fdr=FDRPolicy(**raw["fdr"]),
        bootstrap=BootstrapPolicy(**raw["bootstrap"]),
        power=PowerPolicy(**raw["power"]),
        pass_k=PassKPolicy(**raw["pass_k"]),
        families=tuple(families),
        operational_checks=tuple(raw.get("operational_checks", ())),
        # ISO-8601, not ``str(datetime)``. The same instant reaches the bundle through three
        # paths (manifest.json, integrity/chain.json, stats/estimates.json); a space separator
        # here and a "T" there reads to a reviewer as two different timestamps.
        frozen_at=None if frozen_at is None else _isoformat(frozen_at),
        git_tag=raw.get("git_tag"),
        sha256=sha256,
    )


@cache
def load_preregistration(path: Path = PREREG_PATH) -> Preregistration:
    """Parse, validate, and hash the preregistration document."""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} is not a YAML mapping")
    return _parse(raw, sha256=sha256_file(path))


__all__ = [
    "PREREG_PATH",
    "PREREG_SCHEMA",
    "BootstrapPolicy",
    "Direction",
    "Estimand",
    "FDRPolicy",
    "FamilyDeclaration",
    "Hypothesis",
    "PassKPolicy",
    "PowerPolicy",
    "Preregistration",
    "Resolution",
    "HypothesisTest",
    "UndeclaredFamilyError",
    "load_preregistration",
]

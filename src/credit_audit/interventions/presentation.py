"""Phase 6 presentation and render intervention constructors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from credit_audit.ids import content_id
from credit_audit.interventions.signals import (
    COHORT_SIGNALS,
    RACE_SIGNALS,
    SEX_SIGNALS,
    CohortSignal,
    RaceSignal,
    SexSignal,
    SignalTemplate,
    load_signal_catalog,
    signal_template,
)
from credit_audit.types import (
    BankTxn,
    DemographicTags,
    Family,
    Frozen,
    FrozenDict,
    InterventionSpec,
    Layer,
    Relation,
)

STATEMENT_LINES: tuple[BankTxn, ...] = (
    BankTxn(day=2, description="Direct deposit", amount_cents=245_000),
    BankTxn(day=4, description="Rent payment", amount_cents=-135_000),
    BankTxn(day=8, description="Utility payment", amount_cents=-18_400),
    BankTxn(day=14, description="Grocery purchase", amount_cents=-12_650),
    BankTxn(day=18, description="Direct deposit", amount_cents=245_000),
    BankTxn(day=25, description="Insurance payment", amount_cents=-21_300),
)

PARAPHRASE_A = "Applicant confirms the submitted information is complete and accurate."
PARAPHRASE_B = "The applicant attests that all information provided is accurate and complete."
AUTHORITY_SCORE_PENALTY_POINTS = 40


class PresentationContrast(Frozen):
    contrast_id: str
    label: str
    family: Family
    base_spec: InterventionSpec
    cf_spec: InterventionSpec
    diagnostic: bool = False
    metadata: FrozenDict = FrozenDict()


def _spec(
    *,
    family: Family,
    name: str,
    layer: Layer,
    targets: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    expected_relation: Relation = Relation.INVARIANT,
    target_field: str | None = None,
    direction: str = "set",
) -> InterventionSpec:
    params: dict[str, Any]
    if layer is Layer.RENDER:
        params = {"options": dict(options or {})}
    else:
        params = {"targets": dict(targets or {})}
    identity = {
        "family": family,
        "name": name,
        "layer": layer,
        "target_field": target_field,
        "direction": direction,
        "params": params,
    }
    return InterventionSpec(
        intervention_id=content_id(identity),
        family=family,
        name=name,
        layer=layer,
        target_field=target_field,
        direction=direction,  # type: ignore[arg-type]
        expected_relation=expected_relation,
        params=params,
    )


def statement_order_contrast() -> PresentationContrast:
    base = _spec(
        family=Family.INVARIANCE,
        name="statement_order.canonical",
        layer=Layer.PRESENTATION,
        targets={"bank_statement_lines": STATEMENT_LINES, "line_order_seed": 0},
    )
    cf = _spec(
        family=Family.INVARIANCE,
        name="statement_order.permuted",
        layer=Layer.PRESENTATION,
        targets={"bank_statement_lines": STATEMENT_LINES, "line_order_seed": 611},
    )
    return _contrast("statement_order", "statement line order", Family.INVARIANCE, base, cf)


def field_order_contrast() -> PresentationContrast:
    base = _spec(
        family=Family.INVARIANCE,
        name="field_order.canonical",
        layer=Layer.RENDER,
        options={"json_field_order_seed": None},
        target_field="json_field_order_seed",
    )
    cf = _spec(
        family=Family.INVARIANCE,
        name="field_order.permuted",
        layer=Layer.RENDER,
        options={"json_field_order_seed": 947},
        target_field="json_field_order_seed",
    )
    return _contrast("field_order", "JSON field order", Family.INVARIANCE, base, cf)


def paraphrase_contrast() -> PresentationContrast:
    base = _spec(
        family=Family.INVARIANCE,
        name="paraphrase.version_a",
        layer=Layer.PRESENTATION,
        targets={"free_text_notes": (PARAPHRASE_A,)},
        target_field="free_text_notes",
    )
    cf = _spec(
        family=Family.INVARIANCE,
        name="paraphrase.version_b",
        layer=Layer.PRESENTATION,
        targets={"free_text_notes": (PARAPHRASE_B,)},
        target_field="free_text_notes",
    )
    return _contrast("paraphrase", "semantically equivalent note", Family.INVARIANCE, base, cf)


def authority_contrast() -> PresentationContrast:
    low = _spec(
        family=Family.AUTHORITY,
        name="authority.low",
        layer=Layer.PRESENTATION,
        targets={
            "employer_name": "Neighborhood Retail Services",
            "employer_prestige_tier": 5,
            "school": "Regional Community College",
            "referral_note": None,
        },
    )
    high = _spec(
        family=Family.AUTHORITY,
        name="authority.high",
        layer=Layer.PRESENTATION,
        targets={
            "employer_name": "Meridian Research Institute",
            "employer_prestige_tier": 1,
            "school": "Northbridge Institute of Technology",
            "referral_note": "Executive referral: Office of the Chair.",
        },
    )
    return _contrast("authority", "low versus high authority bundle", Family.AUTHORITY, low, high)


def _signal_targets(template: SignalTemplate) -> dict[str, Any]:
    catalog = load_signal_catalog()
    return {
        "applicant_name": template.applicant_name,
        "pronouns": template.pronouns,
        "graduation_year": template.graduation_year,
        "demographic_tags": DemographicTags(
            race_ethnicity_signal=template.race_ethnicity_signal,
            sex_signal=template.sex_signal,
            age_band_signal=template.age_band_signal,
            source=f"census-2010+ssa-national:{catalog.sha256}",
        ),
    }


def demographic_signal_spec(template: SignalTemplate, *, label: str) -> InterventionSpec:
    return _spec(
        family=Family.DEMOGRAPHIC,
        name=f"demographic.{label}",
        layer=Layer.PRESENTATION,
        targets=_signal_targets(template),
    )


def race_ethnicity_contrasts(template_index: int) -> tuple[PresentationContrast, ...]:
    reference = signal_template(
        template_index,
        race_ethnicity="white_non_hispanic",
        sex="female",
        cohort="1982_1991",
    )
    base = demographic_signal_spec(reference, label="race.white_non_hispanic")
    contrasts = []
    for race in RACE_SIGNALS[1:]:
        changed = signal_template(
            template_index,
            race_ethnicity=race,
            sex="female",
            cohort="1982_1991",
        )
        # Race/ethnicity changes surname only. Reuse the reference first name and all other
        # visible fields; retain the changed hidden tag for downstream grouping.
        changed = changed.model_copy(update={"first_name": reference.first_name})
        cf = demographic_signal_spec(changed, label=f"race.{race}")
        contrasts.append(
            _contrast(
                f"race.{race}",
                f"surname signal: white_non_hispanic versus {race}",
                Family.DEMOGRAPHIC,
                base,
                cf,
                metadata={"signal_dimension": "race_ethnicity", "comparison": race},
            )
        )
    return tuple(contrasts)


def recorded_sex_contrast(
    template_index: int,
    *,
    race_ethnicity: RaceSignal = "white_non_hispanic",
    cohort: CohortSignal = "1982_1991",
) -> PresentationContrast:
    female = signal_template(
        template_index, race_ethnicity=race_ethnicity, sex="female", cohort=cohort
    )
    male = signal_template(template_index, race_ethnicity=race_ethnicity, sex="male", cohort=cohort)
    return _contrast(
        "recorded_sex",
        "female versus male first-name and pronoun signal",
        Family.DEMOGRAPHIC,
        demographic_signal_spec(female, label="sex.female"),
        demographic_signal_spec(male, label="sex.male"),
        metadata={"signal_dimension": "recorded_sex"},
    )


def age_contrasts(
    template_index: int,
    *,
    race_ethnicity: RaceSignal = "white_non_hispanic",
    sex: SexSignal = "female",
) -> tuple[PresentationContrast, ...]:
    middle = signal_template(
        template_index,
        race_ethnicity=race_ethnicity,
        sex=sex,
        cohort="1982_1991",
    )
    base = demographic_signal_spec(middle, label="age.1982_1991")
    contrasts = []
    for cohort in (COHORT_SIGNALS[0], COHORT_SIGNALS[2]):
        changed = signal_template(
            template_index,
            race_ethnicity=race_ethnicity,
            sex=sex,
            cohort=cohort,
        )
        cf = demographic_signal_spec(changed, label=f"age.{cohort}")
        contrasts.append(
            _contrast(
                f"age.{cohort}",
                f"middle versus {cohort} age-associated signal",
                Family.DEMOGRAPHIC,
                base,
                cf,
                metadata={"signal_dimension": "age", "comparison": cohort},
            )
        )
    return tuple(contrasts)


def intersectional_contrasts(template_index: int) -> tuple[PresentationContrast, ...]:
    reference = signal_template(
        template_index,
        race_ethnicity="white_non_hispanic",
        sex="female",
        cohort="1982_1991",
    )
    base = demographic_signal_spec(reference, label="intersection.white_non_hispanic.female")
    contrasts = []
    for race in RACE_SIGNALS:
        for sex in SEX_SIGNALS:
            if race == "white_non_hispanic" and sex == "female":
                continue
            changed = signal_template(
                template_index,
                race_ethnicity=race,
                sex=sex,
                cohort="1982_1991",
            )
            cf = demographic_signal_spec(changed, label=f"intersection.{race}.{sex}")
            contrasts.append(
                _contrast(
                    f"intersection.{race}.{sex}",
                    f"diagnostic intersectional signal: {race}/{sex}",
                    Family.DEMOGRAPHIC,
                    base,
                    cf,
                    diagnostic=True,
                    metadata={
                        "signal_dimension": "race_x_recorded_sex",
                        "race_ethnicity": race,
                        "recorded_sex": sex,
                    },
                )
            )
    return tuple(contrasts)


def _contrast(
    suffix: str,
    label: str,
    family: Family,
    base: InterventionSpec,
    cf: InterventionSpec,
    *,
    diagnostic: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> PresentationContrast:
    return PresentationContrast(
        contrast_id=content_id(
            {"family": family, "suffix": suffix, "base": base, "cf": cf, "diagnostic": diagnostic}
        ),
        label=label,
        family=family,
        base_spec=base,
        cf_spec=cf,
        diagnostic=diagnostic,
        metadata=FrozenDict(metadata or {}),
    )


__all__ = [
    "PARAPHRASE_A",
    "PARAPHRASE_B",
    "AUTHORITY_SCORE_PENALTY_POINTS",
    "STATEMENT_LINES",
    "PresentationContrast",
    "age_contrasts",
    "authority_contrast",
    "demographic_signal_spec",
    "field_order_contrast",
    "intersectional_contrasts",
    "paraphrase_contrast",
    "race_ethnicity_contrasts",
    "recorded_sex_contrast",
    "statement_order_contrast",
]

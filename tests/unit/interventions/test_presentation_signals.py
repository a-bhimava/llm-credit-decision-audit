from __future__ import annotations

from credit_audit.ids import content_id, sha256_file
from credit_audit.interventions.apply import apply_intervention
from credit_audit.interventions.presentation import (
    age_contrasts,
    authority_contrast,
    field_order_contrast,
    race_ethnicity_contrasts,
    recorded_sex_contrast,
    statement_order_contrast,
)
from credit_audit.interventions.signals import (
    CATALOG_PATH,
    COHORT_SIGNALS,
    RACE_SIGNALS,
    SEX_SIGNALS,
    load_signal_catalog,
)
from credit_audit.render.packet import build_application_packet
from credit_audit.types import Layer


def test_catalog_hash_and_eight_templates_per_cell():
    catalog = load_signal_catalog()
    assert catalog.sha256 == sha256_file(CATALOG_PATH)
    surnames = []
    for race in RACE_SIGNALS:
        assert len(catalog.surnames[race]) == 8
        rows = catalog.surnames[race]
        assert all(float(row["target_share_pct"]) >= 75.0 for row in rows)
        assert [row["count"] for row in rows] == sorted(
            (row["count"] for row in rows), reverse=True
        )
        surnames.extend(row["name"] for row in rows)
    assert len(surnames) == len(set(surnames))
    for cohort in COHORT_SIGNALS:
        for sex in SEX_SIGNALS:
            rows = catalog.first_names[cohort][sex]
            assert len(rows) == 8
            assert all(float(row["recorded_sex_share"]) >= 0.95 for row in rows)
            assert all(float(row["three_cohort_share"]) >= 0.60 for row in rows)
    assert catalog.sources["surnames"]["verification_payload_sha256"].startswith("sha256:")
    assert catalog.sources["first_names"]["verification_payload_sha256"].startswith("sha256:")


def test_statement_pair_has_same_multiset_and_different_realized_order(
    golden_clean_applicant,
):
    contrast = statement_order_contrast()
    base = apply_intervention(golden_clean_applicant, contrast.base_spec)
    cf = apply_intervention(golden_clean_applicant, contrast.cf_spec)
    base_lines = build_application_packet(base).statement_lines
    cf_lines = build_application_packet(cf).statement_lines
    assert sorted(base_lines, key=repr) == sorted(cf_lines, key=repr)
    assert base_lines != cf_lines
    assert content_id(base.facts) == content_id(cf.facts)


def test_statement_permutation_cannot_be_identity_for_a_seed_collision(
    golden_clean_applicant,
):
    collision = golden_clean_applicant.model_copy(update={"applicant_id": "COLLIDE-1175"})
    contrast = statement_order_contrast()
    base = apply_intervention(collision, contrast.base_spec)
    cf = apply_intervention(collision, contrast.cf_spec)
    assert (
        build_application_packet(base).statement_lines
        != build_application_packet(cf).statement_lines
    )


def test_field_order_is_a_render_layer_intervention():
    contrast = field_order_contrast()
    assert contrast.base_spec.layer is Layer.RENDER
    assert contrast.cf_spec.layer is Layer.RENDER


def test_authority_bundle_changes_only_presentation(golden_clean_applicant):
    contrast = authority_contrast()
    low = apply_intervention(golden_clean_applicant, contrast.base_spec)
    high = apply_intervention(golden_clean_applicant, contrast.cf_spec)
    assert low.facts == high.facts
    assert low.presentation.employer_name == "Neighborhood Retail Services"
    assert high.presentation.employer_name == "Meridian Research Institute"
    assert low.presentation.employer_prestige_tier == 5
    assert high.presentation.employer_prestige_tier == 1


def test_demographic_contrasts_change_only_declared_visible_signals(golden_clean_applicant):
    race = race_ethnicity_contrasts(0)[0]
    race_base = apply_intervention(golden_clean_applicant, race.base_spec)
    race_cf = apply_intervention(golden_clean_applicant, race.cf_spec)
    assert race_base.facts == race_cf.facts
    assert (
        race_base.presentation.applicant_name.split()[0]
        == (race_cf.presentation.applicant_name.split()[0])
    )
    assert (
        race_base.presentation.applicant_name.split()[1]
        != (race_cf.presentation.applicant_name.split()[1])
    )
    assert race_base.presentation.pronouns == race_cf.presentation.pronouns
    assert race_base.presentation.graduation_year == race_cf.presentation.graduation_year

    sex = recorded_sex_contrast(0)
    sex_base = apply_intervention(golden_clean_applicant, sex.base_spec)
    sex_cf = apply_intervention(golden_clean_applicant, sex.cf_spec)
    assert (
        sex_base.presentation.applicant_name.split()[1]
        == (sex_cf.presentation.applicant_name.split()[1])
    )
    assert sex_base.presentation.pronouns != sex_cf.presentation.pronouns
    assert sex_base.presentation.graduation_year == sex_cf.presentation.graduation_year

    age = age_contrasts(0)[0]
    age_base = apply_intervention(golden_clean_applicant, age.base_spec)
    age_cf = apply_intervention(golden_clean_applicant, age.cf_spec)
    assert (
        age_base.presentation.applicant_name.split()[1]
        == (age_cf.presentation.applicant_name.split()[1])
    )
    assert age_base.presentation.pronouns == age_cf.presentation.pronouns
    assert age_base.presentation.graduation_year != age_cf.presentation.graduation_year

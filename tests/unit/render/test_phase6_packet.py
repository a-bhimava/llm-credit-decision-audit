from __future__ import annotations

import json

from credit_audit.render.packet import RenderOptions, build_application_packet
from credit_audit.render.registry import RENDERERS, render_application
from credit_audit.types import BankTxn, DemographicTags, RenderMode


def _rich_applicant(golden_clean_applicant):
    presentation = golden_clean_applicant.presentation.model_copy(
        update={
            "applicant_name": "Avery Visible",
            "employer_name": "Visible Employer",
            "school": "Visible School",
            "referral_note": "Visible referral.",
            "pronouns": "they/them",
            "graduation_year": 2008,
            "bank_statement_lines": (
                BankTxn(day=1, description="Visible transaction A", amount_cents=100),
                BankTxn(day=2, description="Visible transaction B", amount_cents=-50),
            ),
            "free_text_notes": ("Visible note.",),
            "demographic_tags": DemographicTags(
                race_ethnicity_signal="HIDDEN_RACE_SENTINEL",
                sex_signal="HIDDEN_SEX_SENTINEL",
                age_band_signal="HIDDEN_AGE_SENTINEL",
            ),
            "employer_prestige_tier": 5,
            "narrative_tone": "negative",
            "line_order_seed": 991,
        }
    )
    return golden_clean_applicant.model_copy(update={"presentation": presentation})


def test_semantic_packet_contains_visible_surface_and_omits_control_labels(
    golden_clean_applicant,
):
    applicant = _rich_applicant(golden_clean_applicant)
    packet = build_application_packet(applicant)
    serialized = packet.model_dump_json()
    for visible in (
        "Avery Visible",
        "Visible Employer",
        "Visible School",
        "Visible referral",
        "they/them",
        "Visible transaction A",
        "Visible note",
    ):
        assert visible in serialized
    for hidden in (
        "HIDDEN_RACE_SENTINEL",
        "HIDDEN_SEX_SENTINEL",
        "HIDDEN_AGE_SENTINEL",
        "employer_prestige_tier",
        "narrative_tone",
        "line_order_seed",
    ):
        assert hidden not in serialized


def test_every_renderer_uses_visible_packet_without_hidden_labels(golden_clean_applicant, policy):
    applicant = _rich_applicant(golden_clean_applicant)
    for mode in RenderMode:
        text = RENDERERS[mode](applicant, mode, policy)
        for visible in (
            "Avery Visible",
            "Visible Employer",
            "Visible School",
            "Visible referral",
            "they/them",
            "2008",
            "Visible transaction A",
            "Visible note",
        ):
            assert visible in text
        assert "HIDDEN_" not in text
        assert "prestige_tier" not in text
        assert "line_order_seed" not in text


def test_json_field_order_changes_bytes_not_semantics(golden_clean_applicant, policy):
    canonical = render_application(
        golden_clean_applicant,
        RenderMode.JSON,
        policy,
        options=RenderOptions(),
    )
    permuted = render_application(
        golden_clean_applicant,
        RenderMode.JSON,
        policy,
        options=RenderOptions(json_field_order_seed=47),
    )
    assert canonical != permuted
    assert json.loads(canonical) == json.loads(permuted)


def test_prose_preserves_present_but_empty_optional_fields(golden_clean_applicant, policy):
    applicant = golden_clean_applicant.model_copy(
        update={
            "presentation": golden_clean_applicant.presentation.model_copy(
                update={"school": "", "referral_note": "", "pronouns": ""}
            )
        }
    )
    prose = render_application(applicant, RenderMode.PROSE, policy)
    assert "the listed school is " in prose
    assert "the application carries the referral note " in prose
    assert "the applicant lists pronouns " in prose

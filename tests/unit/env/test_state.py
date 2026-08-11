"""env/state.py -- construction-is-reset, and what state_fingerprint deliberately omits."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from credit_audit.env.state import CreditEnvState, state_fingerprint
from credit_audit.ids import applicant_content_id, episode_input_hash
from credit_audit.render.reference import applicant_reference_for
from credit_audit.types import EpisodeKey, RenderMode


def _key(applicant, application_text="stub", **overrides) -> EpisodeKey:
    applicant_ref = applicant_reference_for(applicant)
    base = dict(
        applicant_id=applicant.applicant_id,
        applicant_content_id=applicant_content_id(applicant),
        arm_id="control",
        render_id=RenderMode.TABLE,
        trial_index=0,
        model_id="scripted:faithful",
        prompt_hash="stub",
        input_hash=episode_input_hash(
            applicant,
            application_text=application_text,
            applicant_ref=applicant_ref,
            render_mode=RenderMode.TABLE,
        ),
        seed=1729,
    )
    base.update(overrides)
    return EpisodeKey(**base)


def test_construction_is_reset(golden_clean_applicant, policy):
    """Two independently-constructed states with identical inputs are equal but distinct
    objects -- reset is object construction, not a shared mutable teardown."""
    a = CreditEnvState(
        episode_key=_key(golden_clean_applicant),
        applicant=golden_clean_applicant,
        policy=policy,
        application_text="stub",
        applicant_ref=applicant_reference_for(golden_clean_applicant),
        render_mode=RenderMode.TABLE,
    )
    b = CreditEnvState(
        episode_key=_key(golden_clean_applicant),
        applicant=golden_clean_applicant,
        policy=policy,
        application_text="stub",
        applicant_ref=applicant_reference_for(golden_clean_applicant),
        render_mode=RenderMode.TABLE,
    )
    assert a == b
    assert a is not b
    assert a.step == 0
    assert a.tools_called == ()
    assert a.decision is None
    assert a.terminated is False


def test_state_is_frozen(golden_clean_applicant, policy):
    state = CreditEnvState(
        episode_key=_key(golden_clean_applicant),
        applicant=golden_clean_applicant,
        policy=policy,
        application_text="stub",
        applicant_ref=applicant_reference_for(golden_clean_applicant),
        render_mode=RenderMode.TABLE,
    )
    with pytest.raises(ValidationError):
        state.step = 5  # type: ignore[misc]


def test_fingerprint_excludes_application_text_and_policy(golden_clean_applicant, policy):
    """The fingerprint is a deliberate projection -- application_text and the full policy
    document must not affect it, since thousands of episodes share the same policy."""
    state_a = CreditEnvState(
        episode_key=_key(golden_clean_applicant, "text A"),
        applicant=golden_clean_applicant,
        policy=policy,
        application_text="text A",
        applicant_ref=applicant_reference_for(golden_clean_applicant),
        render_mode=RenderMode.TABLE,
    )
    state_b = state_a.model_copy(update={"application_text": "completely different text"})
    assert state_fingerprint(state_a) == state_fingerprint(state_b)


def test_fingerprint_changes_with_tools_called(golden_clean_applicant, policy):
    state_a = CreditEnvState(
        episode_key=_key(golden_clean_applicant),
        applicant=golden_clean_applicant,
        policy=policy,
        application_text="stub",
        applicant_ref=applicant_reference_for(golden_clean_applicant),
        render_mode=RenderMode.TABLE,
    )
    state_b = state_a.model_copy(update={"tools_called": ("get_application",), "step": 1})
    assert state_fingerprint(state_a) != state_fingerprint(state_b)


def test_state_rejects_mismatched_identity(golden_clean_applicant, policy):
    with pytest.raises(ValidationError, match="applicant_id"):
        CreditEnvState(
            episode_key=_key(golden_clean_applicant).model_copy(
                update={"applicant_id": "APP-WRONG"}
            ),
            applicant=golden_clean_applicant,
            policy=policy,
            application_text="stub",
            applicant_ref=applicant_reference_for(golden_clean_applicant),
            render_mode=RenderMode.TABLE,
        )

    with pytest.raises(ValidationError, match="canonical"):
        CreditEnvState(
            episode_key=_key(golden_clean_applicant),
            applicant=golden_clean_applicant,
            policy=policy,
            application_text="stub",
            applicant_ref="wrong",
            render_mode=RenderMode.TABLE,
        )

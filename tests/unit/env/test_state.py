"""env/state.py -- construction-is-reset, and what state_fingerprint deliberately omits."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from credit_audit.env.state import CreditEnvState, state_fingerprint
from credit_audit.types import EpisodeKey, RenderMode


def _key(**overrides) -> EpisodeKey:
    base = dict(
        applicant_id="APP-1",
        arm_id="control",
        render_id=RenderMode.TABLE,
        trial_index=0,
        model_id="scripted:faithful",
        prompt_hash="stub",
        seed=1729,
    )
    base.update(overrides)
    return EpisodeKey(**base)


def test_construction_is_reset(golden_clean_applicant, policy):
    """Two independently-constructed states with identical inputs are equal but distinct
    objects -- reset is object construction, not a shared mutable teardown."""
    a = CreditEnvState(
        episode_key=_key(),
        applicant=golden_clean_applicant,
        policy=policy,
        application_text="stub",
        applicant_ref=golden_clean_applicant.applicant_id,
        render_mode=RenderMode.TABLE,
    )
    b = CreditEnvState(
        episode_key=_key(),
        applicant=golden_clean_applicant,
        policy=policy,
        application_text="stub",
        applicant_ref=golden_clean_applicant.applicant_id,
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
        episode_key=_key(),
        applicant=golden_clean_applicant,
        policy=policy,
        application_text="stub",
        applicant_ref="x",
        render_mode=RenderMode.TABLE,
    )
    with pytest.raises(ValidationError):
        state.step = 5  # type: ignore[misc]


def test_fingerprint_excludes_application_text_and_policy(golden_clean_applicant, policy):
    """The fingerprint is a deliberate projection -- application_text and the full policy
    document must not affect it, since thousands of episodes share the same policy."""
    state_a = CreditEnvState(
        episode_key=_key(),
        applicant=golden_clean_applicant,
        policy=policy,
        application_text="text A",
        applicant_ref="x",
        render_mode=RenderMode.TABLE,
    )
    state_b = state_a.model_copy(update={"application_text": "completely different text"})
    assert state_fingerprint(state_a) == state_fingerprint(state_b)


def test_fingerprint_changes_with_tools_called(golden_clean_applicant, policy):
    state_a = CreditEnvState(
        episode_key=_key(),
        applicant=golden_clean_applicant,
        policy=policy,
        application_text="stub",
        applicant_ref="x",
        render_mode=RenderMode.TABLE,
    )
    state_b = state_a.model_copy(update={"tools_called": ("get_application",), "step": 1})
    assert state_fingerprint(state_a) != state_fingerprint(state_b)

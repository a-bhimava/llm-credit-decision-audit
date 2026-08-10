"""Every renderer, every committed profile, every render mode: no out-of-scope substring
ever appears. This is the Phase 3 replacement for the temporary render_stub fixture's own
leak test (tests/unit/env/test_render_stub.py) -- same guarantee, now checked against the
three real renderers instead of a placeholder."""

from __future__ import annotations

import pytest

from credit_audit.policy.loader import load_policy
from credit_audit.profiles.generate import read_profiles_jsonl
from credit_audit.render.registry import RENDERERS
from credit_audit.types import RenderMode

FORBIDDEN_SUBSTRINGS = ("property", "collateral", "cltv", "loan-to-value", "appraised")


@pytest.fixture(scope="module")
def profiles():
    return read_profiles_jsonl()


@pytest.fixture(scope="module")
def policy():
    return load_policy()


@pytest.mark.parametrize("mode", list(RenderMode))
def test_no_out_of_scope_substrings(profiles, policy, mode):
    renderer = RENDERERS[mode]
    for applicant in profiles:
        text = renderer(applicant, mode, policy).lower()
        for forbidden in FORBIDDEN_SUBSTRINGS:
            assert forbidden not in text, (
                f"{mode.value} render of {applicant.applicant_id} leaked {forbidden!r}"
            )


@pytest.mark.parametrize("mode", [RenderMode.PROSE, RenderMode.JSON])
def test_hand_authored_renderers_raise_loudly_on_field_set_drift(profiles, policy, mode):
    """table.py iterates policy.renderable_fields directly, so it adapts automatically.
    prose.py/json_.py are hand-authored text and cannot -- they must instead raise loudly
    the moment policy.renderable_fields no longer matches what they were written against,
    rather than silently continuing to show (or silently continuing to omit) a field."""
    mutated_fields = dict(policy.fields)
    mutated_fields["credit_score"] = mutated_fields["credit_score"].model_copy(
        update={"renderable": False}
    )
    mutated_policy = policy.model_copy(update={"fields": mutated_fields})

    with pytest.raises(RuntimeError, match="renderable_fields"):
        RENDERERS[mode](profiles[0], mode, mutated_policy)


def test_table_renderer_adapts_instead_of_raising(profiles, policy):
    """The contrast case: table.py genuinely iterates the registry, so the same mutation
    that must make prose/json raise should instead just change table's output."""
    mutated_fields = dict(policy.fields)
    mutated_fields["credit_score"] = mutated_fields["credit_score"].model_copy(
        update={"renderable": False}
    )
    mutated_policy = policy.model_copy(update={"fields": mutated_fields})

    text = RENDERERS[RenderMode.TABLE](profiles[0], RenderMode.TABLE, mutated_policy)
    assert "credit score" not in text.lower()


@pytest.mark.parametrize("mode", [RenderMode.TABLE, RenderMode.PROSE, RenderMode.JSON])
def test_renderer_rejects_the_wrong_mode(profiles, policy, mode):
    """F15: renderers used to enforce their own mode via a bare `assert`, stripped under
    `python -O`. Now an explicit ValueError -- verify it actually fires."""
    wrong_mode = next(m for m in RenderMode if m is not mode)
    with pytest.raises(ValueError, match="RenderMode"):
        RENDERERS[mode](profiles[0], wrong_mode, policy)

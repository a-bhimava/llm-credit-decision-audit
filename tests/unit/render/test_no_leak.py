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

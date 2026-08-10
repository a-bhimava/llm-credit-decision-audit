"""The applicant reference is derived once (render/reference.py) and must appear verbatim
in all three renders -- resolving the design gap Phase 2's _fetch_credit_report docstring
deferred to Phase 3."""

from __future__ import annotations

from credit_audit.policy.loader import load_policy
from credit_audit.profiles.generate import read_profiles_jsonl
from credit_audit.render.reference import applicant_reference, applicant_reference_for
from credit_audit.render.registry import RENDERERS
from credit_audit.types import RenderMode


def test_reference_is_deterministic_and_matches_format():
    ref1 = applicant_reference("APP-A-00001")
    ref2 = applicant_reference("APP-A-00001")
    assert ref1 == ref2
    assert ref1.startswith("MPL-")
    assert len(ref1) == len("MPL-") + 10


def test_reference_differs_across_applicants():
    assert applicant_reference("APP-A-00001") != applicant_reference("APP-A-00002")


def test_reference_appears_in_all_three_renders():
    policy = load_policy()
    for applicant in read_profiles_jsonl()[:15]:
        ref = applicant_reference_for(applicant)
        for mode in RenderMode:
            text = RENDERERS[mode](applicant, mode, policy)
            assert ref in text, (
                f"{mode.value} render of {applicant.applicant_id} missing reference {ref}"
            )

"""One integration test proving the pieces actually compose: a real committed Phase 3
profile, rendered by a real Phase 3 renderer (not the conftest.py stub every other
golden/env test deliberately uses for isolation), run through a full episode against a
real Phase 2 scripted agent.

Before this test, nothing in the suite ever exercised this combination -- every episode
and golden test renders via ``render_stub``, and render/'s own unit tests call renderers
directly without ever starting an episode. Both halves were tested; the seam between them
wasn't.
"""

from __future__ import annotations

import asyncio

from credit_audit.env.episode import run_episode
from credit_audit.model.scripted import FaithfulAgent
from credit_audit.policy.loader import load_policy
from credit_audit.policy.oracle import evaluate
from credit_audit.profiles.generate import read_profiles_jsonl
from credit_audit.render.reference import applicant_reference_for
from credit_audit.render.registry import RENDERERS
from credit_audit.types import DecisionOutcome, EpisodeKey, RenderMode, Termination


def _key(applicant_id: str, render_id: RenderMode) -> EpisodeKey:
    return EpisodeKey(
        applicant_id=applicant_id,
        arm_id="control",
        render_id=render_id,
        trial_index=0,
        model_id="scripted:faithful",
        prompt_hash="stub",
        seed=1,
    )


def test_faithful_agent_full_episode_against_a_real_renderer():
    policy = load_policy()
    applicant = read_profiles_jsonl()[0]
    render_mode = RenderMode.TABLE
    application_text = RENDERERS[render_mode](applicant, render_mode, policy)

    # The render actually happened and carries this applicant's real reference -- not a
    # stub string standing in for it.
    assert applicant_reference_for(applicant) in application_text

    key = _key(applicant.applicant_id, render_mode)
    traj = asyncio.run(
        run_episode(
            key=key,
            applicant=applicant,
            policy=policy,
            application_text=application_text,
            applicant_ref=applicant.applicant_id,
            client=FaithfulAgent(),
            reason_mode="coded",
        )
    )

    assert traj.termination == Termination.SUBMITTED
    assert traj.decision is not None
    tool_names = [tc.name for tc in traj.tool_calls]
    assert tool_names[:2] == ["get_application", "fetch_credit_report"]
    assert tool_names[-1] == "submit_decision"
    assert all(tc.ok for tc in traj.tool_calls)

    # FaithfulAgent's decision must agree with the real oracle for this real profile --
    # the whole point of the positive control, now checked against a real render rather
    # than the stub.
    ground_truth = evaluate(applicant.facts, policy)
    assert traj.decision.outcome == ground_truth.outcome
    if ground_truth.outcome is DecisionOutcome.DENY:
        stated_codes = {r.code for r in traj.decision.stated_reasons}
        assert stated_codes <= set(ground_truth.breached_codes)


def test_prose_and_json_renders_also_compose_with_a_real_episode():
    """Not just table -- the other two real renderers must also work as episode input."""
    policy = load_policy()
    applicant = read_profiles_jsonl()[1]

    for render_mode in (RenderMode.PROSE, RenderMode.JSON):
        application_text = RENDERERS[render_mode](applicant, render_mode, policy)
        key = _key(applicant.applicant_id, render_mode)
        traj = asyncio.run(
            run_episode(
                key=key,
                applicant=applicant,
                policy=policy,
                application_text=application_text,
                applicant_ref=applicant.applicant_id,
                client=FaithfulAgent(),
                reason_mode="coded",
            )
        )
        assert traj.termination == Termination.SUBMITTED
        assert traj.decision is not None

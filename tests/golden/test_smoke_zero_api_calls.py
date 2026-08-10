"""Direct substitute for `credit-audit run --suite smoke --model scripted` (Phase 8's CLI
doesn't exist yet): proves the same property -- trajectories produced, zero API calls --
by driving run_episode() directly for every scripted agent, both reason modes, and every
render-mode label.
"""

from __future__ import annotations

import asyncio

from credit_audit.env.episode import run_episode
from credit_audit.model.scripted import (
    BiasedAgent,
    FaithfulAgent,
    FormatSensitiveAgent,
    LaunderingAgent,
    MalformedAgent,
    NonMonotoneAgent,
    OmittingAgent,
    OutOfSchemaAgent,
    RefusingAgent,
    StochasticAgent,
    VagueAgent,
)
from credit_audit.types import EpisodeKey, RenderMode


def _agents():
    return [
        FaithfulAgent(),
        LaunderingAgent(),
        OmittingAgent(),
        VagueAgent(),
        OutOfSchemaAgent(),
        NonMonotoneAgent(),
        FormatSensitiveAgent(),
        BiasedAgent(),
        StochasticAgent(0.3),
        RefusingAgent(),
        MalformedAgent(),
    ]


def test_smoke_suite_scripted_zero_api_calls(golden_clean_applicant, policy, render_stub):
    agents = _agents()
    trajectories = []
    for agent in agents:
        for reason_mode in ("coded", "freetext"):
            for render_mode in (RenderMode.TABLE, RenderMode.PROSE, RenderMode.JSON):
                key = EpisodeKey(
                    applicant_id=golden_clean_applicant.applicant_id,
                    arm_id="smoke",
                    render_id=render_mode,
                    trial_index=0,
                    model_id=agent.model_id,
                    prompt_hash="stub",
                    seed=1729,
                )
                text = render_stub(golden_clean_applicant, render_mode, policy)
                traj = asyncio.run(
                    run_episode(
                        key=key,
                        applicant=golden_clean_applicant,
                        policy=policy,
                        application_text=text,
                        applicant_ref=golden_clean_applicant.applicant_id,
                        client=agent,
                        reason_mode=reason_mode,
                    )
                )
                trajectories.append(traj)

    assert len(trajectories) == len(agents) * 2 * 3
    assert all(t.usage.cost_usd == 0.0 for t in trajectories)
    assert all(t.usage.input_tokens == 0 for t in trajectories)
    assert all(t.usage.output_tokens == 0 for t in trajectories)
    assert all(t.termination is not None for t in trajectories)
    assert all(t.trajectory_id for t in trajectories)

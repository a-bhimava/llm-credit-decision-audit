"""Direct substitute for `credit-audit run --suite smoke --model scripted` (Phase 8's CLI
doesn't exist yet): proves the same property -- trajectories produced, zero API calls --
by driving run_episode() directly for every scripted agent, both reason modes, and every
render-mode label.
"""

from __future__ import annotations

import asyncio

from credit_audit.env.episode import build_episode_key, run_episode
from credit_audit.model.scripted import (
    BiasedAgent,
    DemographicSignalAgent,
    FaithfulAgent,
    FormatSensitiveAgent,
    LaunderingAgent,
    MalformedAgent,
    NonMonotoneAgent,
    OmittingAgent,
    OrderSensitiveAgent,
    OutOfSchemaAgent,
    OverReasonAgent,
    ParaphraseSensitiveAgent,
    ProhibitedReasonAgent,
    RefusingAgent,
    ShortcutAgent,
    StochasticAgent,
    TrapAgent,
    VagueAgent,
    WrongDecisionAgent,
)
from credit_audit.types import RenderMode


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
        OrderSensitiveAgent(),
        ParaphraseSensitiveAgent(),
        DemographicSignalAgent(),
        ShortcutAgent(),
        TrapAgent(),
        ProhibitedReasonAgent(),
        OverReasonAgent(),
        WrongDecisionAgent(),
        StochasticAgent(0.3),
        RefusingAgent(),
        MalformedAgent(),
    ]


def test_smoke_suite_scripted_zero_api_calls(golden_clean_applicant, policy):
    agents = _agents()
    trajectories = []
    for agent in agents:
        for reason_mode in ("coded", "freetext"):
            for render_mode in (RenderMode.TABLE, RenderMode.PROSE, RenderMode.JSON):
                key = build_episode_key(
                    applicant=golden_clean_applicant,
                    arm_id="smoke",
                    render_id=render_mode,
                    trial_index=0,
                    model_id=agent.model_id,
                    policy=policy,
                    reason_mode=reason_mode,
                    seed=1729,
                )
                traj = asyncio.run(
                    run_episode(
                        key=key,
                        applicant=golden_clean_applicant,
                        policy=policy,
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

"""One execution path for every zero-API-call check.

The runner centralizes canonical episode identity, rendering, and paired seed semantics.
Corresponding arms use the same trial seed (common random numbers), while ``arm_id``
remains part of :class:`~credit_audit.types.EpisodeKey` so episode and cache identities
cannot collide.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from credit_audit.env.episode import build_episode_key, run_episode
from credit_audit.env.tools import ReasonMode
from credit_audit.ids import derive_seed
from credit_audit.model.client import ModelClient
from credit_audit.policy.loader import Policy
from credit_audit.render.registry import render_application
from credit_audit.types import Applicant, RenderMode, Trajectory

if TYPE_CHECKING:
    from credit_audit.interventions.apply import ArmPlan
    from credit_audit.render.packet import RenderOptions


def paired_trial_seed(
    run_seed: int,
    seed_group: str,
    trial_index: int,
) -> int:
    """Derive a seed shared by the two corresponding arms of one contrast."""

    return derive_seed(run_seed, seed_group, trial_index)


async def run_trials(
    *,
    applicant: Applicant,
    client: ModelClient,
    policy: Policy,
    render_mode: RenderMode,
    run_seed: int,
    seed_group: str,
    arm_id: str,
    k_trials: int,
    reason_mode: ReasonMode = "coded",
    render_options: RenderOptions | None = None,
) -> tuple[Trajectory, ...]:
    """Render and execute ``k_trials`` through the canonical episode protocol."""

    if k_trials < 1:
        raise ValueError("k_trials must be at least 1")
    application_text = render_application(
        applicant,
        render_mode,
        policy,
        options=render_options,
    )
    trajectories: list[Trajectory] = []
    for trial_index in range(k_trials):
        seed = paired_trial_seed(
            run_seed,
            seed_group,
            trial_index,
        )
        key = build_episode_key(
            applicant=applicant,
            arm_id=arm_id,
            render_id=render_mode,
            trial_index=trial_index,
            model_id=client.model_id,
            policy=policy,
            reason_mode=reason_mode,
            seed=seed,
            render_options=render_options,
        )
        trajectories.append(
            await run_episode(
                key=key,
                applicant=applicant,
                policy=policy,
                application_text=application_text,
                client=client,
                reason_mode=reason_mode,
                render_options=render_options,
            )
        )
    return tuple(trajectories)


async def run_arm_trials(
    *,
    arm: ArmPlan,
    client: ModelClient,
    policy: Policy,
    run_seed: int,
    seed_group: str,
    k_trials: int,
    reason_mode: ReasonMode = "coded",
) -> tuple[Trajectory, ...]:
    """Materialize an immutable arm plan and execute it through :func:`run_trials`."""

    materialized = arm.materialize()
    return await run_trials(
        applicant=materialized.applicant,
        client=client,
        policy=policy,
        render_mode=arm.render_mode,
        run_seed=run_seed,
        seed_group=seed_group,
        arm_id=arm.arm_id,
        k_trials=k_trials,
        reason_mode=reason_mode,
        render_options=materialized.render_options,
    )


__all__ = ["paired_trial_seed", "run_arm_trials", "run_trials"]

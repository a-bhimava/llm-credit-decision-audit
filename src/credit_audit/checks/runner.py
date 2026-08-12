"""One execution path for every zero-API-call check.

The runner centralizes canonical episode identity, rendering, and paired seed semantics.
Corresponding arms use the same trial seed (common random numbers), while ``arm_id``
remains part of :class:`~credit_audit.types.EpisodeKey` so episode and cache identities
cannot collide.

Because this is the single execution path, it is also where executed evidence is recorded. A
run needs every trajectory to export pair detail and to let ``verify`` re-derive statistics
from raw evidence, but the checks layer's job is to return scored results, not to carry an
output parameter for one caller's benefit. :func:`recording_trajectories` installs a sink for
the duration of a run instead, so no check signature changes and nothing can be executed
through this module without being recorded.

The sink receives the **materialized applicant** alongside the trajectory. An arm's applicant
is constructed here from its plan and then exists nowhere else; without capturing it at this
point the exporter could not show which single field a contrast changed, which is the entire
content of the pair viewer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
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

TrajectorySink = Callable[[Trajectory, Applicant], None]

_RECORDER: ContextVar[TrajectorySink | None] = ContextVar(
    "credit_audit_trajectory_recorder", default=None
)


@contextmanager
def recording_trajectories(sink: TrajectorySink) -> Iterator[None]:
    """Record every trajectory executed inside this block, with its materialized applicant.

    A :class:`~contextvars.ContextVar` rather than a module global: it is correct under
    ``asyncio`` and cannot leak a sink from one run into another. Nesting is supported and the
    previous sink is restored on exit, including on exception.
    """

    token = _RECORDER.set(sink)
    try:
        yield
    finally:
        _RECORDER.reset(token)


def _record(trajectory: Trajectory, applicant: Applicant) -> Trajectory:
    sink = _RECORDER.get()
    if sink is not None:
        sink(trajectory, applicant)
    return trajectory


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
            _record(
                await run_episode(
                    key=key,
                    applicant=applicant,
                    policy=policy,
                    application_text=application_text,
                    client=client,
                    reason_mode=reason_mode,
                    render_options=render_options,
                ),
                applicant,
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


__all__ = [
    "TrajectorySink",
    "paired_trial_seed",
    "recording_trajectories",
    "run_arm_trials",
    "run_trials",
]

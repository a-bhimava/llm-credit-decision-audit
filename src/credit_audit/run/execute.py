"""Execute a suite and persist raw evidence.

The output of a run is three files under ``runs/<run_id>/``: every trajectory, every scored
result, and the manifest tying them to the code, policy, profiles, and preregistration that
produced them. The exporter reads only those files, and ``verify`` re-derives every published
statistic from them. Nothing downstream re-executes an episode, so the raw artifacts are the
single source of truth for the run.

``run_id`` is content-addressed over the *experiment definition* -- suite, model, seed, k,
reason mode, render mode, and the hashes of the policy, profiles, and preregistration. It
deliberately excludes the git commit: the same experiment must land at the same bundle path
across commits, or the site would accumulate a new run directory on every push. The commit is
recorded inside the manifest, where it belongs, as provenance rather than identity.
"""

from __future__ import annotations

import platform
from datetime import datetime
from pathlib import Path
from typing import Literal

from credit_audit.checks.counterfactual_bias import run_counterfactual_bias_checks
from credit_audit.checks.invariance import run_invariance_checks
from credit_audit.checks.monotonicity import run_monotonicity_check
from credit_audit.checks.policy_adherence import run_policy_adherence_check
from credit_audit.checks.reason_validity import run_reason_validity_check
from credit_audit.checks.runner import recording_trajectories
from credit_audit.checks.serialization import run_serialization_checks
from credit_audit.ids import sha256_file, short_id
from credit_audit.io.jsonl import write_json, write_records
from credit_audit.model.client import ModelClient
from credit_audit.policy.loader import Policy
from credit_audit.policy.oracle import evaluate
from credit_audit.profiles.generate import PROFILES_PATH, read_profiles_jsonl
from credit_audit.run.budget import Budget, BudgetExceeded, BudgetState
from credit_audit.run.gitmeta import GitMetadata, git_metadata, run_timestamp
from credit_audit.run.plan import RunPlan, build_run_plan
from credit_audit.stats.families import Preregistration, load_preregistration
from credit_audit.suites.loader import Family, Selection, Suite, load_suite
from credit_audit.types import (
    Applicant,
    CostSummary,
    DatasetRef,
    DecisionOutcome,
    Frozen,
    FrozenDict,
    ModelSpec,
    PolicyRef,
    PreregRef,
    RunCounts,
    RunManifest,
    TestResult,
    TestStatus,
    Trajectory,
)

TRAJECTORIES_FILE = "trajectories.jsonl"
RESULTS_FILE = "results.jsonl"
APPLICANTS_FILE = "applicants.jsonl"
MANIFEST_FILE = "manifest.json"

DEFAULT_RUNS_DIR = Path("runs")

RunKind = Literal["scripted", "model"]


class RunOutcome(Frozen):
    run_id: str
    run_dir: Path
    manifest: RunManifest
    plan: RunPlan
    budget: BudgetState
    n_trajectories: int
    n_results: int
    aborted: bool = False
    abort_reason: str = ""


def select_applicants(
    suite: Suite,
    policy: Policy,
    profiles: tuple[Applicant, ...] | None = None,
) -> tuple[Applicant, ...]:
    """Stable sort by ``applicant_id``, filter, then head.

    Never a random sample. Adding profile #226 must not change which applicants a ``limit: 24``
    suite drew, or two runs of the same suite are not comparable.
    """

    population = profiles if profiles is not None else read_profiles_jsonl()
    ordered = sorted(population, key=lambda applicant: applicant.applicant_id)

    if suite.applicants.select is Selection.DENIED:
        ordered = [
            a for a in ordered if evaluate(a.facts, policy).outcome is not DecisionOutcome.APPROVE
        ]
    elif suite.applicants.select is Selection.APPROVED:
        ordered = [
            a for a in ordered if evaluate(a.facts, policy).outcome is DecisionOutcome.APPROVE
        ]

    if suite.applicants.limit is not None:
        ordered = ordered[: suite.applicants.limit]
    if not ordered:
        raise ValueError(
            f"suite {suite.name!r} selected no applicants from a population of {len(population)}"
        )
    return tuple(ordered)


def compute_run_id(
    suite: Suite,
    *,
    model_id: str,
    seed: int,
    profiles_sha256: str,
    policy: Policy,
    prereg: Preregistration,
) -> str:
    return "run_" + short_id(
        {
            "suite": suite.name,
            "suite_sha256": suite.sha256,
            "model_id": model_id,
            "seed": seed,
            "k_trials": suite.k_trials,
            "reason_mode": suite.reason_mode,
            "render_mode": str(suite.render_mode),
            "families": [str(family) for family in suite.families],
            "profiles_sha256": profiles_sha256,
            "policy_md_sha256": policy.md_sha256,
            "policy_yaml_sha256": policy.yaml_sha256,
            "prereg_sha256": prereg.sha256,
        },
        length=12,
    )


async def _run_family(
    family: Family,
    applicant: Applicant,
    *,
    client: ModelClient,
    policy: Policy,
    suite: Suite,
    run_seed: int,
) -> tuple[TestResult, ...]:
    k = suite.k_trials
    mode = suite.reason_mode
    if family is Family.POLICY_ADHERENCE:
        return await run_policy_adherence_check(
            applicant, client, policy, suite.render_mode, run_seed, k_trials=k, reason_mode=mode
        )
    if family is Family.MONOTONICITY:
        return await run_monotonicity_check(
            applicant,
            client,
            policy,
            run_seed,
            render_mode=suite.render_mode,
            k_trials=k,
            reason_mode=mode,
            include_analytic_income_fixture=True,
        )
    if family is Family.INVARIANCE:
        return await run_invariance_checks(
            applicant, client, policy, run_seed=run_seed, k_trials=k, reason_mode=mode
        )
    if family is Family.SERIALIZATION:
        return await run_serialization_checks(
            applicant, client, policy, run_seed=run_seed, k_trials=k, reason_mode=mode
        )
    if family is Family.COUNTERFACTUAL_BIAS:
        return await run_counterfactual_bias_checks(
            applicant, client, policy, run_seed=run_seed, k_trials=k, reason_mode=mode
        )
    if family is Family.REASON_VALIDITY:
        return await run_reason_validity_check(
            applicant, client, policy, suite.render_mode, run_seed, k_trials=k, reason_mode=mode
        )
    raise AssertionError(f"unhandled family: {family}")  # pragma: no cover


def _build_manifest(
    *,
    run_id: str,
    suite: Suite,
    client: ModelClient,
    kind: RunKind,
    provider: str,
    policy: Policy,
    prereg: Preregistration,
    git: GitMetadata,
    created_at: datetime,
    seed: int,
    applicants: tuple[Applicant, ...],
    profiles_sha256: str,
    results: tuple[TestResult, ...],
    trajectories: tuple[Trajectory, ...],
    budget: BudgetState,
    plan: RunPlan,
) -> RunManifest:
    denied = sum(
        1
        for applicant in applicants
        if evaluate(applicant.facts, policy).outcome is not DecisionOutcome.APPROVE
    )
    pairs = len({result.pair_id for result in results})
    arms = sorted({trajectory.key.arm_id for trajectory in trajectories})

    return RunManifest(
        run_id=run_id,
        created_at=created_at,
        suite=suite.name,
        kind=kind,
        git_commit=git.commit,
        git_dirty=git.dirty,
        package_version=_package_version(),
        python_version=platform.python_version(),
        platform=platform.platform(terse=True),
        model=ModelSpec(
            provider=provider,
            model_id=client.model_id,
            max_steps=12,
            reason_mode=suite.reason_mode,
        ),
        seed=seed,
        profile_set=DatasetRef(
            path=_repo_relative(PROFILES_PATH),
            sha256=profiles_sha256,
            n=len(applicants),
        ),
        policy_ref=PolicyRef(
            md_sha256=policy.md_sha256,
            yaml_sha256=policy.yaml_sha256,
            version=policy.version,
        ),
        prereg_ref=PreregRef(
            sha256=prereg.sha256,
            git_tag=prereg.git_tag,
            frozen_at=None,
        ),
        arms=tuple(arms),
        renders=(suite.render_mode,),
        k_trials=suite.k_trials,
        counts=RunCounts(
            planned=plan.episodes_max,
            executed=budget.episodes,
            cached=budget.cache_hits,
            replayed=budget.replayed,
            skipped=max(0, plan.episodes_max - budget.episodes),
            applicants=len(applicants),
            denied=denied,
            tests=len(results),
            pairs=pairs,
        ),
        cost=CostSummary(
            usd_total=budget.usd,
            input_tokens=budget.input_tokens,
            output_tokens=budget.output_tokens,
            cached_tokens=budget.cached_tokens,
            thought_tokens=budget.thought_tokens,
            cache_hits=budget.cache_hits,
            replayed_responses=budget.replayed,
            cache_hit_rate=(budget.cache_hits / budget.episodes if budget.episodes else None),
            current_run_cost=True,
        ),
        artifacts=FrozenDict({}),
    )


def _package_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("llm-credit-decision-audit")
    except PackageNotFoundError:  # pragma: no cover - source checkout without an install
        return "0.0.0+unknown"


def _repo_relative(path: Path) -> str:
    root = Path(__file__).resolve().parents[3]
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - installed outside the source tree
        return path.name


async def execute_run(
    *,
    suite: Suite | str,
    client: ModelClient,
    policy: Policy,
    seed: int,
    kind: RunKind = "scripted",
    provider: str = "scripted",
    runs_dir: Path = DEFAULT_RUNS_DIR,
    profiles: tuple[Applicant, ...] | None = None,
    prereg: Preregistration | None = None,
    git: GitMetadata | None = None,
    stamp_now: bool = False,
) -> RunOutcome:
    """Execute a suite end to end and write its raw artifacts.

    ``kind`` is supplied by the caller rather than sniffed from the client. The scripted /
    model distinction drives a non-dismissible banner on every route of the evidence site and
    a hard export lint, so it is declared at the call site where someone chose it, not
    inferred from a duck-typed attribute a future adapter might forget to set.

    A budget overrun is not an exception the caller has to handle: the partial evidence is
    persisted and the outcome reports ``aborted`` with the reason. A run that stopped early
    is still evidence, and throwing it away would be the wrong trade every time.
    """

    suite = load_suite(suite) if isinstance(suite, str) else suite
    prereg = prereg or load_preregistration()
    git = git or git_metadata()
    created_at, deterministic = run_timestamp(git, stamp_now=stamp_now)

    applicants = select_applicants(suite, policy, profiles)
    profiles_sha256 = sha256_file(PROFILES_PATH)
    run_id = compute_run_id(
        suite,
        model_id=client.model_id,
        seed=seed,
        profiles_sha256=profiles_sha256,
        policy=policy,
        prereg=prereg,
    )
    plan = build_run_plan(suite, applicants, policy)

    budget = Budget(suite.caps)
    budget.admit(plan.episodes_max)

    trajectories: dict[str, Trajectory] = {}
    variants: dict[str, Applicant] = {}
    results: list[TestResult] = []
    aborted = False
    abort_reason = ""

    def sink(trajectory: Trajectory, applicant: Applicant) -> None:
        existing = trajectories.get(trajectory.episode_id)
        if existing is not None and existing.trajectory_id != trajectory.trajectory_id:
            # Two executions claimed one episode identity and disagreed about what happened.
            # That is an identity bug, not a duplicate to silently drop.
            raise ValueError(
                f"episode {trajectory.episode_id} was executed twice with different "
                f"trajectories ({existing.trajectory_id} vs {trajectory.trajectory_id})"
            )
        trajectories[trajectory.episode_id] = trajectory
        # Deduped by content identity: an arm's applicant is identical across its k trials,
        # and matched arms of different contrasts often share one variant.
        variants.setdefault(trajectory.key.applicant_content_id, applicant)
        budget.charge(trajectory)

    try:
        with recording_trajectories(sink):
            for applicant in applicants:
                for family in suite.families:
                    results.extend(
                        await _run_family(
                            family,
                            applicant,
                            client=client,
                            policy=policy,
                            suite=suite,
                            run_seed=seed,
                        )
                    )
    except BudgetExceeded as exceeded:
        aborted = True
        abort_reason = str(exceeded)

    # Sorted by content identity, so the artifact is a function of what was executed rather
    # than of the order the checks happened to execute it in.
    ordered_trajectories = tuple(trajectories[key] for key in sorted(trajectories))
    ordered_results = tuple(
        sorted(results, key=lambda r: (r.check, r.applicant_id, r.pair_id, r.test_id))
    )
    ordered_variants = tuple(variants[key] for key in sorted(variants))

    manifest = _build_manifest(
        run_id=run_id,
        suite=suite,
        client=client,
        kind=kind,
        provider=provider,
        policy=policy,
        prereg=prereg,
        git=git,
        created_at=created_at,
        seed=seed,
        applicants=applicants,
        profiles_sha256=profiles_sha256,
        results=ordered_results,
        trajectories=ordered_trajectories,
        budget=budget.state(),
        plan=plan,
    )

    run_dir = Path(runs_dir) / run_id
    trajectories_path = run_dir / TRAJECTORIES_FILE
    results_path = run_dir / RESULTS_FILE
    applicants_path = run_dir / APPLICANTS_FILE
    write_records(trajectories_path, ordered_trajectories)
    write_records(results_path, ordered_results)
    write_records(applicants_path, ordered_variants)

    manifest = manifest.model_copy(
        update={
            "artifacts": FrozenDict(
                {
                    TRAJECTORIES_FILE: sha256_file(trajectories_path),
                    RESULTS_FILE: sha256_file(results_path),
                    APPLICANTS_FILE: sha256_file(applicants_path),
                }
            )
        }
    )
    write_json(run_dir / MANIFEST_FILE, _manifest_payload(manifest, deterministic=deterministic))

    return RunOutcome(
        run_id=run_id,
        run_dir=run_dir,
        manifest=manifest,
        plan=plan,
        budget=budget.state(),
        n_trajectories=len(ordered_trajectories),
        n_results=len(ordered_results),
        aborted=aborted,
        abort_reason=abort_reason,
    )


def _manifest_payload(manifest: RunManifest, *, deterministic: bool) -> dict:
    """Persist the manifest plus the run-time determinism flag the exporter carries forward."""

    payload = manifest.model_dump(mode="json")
    payload["deterministic"] = deterministic
    return payload


def load_run_manifest(run_dir: Path) -> tuple[RunManifest, bool]:
    """Read a persisted manifest back, returning it with its determinism flag."""

    import json

    payload = json.loads((Path(run_dir) / MANIFEST_FILE).read_text(encoding="utf-8"))
    deterministic = bool(payload.pop("deterministic", True))
    return RunManifest.model_validate(payload), deterministic


def load_run_results(run_dir: Path) -> tuple[TestResult, ...]:
    from credit_audit.io.jsonl import read_models

    return tuple(read_models(Path(run_dir) / RESULTS_FILE, TestResult))


def load_run_trajectories(run_dir: Path) -> tuple[Trajectory, ...]:
    from credit_audit.io.jsonl import read_models

    return tuple(read_models(Path(run_dir) / TRAJECTORIES_FILE, Trajectory))


def load_run_applicants(run_dir: Path) -> dict[str, Applicant]:
    """Materialized arm applicants, keyed by content identity."""

    from credit_audit.ids import applicant_content_id
    from credit_audit.io.jsonl import read_models

    return {
        applicant_content_id(applicant): applicant
        for applicant in read_models(Path(run_dir) / APPLICANTS_FILE, Applicant)
    }


def status_counts(results: tuple[TestResult, ...]) -> dict[str, int]:
    counts = {status.value: 0 for status in TestStatus}
    for result in results:
        counts[result.status.value] += 1
    return counts


__all__ = [
    "APPLICANTS_FILE",
    "MANIFEST_FILE",
    "RESULTS_FILE",
    "TRAJECTORIES_FILE",
    "RunOutcome",
    "compute_run_id",
    "execute_run",
    "load_run_applicants",
    "load_run_manifest",
    "load_run_results",
    "load_run_trajectories",
    "select_applicants",
    "status_counts",
]

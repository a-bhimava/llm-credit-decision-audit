"""The known-answer sweep: every scripted control, over one shared cohort.

A normal run has one client, so it can show that *this* agent behaved. The planted-defect
table needs the whole known-answer argument in one artifact: each control caught at the rate
its rule implies, and — just as important — firing nothing else.

The cohort is **stratified, not sampled**. Several defects are only expressible where their
trigger exists: the authority penalty only crosses a decision boundary for applicants sitting
just above the credit-score cut, and the omission scan needs denials with several binding
breaches. A cohort drawn at random would silently fail to contain them and the table would
report MISSED for a harness that was working.

The sweep is itself a run, with its own content-addressed id, so the exported table can name
one ``source_run_id`` and a later model run can point back at it.
"""

from __future__ import annotations

from pathlib import Path

from credit_audit.checks.counterfactual_bias import select_authority_boundary_cohort
from credit_audit.ids import sha256_file, short_id
from credit_audit.io.jsonl import write_json, write_records
from credit_audit.model.expectations import CONTROLS, AgentExpectation
from credit_audit.policy.loader import Policy
from credit_audit.policy.oracle import evaluate
from credit_audit.profiles.generate import PROFILES_PATH, read_profiles_jsonl
from credit_audit.run.execute import (
    MANIFEST_FILE,
    RunKind,
    _build_manifest,
    _run_family,
)
from credit_audit.run.gitmeta import GitMetadata, git_metadata, run_timestamp
from credit_audit.run.plan import build_run_plan
from credit_audit.stats.families import Preregistration, load_preregistration
from credit_audit.suites.loader import Suite, load_suite
from credit_audit.types import Applicant, DecisionOutcome, Frozen, FrozenDict, TestResult

SWEEP_DIR = "agents"
SWEEP_MODEL_ID = "scripted:sweep"

DEFAULT_SWEEP_SUITE = "core"
"""The sweep takes its *families* from the suite and its applicants from the stratified
cohort, so it needs a suite that runs every family. A three-family suite would leave most
expectations with nothing to evaluate and report them as unproven — which is exactly the
failure this default exists to prevent."""

DEFAULT_APPROVED = 3
DEFAULT_MULTI_BREACH = 3


class SweepOutcome(Frozen):
    run_id: str
    run_dir: Path
    cohort: tuple[str, ...]
    agents: tuple[str, ...]
    n_results: int
    n_episodes: int


def build_sweep_cohort(
    policy: Policy,
    profiles: tuple[Applicant, ...] | None = None,
    *,
    n_approved: int = DEFAULT_APPROVED,
    n_multi_breach: int = DEFAULT_MULTI_BREACH,
) -> tuple[Applicant, ...]:
    """A deterministic stratified cohort covering every declared trigger condition.

    Every stratum is filled by stable sort and head, never by sampling, so adding profile #226
    cannot change which applicants a previous sweep used.
    """

    population = profiles if profiles is not None else read_profiles_jsonl()
    ordered = sorted(population, key=lambda applicant: applicant.applicant_id)

    approved: list[Applicant] = []
    multi_breach: list[Applicant] = []
    for applicant in ordered:
        decision = evaluate(applicant.facts, policy)
        if decision.outcome is DecisionOutcome.APPROVE:
            if len(approved) < n_approved:
                approved.append(applicant)
        elif len(set(decision.breached_codes)) >= 2 and len(multi_breach) < n_multi_breach:
            multi_breach.append(applicant)

    # Rare and non-negotiable: without it the authority expectation has no stratum at all.
    boundary = list(select_authority_boundary_cohort(tuple(ordered), policy))

    selected = {a.applicant_id: a for a in (*approved, *multi_breach, *boundary)}
    cohort = tuple(selected[key] for key in sorted(selected))
    if not cohort:
        raise ValueError("sweep cohort is empty; the committed profile set cannot be right")
    return cohort


def compute_sweep_id(
    suite: Suite,
    *,
    seed: int,
    cohort: tuple[Applicant, ...],
    policy: Policy,
    prereg: Preregistration,
    agents: tuple[str, ...],
) -> str:
    return "sweep_" + short_id(
        {
            "suite": suite.name,
            "suite_sha256": suite.sha256,
            "seed": seed,
            "cohort": [applicant.applicant_id for applicant in cohort],
            "agents": list(agents),
            "policy_md_sha256": policy.md_sha256,
            "policy_yaml_sha256": policy.yaml_sha256,
            "prereg_sha256": prereg.sha256,
        },
        length=12,
    )


def agent_results_file(agent: str) -> str:
    return f"{SWEEP_DIR}/{agent.replace(':', '_')}.jsonl"


def _client_for(agent: str):
    from credit_audit.cli import build_client

    client, _kind, _provider = build_client(agent)
    return client


async def execute_sweep(
    *,
    suite: Suite | str = DEFAULT_SWEEP_SUITE,
    policy: Policy,
    seed: int,
    controls: tuple[AgentExpectation, ...] = CONTROLS,
    runs_dir: Path = Path("runs"),
    cohort: tuple[Applicant, ...] | None = None,
    prereg: Preregistration | None = None,
    git: GitMetadata | None = None,
    stamp_now: bool = False,
    kind: RunKind = "scripted",
) -> SweepOutcome:
    """Execute every declared control over one cohort and persist per-agent results."""

    from credit_audit.checks.runner import recording_trajectories

    suite = load_suite(suite) if isinstance(suite, str) else suite
    prereg = prereg or load_preregistration()
    git = git or git_metadata()
    created_at, deterministic = run_timestamp(git, stamp_now=stamp_now)
    cohort = cohort or build_sweep_cohort(policy)
    agents = tuple(control.agent for control in controls)

    run_id = compute_sweep_id(
        suite, seed=seed, cohort=cohort, policy=policy, prereg=prereg, agents=agents
    )
    run_dir = Path(runs_dir) / run_id

    total_episodes = 0
    total_results = 0
    artifacts: dict[str, str] = {}
    all_results: list[TestResult] = []

    for agent in agents:
        client = _client_for(agent)
        episodes: list[str] = []
        results: list[TestResult] = []

        def sink(trajectory, _applicant, _episodes=episodes) -> None:
            _episodes.append(trajectory.episode_id)

        with recording_trajectories(sink):
            for applicant in cohort:
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

        ordered = tuple(
            sorted(results, key=lambda r: (r.check, r.applicant_id, r.pair_id, r.test_id))
        )
        path = run_dir / agent_results_file(agent)
        write_records(path, ordered)
        artifacts[agent_results_file(agent)] = sha256_file(path)
        total_episodes += len(set(episodes))
        total_results += len(ordered)
        all_results.extend(ordered)

    plan = build_run_plan(suite, cohort, policy)
    manifest = _build_manifest(
        run_id=run_id,
        suite=suite,
        client=_client_for(agents[0]),
        kind=kind,
        provider="scripted",
        policy=policy,
        prereg=prereg,
        git=git,
        created_at=created_at,
        seed=seed,
        applicants=cohort,
        profiles_sha256=sha256_file(PROFILES_PATH),
        results=tuple(all_results),
        trajectories=(),
        budget=_zero_budget(total_episodes),
        plan=plan,
        # build_run_plan bounds *one* client over the cohort. A sweep executes every agent
        # over the same cohort, so the unscaled bound published `planned: 2265` beside
        # `executed: 31665` -- a strip built from those two numbers renders as nonsense.
        planned_override=plan.episodes_max * len(agents),
    )
    manifest = manifest.model_copy(
        update={
            "model": manifest.model.model_copy(update={"model_id": SWEEP_MODEL_ID}),
            "artifacts": FrozenDict(dict(sorted(artifacts.items()))),
        }
    )
    payload = manifest.model_dump(mode="json")
    payload["deterministic"] = deterministic
    payload["sweep"] = {"agents": list(agents), "cohort": [a.applicant_id for a in cohort]}
    write_json(run_dir / MANIFEST_FILE, payload)

    return SweepOutcome(
        run_id=run_id,
        run_dir=run_dir,
        cohort=tuple(applicant.applicant_id for applicant in cohort),
        agents=agents,
        n_results=total_results,
        n_episodes=total_episodes,
    )


def _zero_budget(episodes: int):
    from credit_audit.run.budget import BudgetState

    return BudgetState(episodes=episodes)


def load_sweep_manifest(run_dir: Path) -> tuple[dict, tuple[str, ...], tuple[str, ...]]:
    """Read a sweep manifest back, with the agent list and cohort it recorded."""

    import json

    payload = json.loads((Path(run_dir) / MANIFEST_FILE).read_text(encoding="utf-8"))
    sweep = payload.get("sweep") or {}
    return payload, tuple(sweep.get("agents", ())), tuple(sweep.get("cohort", ()))


def load_agent_results(run_dir: Path, agent: str) -> tuple[TestResult, ...]:
    from credit_audit.io.jsonl import read_models

    return tuple(read_models(Path(run_dir) / agent_results_file(agent), TestResult))


__all__ = [
    "DEFAULT_APPROVED",
    "DEFAULT_MULTI_BREACH",
    "SWEEP_DIR",
    "SWEEP_MODEL_ID",
    "SweepOutcome",
    "agent_results_file",
    "build_sweep_cohort",
    "compute_sweep_id",
    "execute_sweep",
    "load_agent_results",
    "load_sweep_manifest",
]

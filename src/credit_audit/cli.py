"""``credit-audit`` -- run, export, verify.

Three verbs, in the order a run actually happens. Deliberately built on ``argparse`` rather
than a CLI framework: this is a research harness and its dependency list is a claim about how
much of it a reader has to trust.

    credit-audit run    --suite core --model scripted --seed 1729
    credit-audit export --run <run_id>
    credit-audit verify --run <run_id> --strict
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from credit_audit.model.client import ModelClient
from credit_audit.policy.loader import load_policy
from credit_audit.report.bundle import ExportError
from credit_audit.report.export import DEFAULT_BUNDLE_ROOT, export_run
from credit_audit.report.verify import verify_bundle
from credit_audit.run.budget import BudgetExceeded
from credit_audit.run.execute import DEFAULT_RUNS_DIR, execute_run, select_applicants
from credit_audit.run.plan import build_run_plan, format_plan
from credit_audit.run.sweep import DEFAULT_SWEEP_SUITE
from credit_audit.suites.loader import SUITE_NAMES, load_suite

SCRIPTED_PREFIX = "scripted"


def _scripted_agents() -> dict[str, type]:
    """Every scripted control, keyed by the short name the CLI accepts."""

    import inspect

    from credit_audit.model import scripted

    agents: dict[str, type] = {}
    for name, obj in vars(scripted).items():
        if inspect.isclass(obj) and name.endswith("Agent") and obj.__module__ == scripted.__name__:
            short = _snake(name.removesuffix("Agent"))
            agents[short] = obj
    return agents


def _snake(name: str) -> str:
    out: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index:
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def build_client(spec: str) -> tuple[ModelClient, str, str]:
    """Resolve ``--model`` to a client, its kind, and its provider.

    ``scripted`` is the faithful control. ``scripted:<name>`` selects a specific planted-defect
    agent, which is how the known-answer validation table is produced. A real provider adapter
    is Phase 9, and asking for one here says so rather than failing obscurely.
    """

    if spec == SCRIPTED_PREFIX:
        spec = f"{SCRIPTED_PREFIX}:faithful"
    if not spec.startswith(f"{SCRIPTED_PREFIX}:"):
        raise SystemExit(
            f"unknown model {spec!r}. Only scripted agents exist today; provider adapters "
            "arrive in Phase 9. Try --model scripted, or --model scripted:<agent>."
        )
    short = spec.split(":", 1)[1]
    agents = _scripted_agents()
    factory = agents.get(short)
    if factory is None:
        raise SystemExit(
            f"unknown scripted agent {short!r}. Available: {', '.join(sorted(agents))}"
        )
    try:
        client = factory()
    except TypeError:
        # StochasticAgent takes a probability; its default exercises repeated-trial pairing.
        client = factory(0.3)
    return client, "scripted", "scripted"


def _run(args: argparse.Namespace) -> int:
    policy = load_policy()
    suite = load_suite(args.suite)
    client, kind, provider = build_client(args.model)

    if args.dry_run:
        applicants = select_applicants(suite, policy)
        print(format_plan(build_run_plan(suite, applicants, policy)))
        print(f"\n  model: {client.model_id} ({kind})")
        print(f"  seed:  {args.seed}")
        print("\nnothing was executed (--dry-run)")
        return 0

    try:
        outcome = asyncio.run(
            execute_run(
                suite=suite,
                client=client,
                policy=policy,
                seed=args.seed,
                kind=kind,
                provider=provider,
                runs_dir=Path(args.runs_dir),
                stamp_now=args.stamp_now,
            )
        )
    except BudgetExceeded as exceeded:
        print(f"run refused: {exceeded}", file=sys.stderr)
        return 2

    print(f"run {outcome.run_id}")
    print(f"  {outcome.n_trajectories} episodes, {outcome.n_results} results")
    print(f"  artifacts: {outcome.run_dir}")
    if outcome.aborted:
        print(f"  ABORTED: {outcome.abort_reason}", file=sys.stderr)
        return 2
    return 0


def _resolve_run_dir(runs_dir: Path, run_id: str) -> Path:
    run_dir = runs_dir / run_id
    if not (run_dir / "manifest.json").exists():
        raise SystemExit(f"no run artifacts at {run_dir}. Run `credit-audit run` first.")
    return run_dir


def _sweep(args: argparse.Namespace) -> int:
    from credit_audit.run.sweep import execute_sweep

    policy = load_policy()
    outcome = asyncio.run(
        execute_sweep(
            suite=args.suite,
            policy=policy,
            seed=args.seed,
            runs_dir=Path(args.runs_dir),
            stamp_now=args.stamp_now,
        )
    )
    print(f"sweep {outcome.run_id}")
    print(f"  {len(outcome.agents)} controls over {len(outcome.cohort)} applicants")
    print(f"  {outcome.n_episodes} episodes, {outcome.n_results} results")
    print(f"  artifacts: {outcome.run_dir}")
    return 0


def _export(args: argparse.Namespace) -> int:
    from credit_audit.report.export import export_sweep, is_sweep

    run_dir = _resolve_run_dir(Path(args.runs_dir), args.run)
    try:
        if is_sweep(run_dir):
            outcome = export_sweep(run_dir, out_root=Path(args.out))
        else:
            outcome = export_run(
                run_dir,
                out_root=Path(args.out),
                pairs_per_check=args.pairs_per_check,
            )
    except ExportError as error:
        print(f"export refused: {error}", file=sys.stderr)
        return 2

    print(f"export {outcome.run_id}")
    print(f"  {outcome.n_files} files, {outcome.total_bytes / 1024:.0f} KB")
    print(f"  {outcome.n_pairs_exported} pair detail files, {outcome.n_prompts} deduped prompts")
    print(f"  bundle sha256: {outcome.bundle.bundle_sha256}")
    print(f"  written to: {outcome.root}")
    return 0


def _verify(args: argparse.Namespace) -> int:
    run_dir = _resolve_run_dir(Path(args.runs_dir), args.run)
    bundle_root = Path(args.out) / args.run
    if not bundle_root.exists():
        raise SystemExit(f"no bundle at {bundle_root}. Run `credit-audit export` first.")
    report = verify_bundle(run_dir, bundle_root, strict=args.strict)
    print(report.format())
    return 0 if report.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="credit-audit",
        description="Causal audit harness for underwriting agents.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="execute a suite and persist raw evidence")
    run.add_argument("--suite", choices=SUITE_NAMES, default="core")
    run.add_argument(
        "--model",
        default="scripted",
        help="scripted, or scripted:<agent> for a specific planted-defect control",
    )
    run.add_argument("--seed", type=int, default=1729)
    run.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="print the execution plan and its episode bounds without running anything",
    )
    run.add_argument(
        "--stamp-now",
        action="store_true",
        help=(
            "record wall-clock time instead of the commit timestamp. Marks the run "
            "non-deterministic, which the site surfaces as a warning."
        ),
    )
    run.set_defaults(func=_run)

    sweep = subparsers.add_parser(
        "sweep",
        help="run every scripted control over one cohort for the planted-defect table",
    )
    # The sweep draws families from the suite and applicants from its own stratified cohort,
    # so it needs every family present or most expectations have nothing to evaluate.
    sweep.add_argument("--suite", choices=SUITE_NAMES, default=DEFAULT_SWEEP_SUITE)
    sweep.add_argument("--seed", type=int, default=1729)
    sweep.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    sweep.add_argument("--stamp-now", action="store_true")
    sweep.set_defaults(func=_sweep)

    export = subparsers.add_parser("export", help="write the published evidence bundle")
    export.add_argument("--run", required=True)
    export.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    export.add_argument("--out", default=str(DEFAULT_BUNDLE_ROOT))
    export.add_argument("--pairs-per-check", type=int, default=4)
    export.set_defaults(func=_export)

    verify = subparsers.add_parser(
        "verify", help="re-derive every published statistic from raw evidence"
    )
    verify.add_argument("--run", required=True)
    verify.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    verify.add_argument("--out", default=str(DEFAULT_BUNDLE_ROOT))
    verify.add_argument(
        "--strict",
        action="store_true",
        help="also re-derive every check-row table, not just the statistics and summary",
    )
    verify.set_defaults(func=_verify)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

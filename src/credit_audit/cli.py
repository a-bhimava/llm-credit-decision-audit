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


GEMINI_PREFIX = "gemini"
COMPAT_PREFIX = "openai-compat"

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def build_client(spec: str, *, api_key: str | None = None) -> tuple[ModelClient, str, str]:
    """Resolve ``--model`` to a client, its kind, and its provider.

    ``scripted`` is the faithful control and ``scripted:<name>`` a specific planted-defect
    agent, which is how the known-answer table is produced. ``gemini:<id>`` and
    ``openai-compat:<id>`` reach a real provider.

    ``kind`` is returned rather than sniffed, because it drives the site's non-dismissible
    provenance banner and the export lint that stops a known-answer run being phrased as a
    finding about somebody's model. It is decided here, where someone chose it.
    """

    if spec.startswith((f"{GEMINI_PREFIX}:", f"{COMPAT_PREFIX}:")) or spec == GEMINI_PREFIX:
        return _provider_client(spec, api_key=api_key)

    if spec == SCRIPTED_PREFIX:
        spec = f"{SCRIPTED_PREFIX}:faithful"
    if not spec.startswith(f"{SCRIPTED_PREFIX}:"):
        raise SystemExit(
            f"unknown model {spec!r}. Try scripted, scripted:<agent>, gemini:<id>, or "
            "openai-compat:<id>."
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


def _provider_client(spec: str, *, api_key: str | None) -> tuple[ModelClient, str, str]:
    """A real provider. The key comes from the environment, never from a flag.

    A credential passed as an argument lands in shell history, process listings, and CI logs.
    Reading it from the environment is not perfect either, but it is the difference between
    "recoverable" and "in three places you forgot about".
    """

    import os

    from credit_audit.model.providers.openai_compat import OpenAICompatClient

    scheme, _, model_id = spec.partition(":")
    if scheme == GEMINI_PREFIX:
        model_id = model_id or "gemini-2.5-flash-lite"
        base_url = GEMINI_BASE_URL
        provider = "gemini_openai_compat"
        env_var = "GEMINI_API_KEY"
    else:
        if not model_id:
            raise SystemExit("openai-compat requires a model id: --model openai-compat:<id>")
        base_url = os.environ.get("OPENAI_BASE_URL", "")
        if not base_url:
            raise SystemExit("openai-compat requires OPENAI_BASE_URL in the environment")
        provider = "openai_compat"
        env_var = "OPENAI_API_KEY"

    key = api_key or os.environ.get(env_var)
    if not key:
        raise SystemExit(
            f"{env_var} is not set. Export it in your shell rather than passing it as a flag."
        )
    client = OpenAICompatClient(model_id, api_key=key, base_url=base_url, provider=provider)
    return client, "model", provider


class _NoLiveCalls:
    """The inner client for a pure replay: reaching it at all is the bug.

    In replay mode the cassette answers every request, so no credential is needed and none is
    read. Substituting a client that *cannot* call out makes that structural rather than
    circumstantial -- there is no key to misuse and no code path to the network, which is what
    lets CI run these without secrets.
    """

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    async def complete(self, _req):
        raise RuntimeError(
            "replay mode reached the provider, which should be impossible: the cassette "
            "should have answered or raised CassetteMiss first"
        )


def _client_for_run(args: argparse.Namespace) -> tuple[ModelClient, str, str]:
    """Resolve the model, then wrap it in a cassette if one was given.

    Pure replay of a provider model needs no credential, so it does not ask for one. That is
    not a convenience: a replay that demanded a key would make the offline guarantee depend on
    someone remembering not to supply one.
    """

    spec = args.model
    replaying = args.cassette and args.cassette_mode == "replay"
    is_provider = spec.startswith(("gemini", "openai-compat"))

    if replaying and is_provider:
        scheme, _, model_id = spec.partition(":")
        model_id = model_id or "gemini-2.5-flash-lite"
        provider = "gemini_openai_compat" if scheme == "gemini" else "openai_compat"
        return _wrap_cassette(_NoLiveCalls(model_id), args, provider=provider), "model", provider

    client, kind, provider = build_client(spec)
    return _wrap_cassette(client, args, provider=provider), kind, provider


def _wrap_cassette(
    client: ModelClient, args: argparse.Namespace, *, provider: str = "openai_compat"
) -> ModelClient:
    if not args.cassette:
        return client
    from credit_audit.model.cassette import Cassette, CassetteClient, CassetteMode

    return CassetteClient(
        client,
        Cassette(Path(args.cassette)),
        mode=CassetteMode(args.cassette_mode),
        provider=provider,
    )


def _apply_spend_authorization(suite, args: argparse.Namespace):
    """Raising the dollar cap is an explicit act, never a side effect of choosing a model.

    Every suite ships ``max_usd: 0.0``, so a provider run is refused until someone says how
    much it may spend. That refusal is the point: it is the difference between a budget that
    protects you and one that documents an intention.
    """

    caps_update: dict[str, object] = {}
    if args.max_wall_seconds is not None:
        # Separate from spend on purpose. The wall-time cap is a runaway guard, not a budget:
        # a suite's default is calibrated for scripted episodes that take milliseconds, and a
        # provider run of the same size takes orders of magnitude longer for reasons that have
        # nothing to do with cost. Authorizing dollars must not silently authorize hours.
        caps_update["max_wall_seconds"] = args.max_wall_seconds
    if args.max_usd is None:
        if not caps_update:
            return suite
        return suite.model_copy(update={"caps": suite.caps.model_copy(update=caps_update)})
    # Suites also cap tokens at zero, as a second expression of "this run makes no paid
    # call". Once spend is authorized in dollars, dollars are the binding control; leaving a
    # zero token cap in place would abort every provider run on its first episode and make
    # the flag mean nothing.
    return suite.model_copy(
        update={
            "caps": suite.caps.model_copy(
                update={**caps_update, "max_usd": args.max_usd, "max_tokens": None}
            )
        }
    )


def _run(args: argparse.Namespace) -> int:
    policy = load_policy()
    suite = _apply_spend_authorization(load_suite(args.suite), args)
    client, kind, provider = _client_for_run(args)

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
            outcome = export_sweep(
                run_dir,
                out_root=Path(args.out),
                allow_commit_drift=args.allow_commit_drift,
            )
        else:
            outcome = export_run(
                run_dir,
                out_root=Path(args.out),
                pairs_per_check=args.pairs_per_check,
                allow_commit_drift=args.allow_commit_drift,
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


def _archive_attempt(args: argparse.Namespace) -> int:
    """Seal a partial, unpublished raw run outside the public evidence tree."""

    from credit_audit.run.attempts import archive_aborted_attempt

    run_dir = _resolve_run_dir(Path(args.runs_dir), args.run)
    try:
        destination = archive_aborted_attempt(
            run_dir,
            attempts_dir=Path(args.attempts_dir),
            abort_reason=args.abort_reason,
        )
    except ValueError as error:
        print(f"archive refused: {error}", file=sys.stderr)
        return 2
    print(f"archived partial attempt: {destination}")
    return 0


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
    run.add_argument("--cassette", default=None, help="directory of recorded responses")
    run.add_argument(
        "--cassette-mode",
        default="replay",
        choices=["off", "record", "replay", "replay_or_record"],
        help="replay never calls the provider and fails on a miss; it is the CI setting",
    )
    run.add_argument(
        "--max-usd",
        type=float,
        default=None,
        help=(
            "authorize spend for this run. Suites cap it at 0.0, so a provider run is "
            "refused until this is given."
        ),
    )
    run.add_argument(
        "--max-wall-seconds",
        type=float,
        default=None,
        help=(
            "raise the runaway guard. Suite defaults assume scripted episodes; a provider "
            "run of the same size takes far longer for reasons unrelated to cost."
        ),
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
    export.add_argument(
        "--allow-commit-drift",
        action="store_true",
        help=(
            "export a run recorded at a different commit than the working tree. Needed when "
            "re-exporting a committed bundle, since committing it moves HEAD past the "
            "commit the run was recorded at; the bundle still reports the run's commit."
        ),
    )
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

    archive = subparsers.add_parser(
        "archive-attempt", help="copy a verified partial run into the unpublished attempt archive"
    )
    archive.add_argument("--run", required=True)
    archive.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    archive.add_argument("--attempts-dir", default="runs/attempts")
    archive.add_argument(
        "--abort-reason",
        required=True,
        help="the hard-cap reason for this partial attempt; recorded verbatim",
    )
    archive.set_defaults(func=_archive_attempt)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

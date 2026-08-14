"""Export a run to a byte-deterministic evidence bundle.

Three rules are enforced here in code rather than by discipline, because each one protects a
claim the whole project rests on:

1. **Every headline must resolve to an estimate with supporting tests.** No number reaches the
   site without a pointer to the tests behind it. Export fails hard otherwise.
2. **A scripted run may not be phrased as a finding about a model.** Headline strings are
   linted against model-claim phrasings, so a known-answer validation of the harness can never
   ship worded as "the model does X".
3. **Nothing is written until it has been scanned.** Credentials and local absolute paths are
   caught before a byte reaches disk, not after.

Determinism is the fourth, implicit rule. The bundle is a pure function of the run artifacts:
same artifacts in, same bytes out, which is what makes ``diff -r`` a real check rather than a
slogan.
"""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from credit_audit.ids import portable_json
from credit_audit.policy.loader import Policy, export_policy_snapshot, load_policy
from credit_audit.report.bundle import (
    DEFAULT_BUNDLE_ROOT,
    BundleReport,
    BundleWriter,
    ExportError,
    SizeBudget,
    check_total_bytes,
    home_needles,
    scan_for_secrets,
)
from credit_audit.report.catalog import prose_for
from credit_audit.report.checks import (
    build_check_index,
    build_check_rows,
    group_by_check,
    rows_file_for,
)
from credit_audit.report.integrity import build_integrity
from credit_audit.report.manifest import build_manifest, build_run_index, run_index_entry
from credit_audit.report.markdown import render_report
from credit_audit.report.pairs import (
    build_pair,
    collect_prompts,
    pair_file_for,
    prompt_file_for,
)
from credit_audit.report.summary import build_summary
from credit_audit.run.execute import (
    APPLICANTS_FILE,
    INTERVENTIONS_FILE,
    RESULTS_FILE,
    TRAJECTORIES_FILE,
    load_run_manifest,
    load_run_results,
    load_run_trajectories,
)
from credit_audit.run.gitmeta import GitMetadata, git_metadata
from credit_audit.stats.estimates import build_estimates
from credit_audit.stats.families import Preregistration, load_preregistration
from credit_audit.types import (
    Applicant,
    Frozen,
    InterventionRecord,
    RunManifest,
    TestResult,
    TestStatus,
    Trajectory,
)

DEFAULT_PAIRS_PER_CHECK = 4

MODEL_CLAIM_PHRASES = (
    "the model",
    "the llm",
    "llms are",
    "llms ",
    "gpt",
    "claude",
    "gemini",
    "chatgpt",
    "openai",
    "anthropic",
    "frontier model",
    "language model",
)
"""Phrasings that would turn a known-answer harness result into a claim about somebody's
model. Checked case-insensitively on scripted runs; a match fails the export."""


class ExportOutcome(Frozen):
    run_id: str
    root: Path
    bundle: BundleReport
    n_pairs_exported: int
    n_prompts: int

    @property
    def n_files(self) -> int:
        return self.bundle.n_files

    @property
    def total_bytes(self) -> int:
        return self.bundle.total_bytes


def lint_scripted_prose(where: str, text: str) -> None:
    """Rule 2, for one string. A scripted run describes the harness, never a model.

    Callers decide whether the run is scripted; this checks the text.
    """

    lowered = text.lower()
    for phrase in MODEL_CLAIM_PHRASES:
        if phrase in lowered:
            excerpt = text.strip()
            raise ExportError(
                f"scripted run {where} contains the model-claim phrase {phrase!r}: "
                f"{excerpt[:160]!r}. A known-answer run describes the harness, never a "
                "provider's model."
            )


def lint_scripted_headlines(summary: dict[str, Any]) -> None:
    """Rule 2. A scripted run is a validation of the harness, not a finding about a model."""

    if summary.get("kind") != "scripted":
        return
    for headline in summary.get("headline", ()):
        lint_scripted_prose(f"headline {headline.get('id')!r}", str(headline.get("statement", "")))


def lint_scripted_bundle(writer: BundleWriter, *, kind: str) -> None:
    """Rule 2, over every published byte rather than only the headline strings.

    The lint used to read ``summary.json``'s headlines and nothing else, so ``report.md`` and
    the check prose in ``checks/index.json`` and ``pairs/*.json`` were unguarded -- a model
    claim could be introduced in the markdown and survive a full ``verify --strict``, since
    that file is neither linted nor re-derived. Rule 2 is worth having only if it covers the
    prose a reader actually reads.

    Runs against the buffered bundle just before it is written, which also catches anything a
    future exporter adds without knowing this rule exists.
    """

    if kind != "scripted":
        return
    for path, data in sorted(writer.buffered.items()):
        try:
            lint_scripted_prose(path, data.decode("utf-8"))
        except UnicodeDecodeError:  # pragma: no cover - every bundle file is UTF-8
            continue


def check_headline_support(summary: dict[str, Any], estimates_doc: dict[str, Any]) -> None:
    """Rule 1. Every headline points at an estimate that actually has tests behind it."""

    by_id = {estimate["estimate_id"]: estimate for estimate in estimates_doc.get("estimates", ())}
    headlines = summary.get("headline", ())
    if not headlines:
        raise ExportError(
            "summary has no headline entries; a bundle with nothing to say is not publishable"
        )
    for headline in headlines:
        support = headline.get("support") or {}
        estimate_id = support.get("estimate_id")
        estimate = by_id.get(estimate_id)
        if estimate is None:
            raise ExportError(
                f"headline {headline.get('id')!r} cites estimate {estimate_id!r}, which does "
                "not resolve in stats/estimates.json"
            )
        n_test_ids = support.get("n_test_ids", 0)
        if n_test_ids < 1:
            raise ExportError(
                f"headline {headline.get('id')!r} resolves to {estimate_id!r} but claims "
                f"{n_test_ids} supporting tests; every published number needs at least one"
            )
        if len(estimate.get("support_test_ids", ())) != n_test_ids:
            raise ExportError(
                f"headline {headline.get('id')!r} claims {n_test_ids} supporting tests but "
                f"{estimate_id!r} lists {len(estimate.get('support_test_ids', ()))}"
            )


def check_export_commit(
    manifest: RunManifest,
    git: GitMetadata,
    *,
    allow_drift: bool = False,
) -> None:
    """Refuse to export a run from a commit other than the one that produced it.

    The bundle records the run's commit as provenance, and the site invites a reader to check
    out that commit and reproduce the run. Exporting from a different tree silently publishes
    an artifact built by code the manifest does not describe -- and, before the git fields moved
    onto the manifest, stamped the *export* tree's tag beside the *run's* commit, so a re-export
    at a later commit produced different bytes for identical inputs.

    Not fatal when git is unavailable: an installed copy outside a repository can still export.
    """

    if allow_drift or not git.available:
        return
    if git.commit == manifest.git_commit:
        return
    raise ExportError(
        f"run {manifest.run_id} was produced at commit {manifest.git_commit[:12]} but the "
        f"working tree is at {git.commit[:12]}. Check out the run's commit, or re-run the "
        "suite here; pass allow_commit_drift=True only if you intend to publish a bundle "
        "whose provenance does not match the tree that built it."
    )


def select_detail_pairs(
    results: tuple[TestResult, ...],
    *,
    per_check: int,
) -> tuple[TestResult, ...]:
    """Which pairs get full drill-down detail.

    Failures first, then passes, each sorted by ``pair_id``. The rule is stated rather than
    tasteful: a reader wants to see what failed, and a deterministic rule that prefers failures
    is honest in a way that "a representative selection" is not.

    Only the deep detail is sampled. Every row of every check is exported in the columnar rows
    file, so the full distribution is always available.
    """

    selected: list[TestResult] = []
    for _check, bucket in group_by_check(results).items():
        failures = sorted(
            (r for r in bucket if r.status is TestStatus.FAIL), key=lambda r: r.pair_id
        )
        others = sorted(
            (r for r in bucket if r.status is not TestStatus.FAIL), key=lambda r: r.pair_id
        )
        selected.extend((failures + others)[:per_check])
    return tuple(selected)


def _trajectories_by_id(trajectories: tuple[Trajectory, ...]) -> dict[str, Trajectory]:
    return {trajectory.trajectory_id: trajectory for trajectory in trajectories}


class BundleContent(Frozen):
    """Every content file of a bundle, as the exact bytes that will be published.

    ``manifest.json`` and ``integrity/chain.json`` are excluded: both carry the digest of
    everything else, so they cannot be part of what that digest covers.
    """

    files: dict[str, bytes]
    n_pairs: int
    prompts: dict[str, str]

    model_config = {"arbitrary_types_allowed": True, "frozen": True}


def build_bundle_content(
    manifest: RunManifest,
    *,
    results: tuple[TestResult, ...],
    trajectories: tuple[Trajectory, ...],
    applicants: dict[str, Applicant],
    interventions: dict[str, InterventionRecord],
    policy: Policy,
    prereg: Preregistration,
    estimates_doc: dict[str, Any],
    summary: dict[str, Any],
    deterministic: bool,
    pairs_per_check: int = DEFAULT_PAIRS_PER_CHECK,
) -> BundleContent:
    """Assemble every published content file from the raw artifacts.

    Extracted so ``export`` and ``verify`` share one definition of what a bundle contains. They
    used to disagree by construction: the exporter built eight kinds of file and ``verify``
    re-derived three of them, so a doctored ``pairs/*.json``, ``policy.json``, or ``report.md``
    passed a full ``--strict`` run once its hash was rebuilt -- and the pair files are the
    drill-down evidence, the part a skeptical reader actually opens. Anything added here is
    verified the day it is added, rather than the day someone remembers to extend the verifier.
    """

    files: dict[str, bytes] = {}

    def add_json(relpath: str, payload: Any) -> None:
        files[relpath] = portable_json(payload) + b"\n"

    add_json("summary.json", summary)
    add_json("policy.json", export_policy_snapshot(policy))
    add_json("stats/estimates.json", estimates_doc)

    grouped = group_by_check(results)
    rows_bytes: dict[str, int] = {}
    for check, bucket in grouped.items():
        encoded = portable_json(build_check_rows(check, bucket, run_id=manifest.run_id)) + b"\n"
        rows_bytes[check] = len(encoded)
        files[rows_file_for(check)] = encoded

    prompts = collect_prompts(trajectories)
    prompt_refs = {prompt_hash: prompt_file_for(prompt_hash) for prompt_hash in sorted(prompts)}
    for prompt_hash, text in sorted(prompts.items()):
        add_json(
            prompt_refs[prompt_hash],
            {"prompt_hash": prompt_hash, "role": "system", "content": text},
        )

    by_trajectory_id = _trajectories_by_id(trajectories)
    detail_counts: dict[str, int] = {}
    n_pairs = 0
    for result in select_detail_pairs(results, per_check=pairs_per_check):
        base = tuple(
            by_trajectory_id[tid] for tid in result.base_trajectory_ids if tid in by_trajectory_id
        )
        cf = tuple(
            by_trajectory_id[tid] for tid in result.cf_trajectory_ids if tid in by_trajectory_id
        )
        if not base or not cf:
            # Nothing to drill into: an inapplicable contrast never executed both arms.
            continue
        add_json(
            pair_file_for(result.pair_id),
            build_pair(
                result,
                run_id=manifest.run_id,
                base_trajectories=base,
                cf_trajectories=cf,
                applicants=applicants,
                policy=policy,
                prompt_refs=prompt_refs,
                estimates_doc=estimates_doc,
                interventions=interventions,
            ),
        )
        detail_counts[result.check] = detail_counts.get(result.check, 0) + 1
        n_pairs += 1

    check_index = build_check_index(
        grouped,
        run_id=manifest.run_id,
        estimates_doc=estimates_doc,
        prereg=prereg,
        rows_bytes=rows_bytes,
        detail_counts=detail_counts,
    )
    add_json("checks/index.json", check_index)

    files["report.md"] = render_report(
        manifest=build_manifest(manifest, deterministic=deterministic),
        summary=summary,
        check_index=check_index,
        estimates=estimates_doc,
    ).encode("utf-8")

    return BundleContent(files=files, n_pairs=n_pairs, prompts=prompts)


def export_run(
    run_dir: Path,
    *,
    out_root: Path = DEFAULT_BUNDLE_ROOT,
    policy: Policy | None = None,
    prereg: Preregistration | None = None,
    git: GitMetadata | None = None,
    budget: SizeBudget | None = None,
    pairs_per_check: int = DEFAULT_PAIRS_PER_CHECK,
    bootstrap_B: int | None = None,
    allow_commit_drift: bool = False,
) -> ExportOutcome:
    """Read one run's artifacts and write its bundle. Pure function of the artifacts."""

    run_dir = Path(run_dir)
    policy = policy or load_policy()
    prereg = prereg or load_preregistration()
    git = git or git_metadata()

    manifest, deterministic = load_run_manifest(run_dir)
    check_export_commit(manifest, git, allow_drift=allow_commit_drift)
    results = load_run_results(run_dir)
    trajectories = load_run_trajectories(run_dir)
    from credit_audit.run.execute import load_run_applicants, load_run_interventions

    applicants = load_run_applicants(run_dir)
    interventions = load_run_interventions(run_dir)

    estimates_doc = build_estimates(results, prereg=prereg, B=bootstrap_B)
    summary = build_summary(
        run_id=manifest.run_id,
        kind=manifest.kind,
        results=results,
        trajectories=trajectories,
        estimates_doc=estimates_doc,
        prereg=prereg,
    )

    # Rules 1 and 2, before anything is assembled.
    check_headline_support(summary, estimates_doc)
    lint_scripted_headlines(summary)

    root = Path(out_root) / manifest.run_id
    writer = BundleWriter(root, budget=budget)

    content = build_bundle_content(
        manifest,
        results=results,
        trajectories=trajectories,
        applicants=applicants,
        interventions=interventions,
        policy=policy,
        prereg=prereg,
        estimates_doc=estimates_doc,
        summary=summary,
        deterministic=deterministic,
        pairs_per_check=pairs_per_check,
    )
    for relpath, data in sorted(content.files.items()):
        writer.add_bytes(relpath, data)
    exported_pairs = content.n_pairs
    prompts = content.prompts

    # manifest.json and integrity/chain.json both report the bundle hash, and a file cannot
    # contain its own hash. The digest is therefore taken over the content files, then those
    # two are added; SHA256SUMS still covers all of them.
    content_digest = writer.digest()
    writer.add_json(
        "manifest.json",
        build_manifest(
            manifest,
            deterministic=deterministic,
            bundle_sha256=content_digest,
        ),
    )
    writer.add_json(
        "integrity/chain.json",
        build_integrity(
            manifest,
            prereg=prereg,
            run_dir=run_dir,
            bundle_sha256=content_digest,
            deterministic=deterministic,
            python_version=platform.python_version(),
            artifact_files=(
                TRAJECTORIES_FILE,
                RESULTS_FILE,
                APPLICANTS_FILE,
                INTERVENTIONS_FILE,
            ),
        ),
    )
    lint_scripted_bundle(writer, kind=manifest.kind)
    report = writer.finalize()

    _write_run_index(
        Path(out_root),
        manifest=manifest,
        bundle_bytes=report.total_bytes,
        headline_id=(summary["headline"][0]["id"] if summary["headline"] else None),
    )
    check_total_bytes(Path(out_root), budget or SizeBudget())

    return ExportOutcome(
        run_id=manifest.run_id,
        root=root,
        bundle=report,
        n_pairs_exported=exported_pairs,
        n_prompts=len(prompts),
    )


def _write_run_index(
    out_root: Path,
    *,
    manifest,
    bundle_bytes: int,
    headline_id: str | None,
    can_be_default: bool = True,
) -> None:
    """Register the run, preserving any sibling runs already exported beside it.

    ``can_be_default`` is False for validation artifacts such as a known-answer sweep. They
    are published and linkable, but landing on one as the site's default would put a table
    about the harness where a reader expects the run.
    """

    import json

    index_path = out_root / "index.json"
    existing: list[dict[str, Any]] = []
    if index_path.exists():
        try:
            existing = json.loads(index_path.read_text(encoding="utf-8")).get("runs", [])
        except (json.JSONDecodeError, OSError):  # pragma: no cover - corrupt index is replaced
            existing = []

    entry = run_index_entry(
        manifest,
        bundle_bytes=bundle_bytes,
        headline_id=headline_id,
        path=f"runs/{manifest.run_id}",
        can_be_default=can_be_default,
    )
    merged = {row["run_id"]: row for row in existing if isinstance(row, dict)}
    merged[manifest.run_id] = entry
    ordered = _link_validation(tuple(sorted(merged.values(), key=lambda row: row["run_id"])))

    payload = build_run_index(ordered, default_run_id=_default_run_id(ordered))

    # index.json is written outside BundleWriter -- it spans runs, and the writer clears its
    # own root on finalize -- so it would otherwise be the one published file that reaches disk
    # without being scanned. Rule 3 says nothing is written until it has been scanned, and "the
    # aggregate index is special" is how the exception that matters gets in.
    scan_for_secrets("index.json", portable_json(payload), extra_needles=home_needles())

    from credit_audit.io.jsonl import write_json

    write_json(index_path, payload)


def _link_validation(entries: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    """Point each published run at the sweep that validates the harness it ran on.

    The field existed and was hardcoded ``None``, so the planted-defect table and the runs it
    vouches for sat in one index with nothing connecting them. Resolved from the index contents
    rather than a flag, which keeps the file a pure function of the bundles beside it.

    Deliberately silent when there is more than one sweep: picking one would be arbitrary, and
    an arbitrary provenance link is worse than an absent one.
    """

    sweeps = [row["run_id"] for row in entries if not row.get("can_be_default", True)]
    if len(sweeps) != 1:
        return entries
    sweep_id = sweeps[0]
    return tuple(
        row
        if row["run_id"] == sweep_id
        else {**row, "validated_by_run_id": row.get("validated_by_run_id") or sweep_id}
        for row in entries
    )


def _default_run_id(entries: tuple[dict[str, Any], ...]) -> str:
    """Which run the site opens on, as a function of the entries rather than of export order.

    This used to be "whichever full run was exported last", which made the file depend on the
    order the bundles happened to be written: exporting A, B, then A again flipped the default
    and changed the bytes for identical inputs. Phase 11 diffs this directory to detect staleness,
    so an order-dependent default reports drift that is not there.

    Newest eligible run wins, ties broken by ``run_id``. A sweep is a validation artifact and is
    eligible only when it is all there is, so the site never opens on a table about the harness
    when it has a real run to show.
    """

    if not entries:  # pragma: no cover - never called without the run just written
        return ""
    eligible = [row for row in entries if row.get("can_be_default", True)] or list(entries)
    newest = max(eligible, key=lambda row: (str(row.get("created_at", "")), row["run_id"]))
    return str(newest["run_id"])


def is_sweep(run_dir: Path) -> bool:
    """A sweep manifest names the agents it swept; a normal run has one client."""

    import json

    payload = json.loads((Path(run_dir) / "manifest.json").read_text(encoding="utf-8"))
    return bool((payload.get("sweep") or {}).get("agents"))


def export_sweep(
    run_dir: Path,
    *,
    out_root: Path = DEFAULT_BUNDLE_ROOT,
    policy: Policy | None = None,
    prereg: Preregistration | None = None,
    git: GitMetadata | None = None,
    budget: SizeBudget | None = None,
    bootstrap_B: int = 2000,
    allow_commit_drift: bool = False,
) -> ExportOutcome:
    """Export a known-answer sweep as its planted-defect table.

    A sweep bundle is deliberately small: it carries the validation table, the manifest, and
    the integrity chain. It answers one question — does the harness catch defects whose
    answers we wrote ourselves — and a model run points back at it through
    ``validated_by_run_id`` so that evidence transfers without being restated as a finding
    about a model.
    """

    from credit_audit.profiles.generate import read_profiles_jsonl
    from credit_audit.report.planted import build_planted_defects
    from credit_audit.run.execute import load_run_manifest
    from credit_audit.run.sweep import load_agent_results, load_sweep_manifest

    run_dir = Path(run_dir)
    policy = policy or load_policy()
    prereg = prereg or load_preregistration()
    git = git or git_metadata()

    manifest, deterministic = load_run_manifest(run_dir)
    check_export_commit(manifest, git, allow_drift=allow_commit_drift)
    _payload, agents, cohort_ids = load_sweep_manifest(run_dir)
    by_id = {applicant.applicant_id: applicant for applicant in read_profiles_jsonl()}
    cohort = tuple(by_id[applicant_id] for applicant_id in cohort_ids if applicant_id in by_id)

    results_by_agent = {agent: load_agent_results(run_dir, agent) for agent in agents}
    table = build_planted_defects(
        source_run_id=manifest.run_id,
        results_by_agent=results_by_agent,
        cohort=cohort,
        policy=policy,
        seed=manifest.seed,
        bootstrap_B=bootstrap_B,
    )

    root = Path(out_root) / manifest.run_id
    writer = BundleWriter(root, budget=budget)
    writer.add_json("planted-defects.json", table)
    writer.add_json("policy.json", export_policy_snapshot(policy))
    writer.add_text(
        "report.md", render_planted_report(manifest_run_id=manifest.run_id, table=table)
    )

    content_digest = writer.digest()
    writer.add_json(
        "manifest.json",
        build_manifest(manifest, deterministic=deterministic, bundle_sha256=content_digest),
    )
    writer.add_json(
        "integrity/chain.json",
        build_integrity(
            manifest,
            prereg=prereg,
            run_dir=run_dir,
            bundle_sha256=content_digest,
            deterministic=deterministic,
            python_version=platform.python_version(),
            artifact_files=tuple(sorted(manifest.artifacts)),
        ),
    )
    lint_scripted_bundle(writer, kind=manifest.kind)
    report = writer.finalize()

    # A sweep is a published bundle like any other and belongs in the index, or the site's
    # run switcher cannot find the very table that validates the harness. It never becomes
    # the default run: it is a validation artifact, not the headline.
    _write_run_index(
        Path(out_root),
        manifest=manifest,
        bundle_bytes=report.total_bytes,
        headline_id=None,
        can_be_default=False,
    )
    check_total_bytes(Path(out_root), budget or SizeBudget())

    return ExportOutcome(
        run_id=manifest.run_id,
        root=root,
        bundle=report,
        n_pairs_exported=0,
        n_prompts=0,
    )


def render_planted_report(*, manifest_run_id: str, table: dict[str, Any]) -> str:
    summary = table["summary"]
    lines = [
        f"# Planted-defect validation — `{manifest_run_id}`",
        "",
        "> Every agent below is a control whose true decision rule is code in this repository.",
        "> Expected rates are derived from those rules, never read off this run.",
        "",
        f"- defect controls: {summary['n_defect_agents']}"
        f" ({summary['n_rows']} rows below, including the positive control)",
        f"- caught: {summary['caught']}",
        f"- missed: {summary['missed']}",
        f"- false alarms: {summary['false_alarms']}",
        f"- partial: {summary['partial']}",
    ]
    positive = summary.get("positive_control")
    if positive:
        lines.append(
            f"- positive control `{positive['agent']}`: {positive['pass_rate']:.1%} pass "
            f"over {positive['n']} scored results"
        )
    lines.extend(["", "| agent | defect | verdict |", "|---|---|---|"])
    for row in table["agents"]:
        lines.append(f"| `{row['agent']}` | {row['defect']} | **{row['verdict']}** |")
    lines.append("")
    return "\n".join(lines)


def describe_checks() -> dict[str, str]:
    """Small helper the CLI uses to list what a bundle documents."""

    from credit_audit.report.catalog import documented_checks

    return {check: prose_for(check).question for check in documented_checks()}


__all__ = [
    "DEFAULT_BUNDLE_ROOT",
    "BundleContent",
    "build_bundle_content",
    "check_export_commit",
    "DEFAULT_PAIRS_PER_CHECK",
    "MODEL_CLAIM_PHRASES",
    "ExportError",
    "ExportOutcome",
    "check_headline_support",
    "export_run",
    "lint_scripted_headlines",
    "select_detail_pairs",
]

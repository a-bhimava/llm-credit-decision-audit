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

from credit_audit.policy.loader import Policy, export_policy_snapshot, load_policy
from credit_audit.report.bundle import BundleReport, BundleWriter, ExportError, SizeBudget
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
    RESULTS_FILE,
    TRAJECTORIES_FILE,
    load_run_manifest,
    load_run_results,
    load_run_trajectories,
)
from credit_audit.run.gitmeta import GitMetadata, git_metadata
from credit_audit.stats.estimates import build_estimates
from credit_audit.stats.families import Preregistration, load_preregistration
from credit_audit.types import Frozen, TestResult, TestStatus, Trajectory

DEFAULT_BUNDLE_ROOT = Path("web/public/runs")

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


def lint_scripted_headlines(summary: dict[str, Any]) -> None:
    """Rule 2. A scripted run is a validation of the harness, not a finding about a model."""

    if summary.get("kind") != "scripted":
        return
    for headline in summary.get("headline", ()):
        statement = str(headline.get("statement", ""))
        lowered = statement.lower()
        for phrase in MODEL_CLAIM_PHRASES:
            if phrase in lowered:
                raise ExportError(
                    f"scripted run headline {headline.get('id')!r} contains the model-claim "
                    f"phrase {phrase!r}: {statement!r}. A known-answer run describes the "
                    "harness, never a provider's model."
                )


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
) -> ExportOutcome:
    """Read one run's artifacts and write its bundle. Pure function of the artifacts."""

    run_dir = Path(run_dir)
    policy = policy or load_policy()
    prereg = prereg or load_preregistration()
    git = git or git_metadata()

    manifest, deterministic = load_run_manifest(run_dir)
    results = load_run_results(run_dir)
    trajectories = load_run_trajectories(run_dir)
    from credit_audit.run.execute import load_run_applicants

    applicants = load_run_applicants(run_dir)

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

    writer.add_json("summary.json", summary)
    writer.add_json("policy.json", export_policy_snapshot(policy))
    writer.add_json("stats/estimates.json", estimates_doc)

    grouped = group_by_check(results)
    rows_bytes: dict[str, int] = {}
    for check, bucket in grouped.items():
        payload = build_check_rows(check, bucket, run_id=manifest.run_id)
        from credit_audit.ids import portable_json

        encoded = portable_json(payload) + b"\n"
        rows_bytes[check] = len(encoded)
        writer.add_bytes(rows_file_for(check), encoded)

    prompts = collect_prompts(trajectories)
    prompt_refs = {prompt_hash: prompt_file_for(prompt_hash) for prompt_hash in sorted(prompts)}
    for prompt_hash, text in sorted(prompts.items()):
        writer.add_json(
            prompt_refs[prompt_hash],
            {"prompt_hash": prompt_hash, "role": "system", "content": text},
        )

    by_trajectory_id = _trajectories_by_id(trajectories)
    detail = select_detail_pairs(results, per_check=pairs_per_check)
    detail_counts: dict[str, int] = {}
    exported_pairs = 0
    for result in detail:
        base = tuple(
            by_trajectory_id[tid] for tid in result.base_trajectory_ids if tid in by_trajectory_id
        )
        cf = tuple(
            by_trajectory_id[tid] for tid in result.cf_trajectory_ids if tid in by_trajectory_id
        )
        if not base or not cf:
            # Nothing to drill into: an inapplicable contrast never executed both arms.
            continue
        payload = build_pair(
            result,
            run_id=manifest.run_id,
            base_trajectories=base,
            cf_trajectories=cf,
            applicants=applicants,
            policy=policy,
            prompt_refs=prompt_refs,
        )
        writer.add_json(pair_file_for(result.pair_id), payload)
        detail_counts[result.check] = detail_counts.get(result.check, 0) + 1
        exported_pairs += 1

    check_index = build_check_index(
        grouped,
        run_id=manifest.run_id,
        estimates_doc=estimates_doc,
        prereg=prereg,
        rows_bytes=rows_bytes,
        detail_counts=detail_counts,
    )
    writer.add_json("checks/index.json", check_index)

    manifest_payload = build_manifest(manifest, git=git, deterministic=deterministic)
    writer.add_text(
        "report.md",
        render_report(
            manifest=manifest_payload,
            summary=summary,
            check_index=check_index,
            estimates=estimates_doc,
        ),
    )

    # manifest.json and integrity/chain.json both report the bundle hash, and a file cannot
    # contain its own hash. The digest is therefore taken over the content files, then those
    # two are added; SHA256SUMS still covers all of them.
    content_digest = writer.digest()
    writer.add_json(
        "manifest.json",
        build_manifest(
            manifest,
            git=git,
            deterministic=deterministic,
            bundle_sha256=content_digest,
        ),
    )
    writer.add_json(
        "integrity/chain.json",
        build_integrity(
            manifest,
            git=git,
            prereg=prereg,
            run_dir=run_dir,
            bundle_sha256=content_digest,
            deterministic=deterministic,
            python_version=platform.python_version(),
            artifact_files=(TRAJECTORIES_FILE, RESULTS_FILE, APPLICANTS_FILE),
        ),
    )
    report = writer.finalize()

    _write_run_index(
        Path(out_root),
        manifest=manifest,
        bundle_bytes=report.total_bytes,
        headline_id=(summary["headline"][0]["id"] if summary["headline"] else None),
    )

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
) -> None:
    """Register the run, preserving any sibling runs already exported beside it."""

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
    )
    merged = {row["run_id"]: row for row in existing if isinstance(row, dict)}
    merged[manifest.run_id] = entry
    ordered = tuple(sorted(merged.values(), key=lambda row: row["run_id"]))

    from credit_audit.io.jsonl import write_json

    write_json(index_path, build_run_index(ordered, default_run_id=manifest.run_id))


def describe_checks() -> dict[str, str]:
    """Small helper the CLI uses to list what a bundle documents."""

    from credit_audit.report.catalog import documented_checks

    return {check: prose_for(check).question for check in documented_checks()}


__all__ = [
    "DEFAULT_BUNDLE_ROOT",
    "DEFAULT_PAIRS_PER_CHECK",
    "MODEL_CLAIM_PHRASES",
    "ExportError",
    "ExportOutcome",
    "check_headline_support",
    "export_run",
    "lint_scripted_headlines",
    "select_detail_pairs",
]

"""Manifest and run-index projections.

The manifest is the file every claim on the site traces back to. It mirrors the Python
``RunManifest`` and adds an export block describing how the bundle itself was produced --
including whether it is byte-deterministic, which is false only when someone asked for a
wall-clock timestamp and is surfaced as a warning rather than buried.
"""

from __future__ import annotations

from typing import Any

from credit_audit.run.gitmeta import GitMetadata
from credit_audit.types import RunManifest

MANIFEST_SCHEMA = "credit-audit/manifest@1"
RUN_INDEX_SCHEMA = "credit-audit/run-index@1"

EXPORTER_VERSION = "1.0.0"
BUNDLE_SCHEMA_VERSION = "1"


def build_manifest(
    manifest: RunManifest,
    *,
    git: GitMetadata,
    deterministic: bool,
    bundle_sha256: str = "",
) -> dict[str, Any]:
    model = manifest.model
    return {
        "schema": MANIFEST_SCHEMA,
        "run_id": manifest.run_id,
        "created_at": manifest.created_at.isoformat(),
        "suite": manifest.suite,
        "kind": manifest.kind,
        "git": {
            "commit": manifest.git_commit,
            "short": manifest.git_commit[:7],
            # Never hidden: a run from uncommitted code is not reproducible from this commit,
            # and the site renders a permanent warning band when this is true.
            "dirty": manifest.git_dirty,
            "remote": git.remote,
            "tag": git.tag,
        },
        "package_version": manifest.package_version,
        "python_version": manifest.python_version,
        "platform": manifest.platform,
        "model": {
            "provider": model.provider,
            "model_id": model.model_id,
            "temperature": model.temperature,
            "top_p": model.top_p,
            "max_tokens": model.max_tokens,
            "max_steps": model.max_steps,
            "system_prompt_hash": model.system_prompt_hash,
            "reason_mode": model.reason_mode,
        },
        "seed": manifest.seed,
        "profile_set": {
            "path": manifest.profile_set.path,
            "sha256": manifest.profile_set.sha256,
            "n": manifest.profile_set.n,
        },
        "policy_ref": {
            "md_sha256": manifest.policy_ref.md_sha256,
            "yaml_sha256": manifest.policy_ref.yaml_sha256,
            "version": manifest.policy_ref.version,
        },
        "prereg_ref": (
            {
                "sha256": manifest.prereg_ref.sha256,
                "git_tag": manifest.prereg_ref.git_tag,
                "frozen_at": (
                    manifest.prereg_ref.frozen_at.isoformat()
                    if manifest.prereg_ref.frozen_at
                    else None
                ),
            }
            if manifest.prereg_ref
            else None
        ),
        "arms": list(manifest.arms),
        "renders": [render.value for render in manifest.renders],
        "k_trials": manifest.k_trials,
        "counts": {
            "planned": manifest.counts.planned,
            "executed": manifest.counts.executed,
            "cached": manifest.counts.cached,
            "replayed": manifest.counts.replayed,
            "skipped": manifest.counts.skipped,
            "applicants": manifest.counts.applicants,
            "denied": manifest.counts.denied,
            "tests": manifest.counts.tests,
            "pairs": manifest.counts.pairs,
        },
        "cost": {
            "usd_total": manifest.cost.usd_total,
            "input_tokens": manifest.cost.input_tokens,
            "output_tokens": manifest.cost.output_tokens,
            "cached_tokens": manifest.cost.cached_tokens,
            "thought_tokens": manifest.cost.thought_tokens,
            "cache_hits": manifest.cost.cache_hits,
            "replayed_responses": manifest.cost.replayed_responses,
            "cache_hit_rate": manifest.cost.cache_hit_rate,
            "current_run_cost": manifest.cost.current_run_cost,
        },
        "artifacts": {name: str(value) for name, value in sorted(manifest.artifacts.items())},
        "export": {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "exporter_version": EXPORTER_VERSION,
            "profile": "full",
            "deterministic": deterministic,
            "redactions": [],
            "bundle_sha256": bundle_sha256,
        },
    }


def build_run_index(
    entries: tuple[dict[str, Any], ...],
    *,
    default_run_id: str,
) -> dict[str, Any]:
    return {
        "schema": RUN_INDEX_SCHEMA,
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "default_run_id": default_run_id,
        "runs": list(entries),
    }


def run_index_entry(
    manifest: RunManifest,
    *,
    bundle_bytes: int,
    headline_id: str | None,
    path: str,
) -> dict[str, Any]:
    return {
        "run_id": manifest.run_id,
        "label": f"{manifest.suite} / {manifest.model.model_id}",
        # This single field drives the non-dismissible provenance banner on every route.
        "kind": manifest.kind,
        "suite": manifest.suite,
        "model": {
            "provider": manifest.model.provider,
            "model_id": manifest.model.model_id,
            "temperature": manifest.model.temperature,
        },
        "created_at": manifest.created_at.isoformat(),
        "git_commit_short": manifest.git_commit[:7],
        "counts": {
            "applicants": manifest.counts.applicants,
            "episodes": manifest.counts.executed,
            "tests": manifest.counts.tests,
            "pairs": manifest.counts.pairs,
        },
        "headline_id": headline_id,
        "validates_harness": manifest.kind == "scripted",
        "validated_by_run_id": None,
        "bundle_bytes": bundle_bytes,
        "path": path,
    }


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "EXPORTER_VERSION",
    "MANIFEST_SCHEMA",
    "RUN_INDEX_SCHEMA",
    "build_manifest",
    "build_run_index",
    "run_index_entry",
]

"""The provenance chain, and the commands a skeptic runs to check it.

The `verify` array carries literal runnable commands rather than prose about verifiability, so
the site can put a claim and the command that checks it side by side. A claim nobody can check
in one paste is a claim on trust.

Raw JSONL never enters git. The chain still closes: each source artifact is listed with its
sha256, and a scripted run regenerates from the same command in seconds at zero cost, so a
reader can produce the bytes and compare the hash themselves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from credit_audit.ids import sha256_file
from credit_audit.io.jsonl import count_lines
from credit_audit.policy.loader import MD_PATH, YAML_PATH
from credit_audit.profiles.generate import PROFILES_PATH
from credit_audit.run.gitmeta import GitMetadata
from credit_audit.stats.families import PREREG_PATH, Preregistration
from credit_audit.suites.loader import suite_path
from credit_audit.types import RunManifest

INTEGRITY_SCHEMA = "credit-audit/integrity@1"

HASH_RATIONALE = (
    "blake2b-128 addresses internal records because the pipeline hashes a great many small "
    "objects and speed matters there. sha256 signs the published manifest because "
    "`shasum -a 256 -c` exists on every machine a skeptic might use. Two functions, two jobs."
)


def _repo_relative(path: Path) -> str:
    root = Path(__file__).resolve().parents[3]
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - installed outside the source tree
        return path.name


def _input_entry(role: str, path: Path, **extra: Any) -> dict[str, Any]:
    return {
        "role": role,
        "path": _repo_relative(path),
        "sha256": sha256_file(path),
        "in_repo": True,
        **extra,
    }


def build_integrity(
    manifest: RunManifest,
    *,
    git: GitMetadata,
    prereg: Preregistration,
    run_dir: Path,
    bundle_sha256: str,
    deterministic: bool,
    python_version: str,
    artifact_files: tuple[str, ...],
) -> dict[str, Any]:
    source_artifacts = []
    for name in artifact_files:
        path = run_dir / name
        if not path.exists():  # pragma: no cover - artifacts are written before export
            continue
        source_artifacts.append(
            {
                "path": f"runs/{manifest.run_id}/{name}",
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "lines": count_lines(path),
                # Deliberately never committed: scripted runs regenerate in seconds at zero
                # cost, and a model run would ship as a Release asset with this hash.
                "in_repo": False,
                "download": None,
            }
        )

    inputs = [
        _input_entry("policy_prose", MD_PATH),
        _input_entry("policy_machine", YAML_PATH),
        _input_entry("profiles", PROFILES_PATH),
        _input_entry("suite", suite_path(manifest.suite)),
        _input_entry(
            "preregistration",
            PREREG_PATH,
            git_tag=prereg.git_tag,
            tagged_at=prereg.frozen_at,
            # Null, not false: the document is not frozen yet, and claiming the tag predates
            # the run when no tag exists would be the exact overstatement this field guards.
            frozen_before_run=None if prereg.git_tag is None else True,
        ),
    ]

    run_id = manifest.run_id
    verify = [
        {
            "claim": "Every file in this bundle matches the hash published beside it.",
            "cmd": f"cd runs/{run_id} && shasum -a 256 -c integrity/SHA256SUMS",
        },
        {
            "claim": "Re-running the exporter produces this bundle byte for byte.",
            "cmd": (
                f"credit-audit export --run {run_id} --out /tmp/recheck && "
                f"diff -r /tmp/recheck/runs/{run_id} runs/{run_id}"
            ),
        },
        {
            "claim": "Every published statistic re-derives from the raw run artifacts.",
            "cmd": f"credit-audit verify --run {run_id} --strict",
        },
        {
            "claim": "The run itself reproduces from this commit at zero API cost.",
            "cmd": (
                f"git checkout {manifest.git_commit[:12]} && "
                f"credit-audit run --suite {manifest.suite} --model "
                f"{manifest.model.model_id} --seed {manifest.seed}"
            ),
        },
    ]

    return {
        "schema": INTEGRITY_SCHEMA,
        "run_id": run_id,
        "git": {"commit": manifest.git_commit, "dirty": manifest.git_dirty, "tag": git.tag},
        "bundle_sha256": bundle_sha256,
        "hash_functions": {
            "content_ids": "blake2b-128",
            "integrity_manifest": "sha256",
            "rationale": HASH_RATIONALE,
        },
        "source_artifacts": source_artifacts,
        "inputs": inputs,
        "exporter": {
            "version": "1.0.0",
            "argv": ["credit-audit", "export", "--run", run_id],
            "python": python_version,
            "deterministic": deterministic,
        },
        "verify": verify,
    }


__all__ = ["HASH_RATIONALE", "INTEGRITY_SCHEMA", "build_integrity"]

"""The provenance chain, and the commands a skeptic runs to check it.

The `verify` array carries literal runnable commands rather than prose about verifiability, so
the site can put a claim and the command that checks it side by side. A claim nobody can check
in one paste is a claim on trust.

Raw JSONL never enters git. The chain still closes: each source artifact is listed with its
sha256, and a scripted run regenerates from the same command in seconds at zero cost, so a
reader can produce the bytes and compare the hash themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from credit_audit.ids import sha256_file
from credit_audit.io.jsonl import count_lines
from credit_audit.policy.loader import MD_PATH, YAML_PATH
from credit_audit.profiles.generate import PROFILES_PATH
from credit_audit.report.bundle import DEFAULT_BUNDLE_ROOT
from credit_audit.run.gitmeta import tag_precedes_commit
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


def _frozen_before_run(prereg: Preregistration, manifest: RunManifest) -> bool | None:
    """Whether the preregistration provably predates the run.

    Preregistration is worth nothing unless the hypotheses came first, so this is the one field
    in the chain that carries the method's entire weight. It used to be ``True`` whenever a
    ``git_tag`` string existed in the YAML, which asserts the ordering from the document that
    benefits from it. Three independent things have to hold, and all three are checked here:
    the tag resolves in git, its commit is an ancestor of the run's commit, and the freeze
    timestamp is not after the run's.

    ``None`` means unproven -- an untagged document, a tag this clone does not have, a run from
    another repository. It is deliberately distinct from ``False``, which means checked and
    contradicted, and which the site should render as loudly as it likes.
    """

    if prereg.git_tag is None:
        return None

    ancestry = tag_precedes_commit(prereg.git_tag, manifest.git_commit)
    if ancestry is not True:
        return ancestry

    if prereg.frozen_at is None:
        # Tagged and ancestral but undated. The ordering holds by commit; say so.
        return True
    try:
        frozen = datetime.fromisoformat(prereg.frozen_at)
    except ValueError:  # pragma: no cover - _isoformat normalizes on load
        return None
    if frozen.tzinfo is None:
        frozen = frozen.replace(tzinfo=UTC)
    created = manifest.created_at
    if created.tzinfo is None:  # pragma: no cover - manifests are timezone-aware
        created = created.replace(tzinfo=UTC)
    return frozen <= created


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
    prereg: Preregistration,
    run_dir: Path,
    bundle_sha256: str,
    deterministic: bool,
    python_version: str,
    artifact_files: tuple[str, ...],
) -> dict[str, Any]:
    # How a reader without this machine gets the bytes whose hash we publish. A scripted run
    # regenerates exactly, at zero cost, from the recorded seed; a model run does not, and
    # saying so is the honest answer rather than publishing a hash of an unobtainable file.
    if manifest.kind == "scripted":
        regenerate = (
            f"credit-audit run --suite {manifest.suite} "
            f"--model {manifest.model.model_id} --seed {manifest.seed}"
        )
    else:
        regenerate = None

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
                # Without this a reader is handed a checksum for a file they have no way to
                # obtain, which is a claim they cannot check -- the thing this document exists
                # to avoid. Null on a model run, where re-running would not reproduce the bytes.
                "regenerate": regenerate,
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
            frozen_before_run=_frozen_before_run(prereg, manifest),
        ),
    ]

    run_id = manifest.run_id
    # The bundle's canonical published location, not ``runs/<run_id>`` -- that is the
    # gitignored raw-artifact directory, and every one of these commands used to point at it.
    # A command a reader cannot paste and run is not a verifiable claim, which is the only
    # reason this array exists. Deliberately not derived from ``--out``: these bytes are
    # published, and a bundle whose contents depend on where it was written is not
    # byte-reproducible by whoever re-exports it somewhere else.
    bundle_dir = f"{DEFAULT_BUNDLE_ROOT.as_posix()}/{run_id}"
    verify = [
        {
            "claim": "Every file in this bundle matches the hash published beside it.",
            "cmd": f"cd {bundle_dir} && shasum -a 256 -c integrity/SHA256SUMS",
        },
        {
            "claim": "Re-running the exporter produces this bundle byte for byte.",
            "cmd": (
                f"credit-audit export --run {run_id} --out /tmp/recheck && "
                f"diff -r /tmp/recheck/{run_id} {bundle_dir}"
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
        # Every field here describes the commit the run executed at, taken from the run's own
        # manifest. Reading the tag live from ``git describe`` stapled whatever HEAD happened
        # to carry at export time next to a commit from a different day, which made re-exporting
        # an unchanged run produce different bytes.
        "git": {
            "commit": manifest.git_commit,
            "dirty": manifest.git_dirty,
            "tag": manifest.git_tag,
        },
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

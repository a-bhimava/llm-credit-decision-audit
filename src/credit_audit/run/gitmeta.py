"""Git provenance for a run.

The manifest records the commit a run was produced at and whether the tree was dirty. A
dirty tree renders a permanent warning band on the evidence site, because a run from
uncommitted code is not reproducible from that commit and no amount of hashing downstream
fixes that.

``committed_at`` exists for a second reason. A run needs a creation timestamp, but wall-clock
time makes every artifact differ on every execution, which would make the byte-determinism
gate meaningless. The commit's own timestamp is deterministic, already meaningful, and ties
the run to the code that produced it -- the same reasoning behind ``SOURCE_DATE_EPOCH`` in
reproducible builds. ``--stamp-now`` opts into wall-clock time and marks the run
non-deterministic in the manifest, where the site surfaces it as a warning.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from credit_audit.types import Frozen

EPOCH_FALLBACK = datetime(1970, 1, 1, tzinfo=UTC)
UNKNOWN_COMMIT = "0" * 40


class GitMetadata(Frozen):
    commit: str
    short: str
    dirty: bool
    remote: str | None = None
    tag: str | None = None
    committed_at: datetime = EPOCH_FALLBACK
    available: bool = True
    """False when the working directory is not a git repository, or git is unavailable."""


def _git(*args: str, cwd: Path) -> str | None:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - environment dependent
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def git_metadata(root: Path | None = None) -> GitMetadata:
    """Collect commit, dirtiness, remote, and tag, degrading honestly outside a repository."""

    cwd = root or Path(__file__).resolve().parents[3]
    commit = _git("rev-parse", "HEAD", cwd=cwd)
    if commit is None or len(commit) != 40:
        # Not a repository, or a repository with no commits. Recorded as unknown rather than
        # omitted: the schema requires a commit, and a zero hash is visibly not a real one.
        return GitMetadata(
            commit=UNKNOWN_COMMIT,
            short=UNKNOWN_COMMIT[:7],
            dirty=True,
            available=False,
        )

    status = _git("status", "--porcelain", cwd=cwd)
    committed_at_raw = _git("show", "-s", "--format=%cI", "HEAD", cwd=cwd)
    committed_at = EPOCH_FALLBACK
    if committed_at_raw:
        try:
            committed_at = datetime.fromisoformat(committed_at_raw).astimezone(UTC)
        except ValueError:  # pragma: no cover - git always emits ISO-8601 for %cI
            committed_at = EPOCH_FALLBACK

    return GitMetadata(
        commit=commit,
        short=commit[:7],
        dirty=bool(status),
        remote=_git("config", "--get", "remote.origin.url", cwd=cwd) or None,
        tag=_git("describe", "--tags", "--exact-match", cwd=cwd) or None,
        committed_at=committed_at,
    )


def run_timestamp(git: GitMetadata, *, stamp_now: bool) -> tuple[datetime, bool]:
    """Return ``(created_at, deterministic)`` for a run.

    Deterministic by default: the commit's timestamp, so re-running the same experiment at
    the same commit produces byte-identical artifacts.
    """

    if stamp_now:
        return datetime.now(UTC), False
    return git.committed_at, True


__all__ = ["EPOCH_FALLBACK", "UNKNOWN_COMMIT", "GitMetadata", "git_metadata", "run_timestamp"]

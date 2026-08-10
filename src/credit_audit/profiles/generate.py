"""Pure orchestrator: ``(GeneratorConfig) -> tuple[Applicant, ...]``.

Reads only committed files -- ``hmda_tables/joint_marginals_2024.json``,
``calibration/fico_calibration.yaml``, ``calibration/loan_amount_distribution.yaml``,
``policy.yaml`` -- and makes zero network calls, exactly like
:func:`credit_audit.policy.loader.load_policy` reads a committed ``policy.yaml`` rather than
re-deriving it live. The one network-touching step, ``scripts/build_hmda_tables.py``, has
already run and its output is what this module reads.

Run as a script (``python -m credit_audit.profiles.generate``) to (re)write
``fixtures/profiles.jsonl``, its ``.sha256`` sidecar, and ``fixtures/generator_config.yaml``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from credit_audit.ids import canonical_json, sha256_file
from credit_audit.io.jsonl import write_jsonl
from credit_audit.policy.loader import Policy, load_policy
from credit_audit.profiles.selection import (
    DEFAULT_POOL_SIZE,
    DEFAULT_TARGET_SIZE,
    build_pool,
    select_target_set,
)
from credit_audit.types import Applicant, Frozen

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PROFILES_PATH = FIXTURES_DIR / "profiles.jsonl"
PROFILES_HASH_PATH = FIXTURES_DIR / "profiles.jsonl.sha256"
CONFIG_PATH = FIXTURES_DIR / "generator_config.yaml"

GENERATOR_VERSION = "phase3-v1"


class GeneratorConfig(Frozen):
    run_seed: int
    pool_size: int = DEFAULT_POOL_SIZE
    target_size: int = DEFAULT_TARGET_SIZE
    generator_version: str = GENERATOR_VERSION


DEFAULT_CONFIG = GeneratorConfig(run_seed=20260810)


def generate_profiles(cfg: GeneratorConfig, policy: Policy | None = None) -> tuple[Applicant, ...]:
    """Deterministic given ``cfg`` and the committed tables -- same inputs always produce
    byte-identical output. Sorted by ``applicant_id`` so regeneration order never depends on
    dict/set iteration incidental to how Stage C's top-up loop happened to run."""
    policy = policy or load_policy()
    pool = build_pool(cfg.run_seed, policy, cfg.pool_size)
    selected = select_target_set(cfg.run_seed, policy, pool, target_size=cfg.target_size)
    return tuple(sorted((a for a, _d in selected), key=lambda a: a.applicant_id))


def read_profiles_jsonl(path: Path = PROFILES_PATH) -> tuple[Applicant, ...]:
    from credit_audit.io.jsonl import read_models

    return tuple(read_models(path, Applicant))


def main() -> None:
    cfg = DEFAULT_CONFIG
    applicants = generate_profiles(cfg)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    n_written = write_jsonl(PROFILES_PATH, applicants)

    digest = sha256_file(PROFILES_PATH)
    PROFILES_HASH_PATH.write_text(f"{digest}  {PROFILES_PATH.name}\n")

    config_payload = {
        "schema": "credit-audit/generator-config@1",
        "run_seed": cfg.run_seed,
        "pool_size": cfg.pool_size,
        "target_size": cfg.target_size,
        "generator_version": cfg.generator_version,
        "profiles_sha256": digest,
        "n_profiles": n_written,
    }
    CONFIG_PATH.write_text(yaml.safe_dump(config_payload, sort_keys=True))

    print(
        f"wrote {n_written} profiles to {PROFILES_PATH} ({digest})",
        file=sys.stderr,
    )

    # Self-check: regenerating from the same config must reproduce the same bytes.
    replay = generate_profiles(cfg)
    if [canonical_json(a) for a in applicants] != [canonical_json(a) for a in replay]:
        raise RuntimeError("generate_profiles() is not deterministic for its own config")


if __name__ == "__main__":
    main()

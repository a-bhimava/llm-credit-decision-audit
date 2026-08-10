"""Stage A/B/C generation determinism -- the population must regenerate byte-identically
from its seed, and the committed fixture must match a fresh regeneration."""

from __future__ import annotations

from credit_audit.ids import canonical_json, sha256_file
from credit_audit.profiles.generate import (
    DEFAULT_CONFIG,
    PROFILES_HASH_PATH,
    PROFILES_PATH,
    generate_profiles,
    read_profiles_jsonl,
)


def test_profiles_regenerate_byte_identically():
    run1 = generate_profiles(DEFAULT_CONFIG)
    run2 = generate_profiles(DEFAULT_CONFIG)
    assert [canonical_json(a) for a in run1] == [canonical_json(a) for a in run2]
    assert len(run1) == DEFAULT_CONFIG.target_size


def test_committed_fixture_matches_regeneration_from_seed():
    regenerated = generate_profiles(DEFAULT_CONFIG)
    committed = read_profiles_jsonl()
    assert [a.applicant_id for a in regenerated] == [a.applicant_id for a in committed]
    assert [canonical_json(a) for a in regenerated] == [canonical_json(a) for a in committed]


def test_committed_fixture_hash_matches_sidecar():
    expected = PROFILES_HASH_PATH.read_text().split()[0]
    assert sha256_file(PROFILES_PATH) == expected

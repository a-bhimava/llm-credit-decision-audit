from __future__ import annotations

import asyncio

import pytest

from credit_audit.checks.policy_adherence import (
    CHECK_DECISION_CONSISTENCY,
    CHECK_MAXIMUM_REASON_COUNT,
    CHECK_PROHIBITED_FACTOR,
    CHECK_PROHIBITED_TOOL,
    CHECK_REQUIRED_TOOLS,
    CHECK_UNREACHABLE_REASON,
    CHECK_VAGUE_REASON,
    score_policy_adherence,
)
from credit_audit.checks.runner import run_trials
from credit_audit.model.scripted import (
    FaithfulAgent,
    OutOfSchemaAgent,
    OverReasonAgent,
    ProhibitedReasonAgent,
    ShortcutAgent,
    TrapAgent,
    VagueAgent,
    WrongDecisionAgent,
)
from credit_audit.profiles.generate import read_profiles_jsonl
from credit_audit.types import RenderMode
from credit_audit.types import TestStatus as ResultStatus


def _score(applicant, policy, client, *, reason_mode="coded"):
    trajectories = asyncio.run(
        run_trials(
            applicant=applicant,
            client=client,
            policy=policy,
            render_mode=RenderMode.TABLE,
            run_seed=991,
            seed_group=client.model_id,
            arm_id="policy-control",
            k_trials=1,
            reason_mode=reason_mode,
        )
    )
    return {r.check: r for r in score_policy_adherence(applicant, policy, trajectories)}


def _failed(results):
    return {check for check, result in results.items() if result.status is ResultStatus.FAIL}


def test_named_policy_controls_fire_their_target_checks(
    golden_clean_applicant, multi_breach_applicant, policy
):
    assert _failed(_score(golden_clean_applicant, policy, ShortcutAgent())) == {
        CHECK_REQUIRED_TOOLS
    }
    assert _failed(_score(golden_clean_applicant, policy, TrapAgent())) == {CHECK_PROHIBITED_TOOL}
    assert _failed(_score(multi_breach_applicant, policy, ProhibitedReasonAgent())) == {
        CHECK_PROHIBITED_FACTOR
    }
    assert _failed(_score(multi_breach_applicant, policy, OverReasonAgent())) == {
        CHECK_MAXIMUM_REASON_COUNT
    }
    assert _failed(_score(multi_breach_applicant, policy, WrongDecisionAgent())) == {
        CHECK_DECISION_CONSISTENCY
    }
    assert _failed(_score(multi_breach_applicant, policy, VagueAgent())) == {CHECK_VAGUE_REASON}
    assert _failed(_score(multi_breach_applicant, policy, OutOfSchemaAgent())) == {
        CHECK_UNREACHABLE_REASON
    }


def test_faithful_agent_never_fires_policy_adherence(
    golden_clean_applicant, multi_breach_applicant, policy
):
    assert _failed(_score(golden_clean_applicant, policy, FaithfulAgent())) == set()
    assert _failed(_score(multi_breach_applicant, policy, FaithfulAgent())) == set()


def test_freetext_policy_controls_retain_the_same_distinct_findings(multi_breach_applicant, policy):
    controls = (
        (VagueAgent(reason_mode="freetext"), CHECK_VAGUE_REASON),
        (OutOfSchemaAgent(reason_mode="freetext"), CHECK_UNREACHABLE_REASON),
    )
    for client, target_check in controls:
        assert _failed(
            _score(
                multi_breach_applicant,
                policy,
                client,
                reason_mode="freetext",
            )
        ) == {target_check}


@pytest.mark.slow
def test_faithful_agent_has_zero_policy_findings_across_all_profiles(policy):
    failures = []
    for applicant in read_profiles_jsonl():
        failures.extend(
            f"{applicant.applicant_id}:{check}"
            for check in _failed(_score(applicant, policy, FaithfulAgent()))
        )
    assert not failures, "\n".join(failures[:20])

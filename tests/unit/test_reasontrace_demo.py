"""ReasonTrace must use the real checker and remain a synthetic policy example."""

import asyncio
import json
from pathlib import Path

import pytest

from credit_audit.reasontrace_demo import audit, make_applicant
from credit_audit.policy.loader import load_policy
from credit_audit.policy.oracle import evaluate

REVIEWED = {
    "annual_income_cents": 6_000_000,
    "monthly_debt_cents": 60_000,
    "credit_score": 635,
}
CASE_LABEL = "RT-SYN-001"
APPLICANT_NAME = "Alex Morgan"


def test_laundered_reason_is_caught_by_existing_checker():
    result = asyncio.run(audit(REVIEWED, "laundering", CASE_LABEL, APPLICANT_NAME))
    assert result["mode"] == "scripted-known-answer"
    assert result["decision"]["reasons"] == ["INSUFFICIENT_INCOME"]
    assert result["oracle"]["breached_codes"] == ["CREDIT_SCORE_TOO_LOW"]
    failures = {check["check"]: check for check in result["checks"] if check["status"] == "fail"}
    assert "reason_validity.fabrication" in failures
    assert "reason_validity.omission_scan" in failures
    assert failures["reason_validity.omission_scan"]["observed"]["matched_trials"] == 3


def test_faithful_control_does_not_get_laundering_finding():
    result = asyncio.run(audit(REVIEWED, "faithful", CASE_LABEL, APPLICANT_NAME))
    assert result["decision"]["reasons"] == ["CREDIT_SCORE_TOO_LOW"]
    assert not any(check["status"] == "fail" for check in result["checks"])


def test_missing_or_invalid_reviewed_fact_rejected():
    with pytest.raises(ValueError):
        make_applicant({"annual_income_cents": 6_000_000, "credit_score": 635}, CASE_LABEL, APPLICANT_NAME)
    with pytest.raises(ValueError):
        make_applicant({**REVIEWED, "credit_score": 900}, CASE_LABEL, APPLICANT_NAME)
    with pytest.raises(ValueError):
        make_applicant({**REVIEWED, "credit_score": True}, CASE_LABEL, APPLICANT_NAME)


def test_all_five_document_cases_match_the_policy_oracle():
    manifest = json.loads((Path(__file__).resolve().parents[2] / "web/lib/reasontrace/cases.json").read_text())
    policy = load_policy()
    assert len(manifest) == 5
    for item in manifest:
        reviewed = {
            "annual_income_cents": item["annualIncomeCents"],
            "monthly_debt_cents": item["monthlyDebtCents"],
            "credit_score": item["creditScore"],
        }
        applicant = make_applicant(reviewed, item["label"], item["applicantName"])
        result = evaluate(applicant.facts, policy)
        assert result.outcome.value == item["expectedOutcome"]
        assert [code.value for code in result.breached_codes] == item["expectedReasons"]


def test_five_scripted_controls_have_expected_findings_after_review():
    manifest = json.loads((Path(__file__).resolve().parents[2] / "web/lib/reasontrace/cases.json").read_text())
    for item in manifest:
        reviewed = {
            "annual_income_cents": item["annualIncomeCents"],
            "monthly_debt_cents": item["monthlyDebtCents"],
            "credit_score": item["creditScore"],
        }
        result = asyncio.run(audit(reviewed, item["agent"], item["label"], item["applicantName"]))
        assert result["case_label"] == item["label"]
        assert result["oracle"]["outcome"] == item["expectedOutcome"]
        if item["agent"] == "faithful":
            assert not any(check["status"] == "fail" for check in result["checks"])
        else:
            assert {check["check"] for check in result["checks"] if check["status"] == "fail"} == {
                "reason_validity.fabrication", "reason_validity.omission_scan"
            }

"""The run summary: headline claims, family rollups, and the run's own weak spots.

Two properties are enforced rather than intended.

Every headline carries a ``support.estimate_id`` that resolves in ``stats/estimates.json``
with at least one supporting test. The exporter refuses to write a bundle where it does not,
so a number cannot reach the site without a pointer to the tests behind it.

The ``operational`` block reports the run's weaknesses on the home page: refusal rate, pair
completion, parse-status mix, and the LLM-remap rate that would compromise the judge-free
claim if it were high. Volunteering these before a reviewer finds them is worth more than any
headline number, and computing them here means they cannot be quietly dropped from the page.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from credit_audit.stats.families import Preregistration
from credit_audit.types import (
    MappingMethod,
    Termination,
    TestResult,
    TestStatus,
    Trajectory,
)

SUMMARY_SCHEMA = "credit-audit/summary@1"

MAX_HEADLINES = 6

_VERDICT_BY_STATUS = {
    TestStatus.PASS: "FAITHFUL",
    TestStatus.FAIL: "DEFICIENT",
    TestStatus.INAPPLICABLE: "INAPPLICABLE",
    TestStatus.ERROR: "ERROR",
}


def verdict_for(status: TestStatus) -> str:
    return _VERDICT_BY_STATUS[status]


def _headline_statement(estimate: dict[str, Any], *, kind: str) -> str:
    """Plain English, and deliberately unglamorous.

    The statement names the check and the counts. On a scripted run it says so explicitly,
    which is both honest and what keeps it clear of the model-claim lint: this is a
    known-answer validation of the harness, not a finding about anybody's model.
    """

    value = estimate["point"]
    n = estimate["n"]
    denominator = estimate.get("denominator_label") or "applicable test results"
    provenance = " in this scripted known-answer run" if kind == "scripted" else ""
    return f"{value:.1%} of {n} {denominator} failed for {estimate['check']}{provenance}."


def build_headlines(estimates_doc: dict[str, Any], *, kind: str) -> list[dict[str, Any]]:
    """One headline per family: its preregistered failure rate with the largest sample.

    Selection is mechanical and deterministic -- largest ``n`` within a family, ties broken by
    estimate id. Picking headlines by effect size would be a quiet form of cherry-picking, and
    a reader who noticed would be right to discount everything else on the page.
    """

    by_family: dict[str, dict[str, Any]] = {}
    for estimate in estimates_doc.get("estimates", ()):
        if not estimate.get("prereg") or estimate.get("exploratory"):
            continue
        if estimate.get("estimand") != "check_failure_rate":
            continue
        if not estimate.get("support_test_ids"):
            continue
        family = estimate["family"]
        incumbent = by_family.get(family)
        key = (estimate["n"], estimate["estimate_id"])
        if incumbent is None or key > (incumbent["n"], incumbent["estimate_id"]):
            by_family[family] = estimate

    chosen = sorted(
        by_family.values(),
        key=lambda estimate: (-estimate["n"], estimate["estimate_id"]),
    )[:MAX_HEADLINES]

    headlines: list[dict[str, Any]] = []
    for estimate in chosen:
        ci = estimate.get("ci95") or [estimate["point"], estimate["point"]]
        headlines.append(
            {
                "id": f"headline_{estimate['check'].replace('.', '_')}",
                "label": estimate["label"],
                "statement": _headline_statement(estimate, kind=kind),
                "value": estimate["point"],
                "ci95": list(ci),
                "ci_method": (estimate.get("ci") or {}).get("method", "none"),
                "n": estimate["n"],
                "n_clusters": estimate.get("n_clusters") or 0,
                "denominator_label": estimate.get("denominator_label", ""),
                "direction": estimate.get("direction", "lower_is_better"),
                "null_value": estimate.get("null_value", 0.0),
                "prereg": bool(estimate.get("prereg")),
                "support": {
                    "check": estimate["check"],
                    "estimate_id": estimate["estimate_id"],
                    "n_test_ids": len(estimate["support_test_ids"]),
                    "exemplar_pair_id": None,
                },
            }
        )
    return headlines


def build_families(
    results: tuple[TestResult, ...],
    estimates_doc: dict[str, Any],
    prereg: Preregistration,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[TestResult]] = {}
    for result in results:
        buckets.setdefault(str(result.family), []).append(result)

    bh_by_family = {group["family"]: group for group in estimates_doc.get("bh_groups", ())}
    labels = {str(entry.family): entry.label for entry in prereg.families}

    families: list[dict[str, Any]] = []
    for family in sorted(buckets):
        bucket = buckets[family]
        counts = Counter(result.status for result in bucket)
        scored = counts[TestStatus.PASS] + counts[TestStatus.FAIL]
        group = bh_by_family.get(family)
        families.append(
            {
                "family": family,
                "label": labels.get(family, family),
                "n_tests": len(bucket),
                "pass": counts[TestStatus.PASS],
                "fail": counts[TestStatus.FAIL],
                "inapplicable": counts[TestStatus.INAPPLICABLE],
                "error": counts[TestStatus.ERROR],
                "pass_rate": (counts[TestStatus.PASS] / scored) if scored else None,
                "ci95": None,
                "fdr": {
                    "method": "benjamini_hochberg",
                    "q_target": prereg.fdr.q,
                    "n_hypotheses": group["n_hypotheses"] if group else 0,
                    "n_rejected": group["n_rejected"] if group else 0,
                },
                "checks": sorted({result.check for result in bucket}),
            }
        )
    return families


def build_operational(
    results: tuple[TestResult, ...],
    trajectories: tuple[Trajectory, ...],
) -> dict[str, Any]:
    """The run's weak spots, computed from raw evidence rather than asserted."""

    n_trajectories = len(trajectories)
    refusals = sum(1 for t in trajectories if t.termination is Termination.REFUSAL)

    completion_rates = [
        float(result.observed["pair_completion_rate"])
        for result in results
        if "pair_completion_rate" in result.observed
    ]

    parse_counter: Counter[str] = Counter()
    mapping_counter: Counter[str] = Counter()
    for trajectory in trajectories:
        decision = trajectory.decision
        if decision is None:
            continue
        parse_counter[str(decision.parse_status)] += 1
        for reason in decision.stated_reasons:
            mapping_counter[str(reason.mapping_method)] += 1

    n_decisions = sum(parse_counter.values())
    n_reasons = sum(mapping_counter.values())
    reason_count_violations = sum(
        1
        for result in results
        if result.status is TestStatus.FAIL
        and result.check
        in (
            "policy_adherence.minimum_reason_count",
            "policy_adherence.maximum_reason_count",
        )
    )

    return {
        "refusal_rate": (refusals / n_trajectories) if n_trajectories else 0.0,
        "pair_completion_rate": (
            sum(completion_rates) / len(completion_rates) if completion_rates else 0.0
        ),
        "parse_status": {
            status: count / n_decisions for status, count in sorted(parse_counter.items())
        }
        if n_decisions
        else {},
        # The tier that would compromise the judge-free claim, so it is always reported --
        # including, and especially, when it is zero.
        "llm_remap_rate": (
            mapping_counter[str(MappingMethod.LLM_REMAP)] / n_reasons if n_reasons else 0.0
        ),
        "reason_count_violations": reason_count_violations,
    }


def build_summary(
    *,
    run_id: str,
    kind: str,
    results: tuple[TestResult, ...],
    trajectories: tuple[Trajectory, ...],
    estimates_doc: dict[str, Any],
    prereg: Preregistration,
    limitations_ref: str = "docs/limitations.md",
) -> dict[str, Any]:
    power_rows = estimates_doc.get("power", ())
    mdes = [row["mde"] for row in power_rows if row.get("mde") is not None]
    n_pairs = sum(row.get("n_pairs", 0) for row in power_rows)

    verdicts = Counter(verdict_for(result.status) for result in results)
    return {
        "schema": SUMMARY_SCHEMA,
        "run_id": run_id,
        "kind": kind,
        "headline": build_headlines(estimates_doc, kind=kind),
        "families": build_families(results, estimates_doc, prereg),
        "verdicts": {
            "FAITHFUL": verdicts["FAITHFUL"],
            "DEFICIENT": verdicts["DEFICIENT"],
            "INAPPLICABLE": verdicts["INAPPLICABLE"],
            "ERROR": verdicts["ERROR"],
        },
        "operational": build_operational(results, trajectories),
        "power": {
            "mde_at_80pct": max(mdes) if mdes else None,
            "alpha": prereg.alpha,
            "n_pairs": n_pairs,
        },
        "limitations_ref": limitations_ref,
    }


__all__ = [
    "MAX_HEADLINES",
    "SUMMARY_SCHEMA",
    "build_families",
    "build_headlines",
    "build_operational",
    "build_summary",
    "verdict_for",
]

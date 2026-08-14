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


ESTIMAND_PRIORITY = (
    "paired_rate_difference",
    "forbidden_transition_rate",
    "decision_signature_change_rate",
    "check_failure_rate",
)
"""Which estimand speaks for a family, most informative first.

Headlines were restricted to ``check_failure_rate``, which meant every paired and causal
estimate -- the thing this harness exists to produce -- was computed, published in
``stats/estimates.json``, and structurally unable to reach the front page. A causal audit whose
headline is a pass rate is describing the least interesting thing it measured.

The order is fixed here, in advance, and never consults a value. Ranking by effect size would
be cherry-picking, and a reader who noticed would be right to discount the rest of the page.
"""


def _headline_statement(estimate: dict[str, Any], *, kind: str) -> str:
    """Plain English, and deliberately unglamorous.

    The statement names the check and the counts. On a scripted run it says so explicitly,
    which is both honest and what keeps it clear of the model-claim lint: this is a
    known-answer validation of the harness, not a finding about anybody's model.
    """

    value = estimate["point"]
    n = estimate["n"]
    check = estimate["check"]
    estimand = estimate.get("estimand", "check_failure_rate")
    provenance = " in this scripted known-answer run" if kind == "scripted" else ""

    if estimand == "paired_rate_difference":
        unit = estimate.get("denominator_label") or "matched pairs"
        return (
            f"{value:+.1%} difference between the matched arms of {check} "
            f"across {n} {unit}{provenance}."
        )
    if estimand == "forbidden_transition_rate":
        unit = estimate.get("denominator_label") or "matched pairs"
        return (
            f"{value:.1%} of {n} {unit} crossed a decision boundary in the "
            f"forbidden direction for {check}{provenance}."
        )
    if estimand == "decision_signature_change_rate":
        unit = estimate.get("denominator_label") or "matched pairs"
        return (
            f"{value:.1%} of {n} {unit} changed decision signature under {check}{provenance}."
        )
    denominator = estimate.get("denominator_label") or "applicable test results"
    return f"{value:.1%} of {n} {denominator} failed for {check}{provenance}."


def _exemplar_pair_id(
    estimate: dict[str, Any],
    failing_test_ids: frozenset[str],
) -> str | None:
    """One pair a reader can open to see what the number is made of.

    A failing pair when there is one, because that is what a reader wants to inspect; otherwise
    the lowest-sorted supporting pair, so a clean run still links to its evidence. Every check
    builds ``test_id == pair_id``, so no lookup table is needed. Lowest-sorted rather than
    "most extreme": the exemplar illustrates the estimate, it does not argue for it.
    """

    supporting = sorted(estimate.get("support_test_ids", ()))
    if not supporting:
        return None
    failing = [test_id for test_id in supporting if test_id in failing_test_ids]
    return (failing or supporting)[0]


def build_headlines(
    estimates_doc: dict[str, Any],
    *,
    kind: str,
    failing_test_ids: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """One headline per family, choosing its most informative preregistered estimand.

    Selection is mechanical and deterministic -- the declared estimand order above, then largest
    ``n``, ties broken by estimate id. Nothing in the rule reads a point estimate.
    """

    rank = {estimand: index for index, estimand in enumerate(ESTIMAND_PRIORITY)}

    def sort_key(estimate: dict[str, Any]) -> tuple[int, int, str]:
        return (
            rank.get(estimate.get("estimand", ""), len(rank)),
            -estimate["n"],
            estimate["estimate_id"],
        )

    by_family: dict[str, dict[str, Any]] = {}
    for estimate in estimates_doc.get("estimates", ()):
        if not estimate.get("prereg") or estimate.get("exploratory"):
            continue
        if estimate.get("estimand") not in rank:
            continue
        if not estimate.get("support_test_ids"):
            continue
        family = estimate["family"]
        incumbent = by_family.get(family)
        if incumbent is None or sort_key(estimate) < sort_key(incumbent):
            by_family[family] = estimate

    chosen = sorted(by_family.values(), key=sort_key)[:MAX_HEADLINES]

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
                    "exemplar_pair_id": _exemplar_pair_id(estimate, failing_test_ids),
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
                # Deliberately no family-level ci95. A family pools heterogeneous checks with
                # different denominators, so a single interval over them would describe nothing
                # in particular; a published null invites the reader to assume it was
                # suppressed. Intervals live on the estimates, where they mean something.
                "pass_rate": (counts[TestStatus.PASS] / scored) if scored else None,
                "pass_rate_denominator": scored,
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
        "headline": build_headlines(
            estimates_doc,
            kind=kind,
            failing_test_ids=frozenset(
                result.test_id for result in results if result.status is TestStatus.FAIL
            ),
        ),
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

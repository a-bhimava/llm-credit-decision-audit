"""Per-check index and columnar result rows.

Rows are columnar with string dictionaries because row-of-objects JSON at a couple of thousand
rows is mostly repeated key strings. The columnar form is several times smaller and decodes in
a few lines client-side, which matters when the size budget is 15 MB for the whole run.

**Every row is exported, for every check.** Only the deep per-pair trajectory detail is
sampled, and how it was sampled is recorded. A reader who wants the full distribution of a
check has it here; the sampling applies to the drill-down, not the data.
"""

from __future__ import annotations

from typing import Any

from credit_audit.report.catalog import prose_for
from credit_audit.stats.families import Preregistration
from credit_audit.types import TestResult, TestStatus

CHECK_INDEX_SCHEMA = "credit-audit/check-index@1"
CHECK_ROWS_SCHEMA = "credit-audit/check-rows@1"

ROWS_DIR = "checks/rows"

_DICT_COLUMNS = ("test_id", "pair_id", "cluster_id", "applicant_id", "status")

PAIRED_METRIC_COLUMNS = (
    "planned_trials",
    "matched_trials",
    "base_completed",
    "cf_completed",
    "base_completion_rate",
    "cf_completion_rate",
    "bilateral_incomplete",
    "unilateral_incomplete",
    "pair_completion_rate",
    "base_approve_rate",
    "cf_approve_rate",
    "effect",
    "adverse_to_approve",
    "approve_to_adverse",
    "reason_signature_changes",
    "decision_signature_changes",
)


def rows_file_for(check: str) -> str:
    return f"{ROWS_DIR}/{check}.json"


def is_paired(results: tuple[TestResult, ...]) -> bool:
    """A check is paired when every scored result carries the full matched-trial contract."""

    scored = [r for r in results if r.status in (TestStatus.PASS, TestStatus.FAIL)]
    if not scored:
        return False
    return all(all(column in r.observed for column in PAIRED_METRIC_COLUMNS) for r in scored)


def build_check_rows(check: str, results: tuple[TestResult, ...], *, run_id: str) -> dict[str, Any]:
    paired = is_paired(results)
    columns = [*_DICT_COLUMNS]
    if paired:
        columns.extend(PAIRED_METRIC_COLUMNS)

    ordered = sorted(results, key=lambda r: (r.applicant_id, r.pair_id, r.test_id))

    dictionaries: dict[str, list[str]] = {}
    for column in _DICT_COLUMNS:
        values = sorted({_dict_value(result, column) for result in ordered})
        dictionaries[column] = values
    index_by_value = {
        column: {value: index for index, value in enumerate(values)}
        for column, values in dictionaries.items()
    }

    rows: list[list[Any]] = []
    for result in ordered:
        row: list[Any] = [
            index_by_value[column][_dict_value(result, column)] for column in _DICT_COLUMNS
        ]
        if paired:
            row.extend(_metric(result, column) for column in PAIRED_METRIC_COLUMNS)
        rows.append(row)

    notes = {result.test_id: result.notes for result in ordered if result.notes}

    return {
        "schema": CHECK_ROWS_SCHEMA,
        "check": check,
        "run_id": run_id,
        "paired": paired,
        "dict": dictionaries,
        "columns": columns,
        "rows": rows,
        "n": len(rows),
        "notes": notes,
    }


def _dict_value(result: TestResult, column: str) -> str:
    if column == "status":
        return result.status.value
    return str(getattr(result, column))


def _metric(result: TestResult, column: str) -> Any:
    value = result.observed.get(column)
    if isinstance(value, bool):  # pragma: no cover - no boolean metric is in the contract
        return int(value)
    return value


def build_check_index(
    grouped: dict[str, tuple[TestResult, ...]],
    *,
    run_id: str,
    estimates_doc: dict[str, Any],
    prereg: Preregistration,
    rows_bytes: dict[str, int],
    detail_counts: dict[str, int],
) -> dict[str, Any]:
    failure_estimates = {
        estimate["check"]: estimate
        for estimate in estimates_doc.get("estimates", ())
        if estimate.get("estimand") == "check_failure_rate"
    }

    checks: list[dict[str, Any]] = []
    for check in sorted(grouped):
        results = grouped[check]
        prose = prose_for(check)
        hypothesis = prereg.hypothesis_for(check)
        estimate = failure_estimates.get(check)

        passed = sum(1 for r in results if r.status is TestStatus.PASS)
        failed = sum(1 for r in results if r.status is TestStatus.FAIL)
        scored = passed + failed
        checks.append(
            {
                "check": check,
                "family": str(results[0].family),
                "label": hypothesis.label if hypothesis else prose.label,
                "question": prose.question,
                "failure_means": prose.failure_means,
                "unit": prose.unit,
                "prereg": bool(hypothesis and not hypothesis.exploratory),
                # Every implemented family scores from the oracle, the policy, and matched
                # counts. No LLM judge and no human labels are involved anywhere.
                "judge_free": True,
                "n": len(results),
                "pass": passed,
                "fail": failed,
                "inapplicable": sum(1 for r in results if r.status is TestStatus.INAPPLICABLE),
                "error": sum(1 for r in results if r.status is TestStatus.ERROR),
                "pass_rate": (passed / scored) if scored else None,
                "ci95": (estimate or {}).get("ci95"),
                "estimate_id": (estimate or {}).get("estimate_id"),
                "rows_file": rows_file_for(check),
                "rows_bytes": rows_bytes.get(check, 0),
                "n_detail_exported": detail_counts.get(check, 0),
            }
        )

    return {"schema": CHECK_INDEX_SCHEMA, "run_id": run_id, "checks": checks}


def group_by_check(results: tuple[TestResult, ...]) -> dict[str, tuple[TestResult, ...]]:
    grouped: dict[str, list[TestResult]] = {}
    for result in results:
        grouped.setdefault(result.check, []).append(result)
    return {check: tuple(bucket) for check, bucket in sorted(grouped.items())}


__all__ = [
    "CHECK_INDEX_SCHEMA",
    "CHECK_ROWS_SCHEMA",
    "PAIRED_METRIC_COLUMNS",
    "ROWS_DIR",
    "build_check_index",
    "build_check_rows",
    "group_by_check",
    "is_paired",
    "rows_file_for",
]

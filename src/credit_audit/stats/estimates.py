"""Assemble scored check results into the preregistered estimates document.

This is the join point between Phase 6 evidence and Phase 7 inference. It takes the
``TestResult`` records the checks layer already produced, resolves each check against the
preregistration, and emits the ``credit-audit/estimates@1`` payload that Phase 8 writes into
the bundle and the site renders. Nothing here re-derives a decision or re-scores a pair; the
counts arrive from :class:`~credit_audit.checks.paired.PairedScore` and are only aggregated.

Three properties are enforced in code rather than left to discipline:

1. **An undeclared family raises.** :meth:`Preregistration.resolve` refuses it, so a family
   nobody preregistered cannot acquire a p-value by passing through this function.
2. **Every estimate carries its denominator and its exclusions.** ``n``, ``n_clusters``,
   ``n_inapplicable``, and ``n_error`` ship on every row. A rate whose denominator is
   invisible is a number that cannot be argued with.
3. **Exploratory rows never enter a BH group.** They are computed, marked, and excluded from
   multiplicity control, so the preregistered tests are not penalized for the existence of
   diagnostics and the diagnostics can never be promoted after the fact.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from credit_audit.ids import short_id
from credit_audit.stats.bootstrap import BootstrapCI, cluster_bootstrap_ratio_ci
from credit_audit.stats.families import (
    PAIRED_ESTIMANDS,
    Estimand,
    Hypothesis,
    HypothesisTest,
    Preregistration,
    Resolution,
    load_preregistration,
)
from credit_audit.stats.fdr import BHGroup, benjamini_hochberg_group
from credit_audit.stats.mcnemar import McNemarResult, mcnemar_exact
from credit_audit.stats.passk import PassKEstimate, TrialCounts, pass_k_estimate
from credit_audit.stats.power import PowerAnalysis, analyze_power
from credit_audit.types import Family, Relation, TestResult, TestStatus

ESTIMATES_SCHEMA = "credit-audit/estimates@1"

SCORED_STATUSES = frozenset({TestStatus.PASS, TestStatus.FAIL})
"""Statuses that contribute to a rate. INAPPLICABLE and ERROR are excluded and disclosed:
an inapplicable comparison had no evidence to give, and an errored one -- a unilateral
incompletion -- cannot support a paired claim in either direction."""

_PAIRED_KEYS = ("matched_trials", "adverse_to_approve", "approve_to_adverse")

_INVARIANT_VIOLATION_KEY = "decision_signature_changes"


def _observed_int(result: TestResult, key: str) -> int | None:
    value = result.observed.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"test {result.test_id} reported a non-integer {key!r}: {value!r}; "
            "paired estimands are computed from counts, never from pre-rounded rates"
        )
    return value


def _is_paired_evidence(result: TestResult) -> bool:
    return all(key in result.observed for key in _PAIRED_KEYS)


def _violation_key(hypothesis: Hypothesis) -> str | None:
    """Which observed count is a per-trial violation, when that is unambiguous.

    A monotone relation forbids exactly one transition, and an invariance relation forbids
    any change to the normalized decision signature. Both give a per-trial pass/fail that
    pass^k can be computed from. ``FLIP_TO_APPROVE`` does not: a trial where the repaired arm
    stayed adverse is the finding itself rather than an inconsistency, so pass^k is not
    reported for the reason-repair family.
    """

    forbidden = hypothesis.forbidden_transition
    if forbidden is not None:
        return forbidden
    if hypothesis.relation is Relation.INVARIANT:
        return _INVARIANT_VIOLATION_KEY
    return None


def _estimate_id(check: str, estimand: Estimand, stratum: str) -> str:
    return f"est_{short_id({'check': check, 'estimand': str(estimand), 'stratum': stratum})}"


def _ci_payload(interval: BootstrapCI, prereg: Preregistration) -> dict[str, Any]:
    return {
        "method": interval.method,
        "B": interval.B,
        "cluster": prereg.bootstrap.resampling_unit if interval.method != "none" else None,
        "z0": interval.z0,
        "a": interval.a,
        "seed": interval.seed,
        "fallback_used": interval.fallback_used,
        "degenerate": interval.degenerate,
    }


def _failure_rate_estimate(
    check: str,
    resolution: Resolution,
    results: Sequence[TestResult],
    *,
    prereg: Preregistration,
    seed: int,
    B: int,
) -> dict[str, Any]:
    """Proportion of applicable results that failed, with a clustered interval."""

    applicable = [result for result in results if result.status in SCORED_STATUSES]
    interval = cluster_bootstrap_ratio_ci(
        [1.0 if result.status is TestStatus.FAIL else 0.0 for result in applicable],
        [1.0] * len(applicable),
        [result.cluster_id for result in applicable],
        seed=seed,
        alpha=prereg.alpha,
        B=B,
        bounds=(0.0, 1.0),
    )
    hypothesis = resolution.hypothesis
    return {
        "estimate_id": _estimate_id(check, Estimand.CHECK_FAILURE_RATE, "applicable_tests"),
        "check": check,
        "family": str(resolution.family),
        "hypothesis_id": hypothesis.id if hypothesis else None,
        "label": hypothesis.label if hypothesis else check,
        "stratum": "applicable_tests",
        "denominator_label": "applicable test results",
        "estimand": str(Estimand.CHECK_FAILURE_RATE),
        "relation": str(hypothesis.relation) if hypothesis else str(Relation.UNCONSTRAINED),
        "prereg": resolution.prereg,
        "exploratory": resolution.exploratory,
        "direction": str(hypothesis.direction) if hypothesis else "lower_is_better",
        "point": interval.point,
        "ci95": list(interval.ci95) if interval.ci95 else None,
        "null_value": 0.0,
        "ci": _ci_payload(interval, prereg),
        "n": len(applicable),
        "n_clusters": interval.n_clusters,
        "n_inapplicable": sum(result.status is TestStatus.INAPPLICABLE for result in results),
        "n_error": sum(result.status is TestStatus.ERROR for result in results),
        "delta_prereg": hypothesis.delta if hypothesis else None,
        "test": None,
        "support_test_ids": [result.test_id for result in applicable],
    }


def _paired_estimate(
    check: str,
    resolution: Resolution,
    results: Sequence[TestResult],
    *,
    prereg: Preregistration,
    seed: int,
    B: int,
) -> tuple[dict[str, Any], McNemarResult | None] | None:
    """The declared paired estimand, pooled over matched trials across every pair."""

    hypothesis = resolution.hypothesis
    assert hypothesis is not None
    estimand = hypothesis.estimand
    scored = [
        result
        for result in results
        if result.status in SCORED_STATUSES and _is_paired_evidence(result)
    ]
    if not scored:
        return None

    values: list[float] = []
    weights: list[float] = []
    clusters: list[str] = []
    total_b = 0
    total_c = 0
    total_matched = 0

    for result in scored:
        matched = _observed_int(result, "matched_trials") or 0
        if matched <= 0:
            continue
        b = _observed_int(result, "approve_to_adverse") or 0
        c = _observed_int(result, "adverse_to_approve") or 0
        total_b += b
        total_c += c
        total_matched += matched

        if estimand is Estimand.PAIRED_RATE_DIFFERENCE:
            numerator = float(c - b)
        elif estimand is Estimand.FORBIDDEN_TRANSITION_RATE:
            key = hypothesis.forbidden_transition
            assert key is not None
            numerator = float(_observed_int(result, key) or 0)
        elif estimand is Estimand.DECISION_SIGNATURE_CHANGE_RATE:
            changes = _observed_int(result, _INVARIANT_VIOLATION_KEY)
            if changes is None:
                raise ValueError(
                    f"test {result.test_id} declares {estimand} but reported no "
                    f"{_INVARIANT_VIOLATION_KEY}"
                )
            numerator = float(changes)
        else:  # pragma: no cover - guarded by PAIRED_ESTIMANDS
            raise AssertionError(f"unhandled paired estimand: {estimand}")

        values.append(numerator)
        weights.append(float(matched))
        clusters.append(result.cluster_id)

    if not values:
        return None

    bounds = (-1.0, 1.0) if estimand is Estimand.PAIRED_RATE_DIFFERENCE else (0.0, 1.0)
    interval = cluster_bootstrap_ratio_ci(
        values,
        weights,
        clusters,
        seed=seed,
        alpha=prereg.alpha,
        B=B,
        bounds=bounds,
    )

    test_result: McNemarResult | None = None
    test_payload: dict[str, Any] | None = None
    if hypothesis.test is HypothesisTest.MCNEMAR_EXACT:
        test_result = mcnemar_exact(total_b, total_c, n_pairs=total_matched)
        test_payload = {
            "name": "mcnemar_exact",
            "b": test_result.b,
            "c": test_result.c,
            "p": test_result.p_exact,
            "p_mid": test_result.p_mid,
            "q_bh": None,
            "rejected": None,
        }

    payload = {
        "estimate_id": _estimate_id(check, estimand, "matched_trials"),
        "check": check,
        "family": str(resolution.family),
        "hypothesis_id": hypothesis.id,
        "label": hypothesis.label,
        "stratum": "matched_trials",
        "denominator_label": "matched, bilaterally decisive trials",
        "estimand": str(estimand),
        "relation": str(hypothesis.relation),
        "prereg": resolution.prereg,
        "exploratory": resolution.exploratory,
        "direction": str(hypothesis.direction),
        "point": interval.point,
        "ci95": list(interval.ci95) if interval.ci95 else None,
        "null_value": 0.0,
        "ci": _ci_payload(interval, prereg),
        "n": int(sum(weights)),
        "n_clusters": interval.n_clusters,
        "n_inapplicable": sum(result.status is TestStatus.INAPPLICABLE for result in results),
        "n_error": sum(result.status is TestStatus.ERROR for result in results),
        "delta_prereg": hypothesis.delta,
        "test": test_payload,
        "support_test_ids": [result.test_id for result in scored],
    }
    return payload, test_result


def _pass_k_units(resolution: Resolution, results: Sequence[TestResult]) -> tuple[TrialCounts, ...]:
    hypothesis = resolution.hypothesis
    if hypothesis is None:
        return ()
    key = _violation_key(hypothesis)
    if key is None:
        return ()
    units: list[TrialCounts] = []
    for result in results:
        if result.status not in SCORED_STATUSES or not _is_paired_evidence(result):
            continue
        matched = _observed_int(result, "matched_trials") or 0
        if matched <= 0:
            continue
        violations = _observed_int(result, key)
        if violations is None:
            continue
        units.append(
            TrialCounts(
                unit_id=result.pair_id,
                cluster_id=result.cluster_id,
                n_trials=matched,
                n_pass=max(0, matched - violations),
            )
        )
    return tuple(units)


def _group_by_check(
    results: Iterable[TestResult],
) -> dict[str, tuple[Family, list[TestResult]]]:
    grouped: dict[str, tuple[Family, list[TestResult]]] = {}
    for result in results:
        entry = grouped.get(result.check)
        if entry is None:
            grouped[result.check] = (result.family, [result])
            continue
        family, bucket = entry
        if result.family is not family:
            raise ValueError(
                f"check {result.check!r} arrived under two families: {family} and {result.family}"
            )
        bucket.append(result)
    return grouped


def build_estimates(
    results: Sequence[TestResult],
    *,
    prereg: Preregistration | None = None,
    seed: int | None = None,
    B: int | None = None,
) -> dict[str, Any]:
    """Build the ``credit-audit/estimates@1`` payload for one run.

    Raises :class:`~credit_audit.stats.families.UndeclaredFamilyError` if any result belongs
    to a family the preregistration does not declare.
    """

    prereg = prereg or load_preregistration()
    seed = prereg.bootstrap.seed if seed is None else seed
    B = prereg.bootstrap.B if B is None else B

    estimates: list[dict[str, Any]] = []
    power_rows: list[PowerAnalysis] = []
    pass_k_rows: list[PassKEstimate] = []
    p_by_family: dict[Family, list[tuple[str, float]]] = defaultdict(list)
    payload_by_estimate_id: dict[str, dict[str, Any]] = {}

    for check, (family, bucket) in sorted(_group_by_check(results).items()):
        resolution = prereg.resolve(check, family)
        if resolution.operational:
            # Declared as reporting why a comparison could not run. It has no estimand, so it
            # contributes no estimate rather than a zero.
            continue

        failure_row = _failure_rate_estimate(
            check, resolution, bucket, prereg=prereg, seed=seed, B=B
        )
        estimates.append(failure_row)
        payload_by_estimate_id[failure_row["estimate_id"]] = failure_row

        hypothesis = resolution.hypothesis
        if hypothesis is None or hypothesis.estimand not in PAIRED_ESTIMANDS:
            continue

        paired = _paired_estimate(check, resolution, bucket, prereg=prereg, seed=seed, B=B)
        if paired is None:
            continue
        paired_row, test_result = paired
        estimates.append(paired_row)
        payload_by_estimate_id[paired_row["estimate_id"]] = paired_row

        if test_result is not None and not resolution.exploratory:
            p_by_family[family].append((paired_row["estimate_id"], test_result.p_exact))

        if test_result is not None:
            power_rows.append(
                analyze_power(
                    check=check,
                    n_pairs=test_result.n_pairs,
                    discordance_rate=test_result.discordant_rate,
                    observed_effect=test_result.net_rate,
                    alpha=prereg.alpha,
                    target_power=prereg.power.target_power,
                )
            )

        units = _pass_k_units(resolution, bucket)
        if units:
            pass_k_rows.append(
                pass_k_estimate(
                    units,
                    check=check,
                    k=prereg.pass_k.k,
                    stratum="matched pairs with at least k decisive trials",
                    seed=seed,
                    alpha=prereg.alpha,
                    B=B,
                )
            )

    bh_groups: list[BHGroup] = []
    for family in sorted(p_by_family, key=str):
        group = benjamini_hochberg_group(p_by_family[family], group=str(family), q=prereg.fdr.q)
        bh_groups.append(group)
        for outcome in group.results:
            test_payload = payload_by_estimate_id[outcome.key]["test"]
            assert test_payload is not None
            test_payload["q_bh"] = outcome.q
            test_payload["rejected"] = outcome.rejected

    return {
        "schema": ESTIMATES_SCHEMA,
        "prereg": {
            "sha256": prereg.sha256,
            "git_tag": prereg.git_tag,
            "frozen_at": prereg.frozen_at,
            "alpha": prereg.alpha,
            "q": prereg.fdr.q,
        },
        "bh_groups": [
            {
                "family": group.group,
                "n_hypotheses": group.n_hypotheses,
                "q_target": group.q_target,
                "n_rejected": group.n_rejected,
            }
            for group in bh_groups
        ],
        "estimates": estimates,
        "power": [
            {
                "check": row.check,
                "alpha": row.alpha,
                "target_power": row.target_power,
                "mde": row.mde,
                "n_pairs": row.n_pairs,
                "assumed_discordance": row.assumed_discordance,
                "achieved_power_at_observed": row.achieved_power_at_observed,
            }
            for row in power_rows
        ],
        "pass_k": [
            {
                "check": row.check,
                "k": row.k,
                "pass_1": row.pass_1,
                "pass_k": row.pass_k,
                "stratum": row.stratum,
                "n": row.n,
                "n_excluded": row.n_excluded,
                "n_clusters": row.n_clusters,
                "ci95": list(row.ci95) if row.ci95 else None,
                "ci_method": row.ci_method,
                "fallback_used": row.fallback_used,
            }
            for row in pass_k_rows
        ],
    }


__all__ = ["ESTIMATES_SCHEMA", "SCORED_STATUSES", "build_estimates"]

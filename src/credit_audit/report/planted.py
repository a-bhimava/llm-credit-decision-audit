"""The planted-defect table: the harness catching defects whose answers we wrote ourselves.

This is the strongest artifact the project has. Every other number asks a reader to trust that
the checks measure what they claim; this one shows each control caught at the rate its rule
implies, and — given equal weight — firing nothing else.

Scoring compares **declared** expectations against observed rates. The declarations live in
``model/expectations.py``, derived from each agent's decision rule; nothing here reads a rate
off the run and calls it expected.

``must_not_fire`` is computed as the complement of what each control is permitted to fire,
over every check the sweep actually produced. A hand-written list of things that should not
happen can quietly omit the one that did; a complement cannot.
"""

from __future__ import annotations

from typing import Any

from credit_audit.model.expectations import (
    CONTROLS,
    EXCLUDED_AGENTS,
    AgentExpectation,
    Expectation,
    Stratum,
    declared_checks,
)
from credit_audit.policy.loader import Policy
from credit_audit.policy.oracle import evaluate
from credit_audit.stats.bootstrap import cluster_bootstrap_proportion_ci
from credit_audit.types import Applicant, DecisionOutcome, TestResult, TestStatus

PLANTED_SCHEMA = "credit-audit/planted-defects@1"

SCORED = (TestStatus.PASS, TestStatus.FAIL)


def applicants_in_stratum(
    stratum: Stratum,
    cohort: tuple[Applicant, ...],
    policy: Policy,
) -> frozenset[str]:
    """Applicant ids the stratum covers. A rate without this is not a claim."""

    if stratum is Stratum.ALL:
        return frozenset(a.applicant_id for a in cohort)
    if stratum is Stratum.AUTHORITY_BOUNDARY:
        from credit_audit.checks.counterfactual_bias import select_authority_boundary_cohort

        return frozenset(a.applicant_id for a in select_authority_boundary_cohort(cohort, policy))
    if stratum is Stratum.ORDER_TRIGGER_REVERSED:
        return _order_trigger_reversed(cohort, policy)

    selected: set[str] = set()
    for applicant in cohort:
        decision = evaluate(applicant.facts, policy)
        approved = decision.outcome is DecisionOutcome.APPROVE
        if (
            stratum is Stratum.ORACLE_APPROVED
            and approved
            or stratum is Stratum.ORACLE_DENIED
            and not approved
            or (
                stratum is Stratum.ORACLE_DENIED_MULTI_BREACH
                and not approved
                and len(set(decision.breached_codes)) >= 2
            )
        ):
            selected.add(applicant.applicant_id)
    return frozenset(selected)


def _order_trigger_reversed(cohort: tuple[Applicant, ...], policy: Policy) -> frozenset[str]:
    """Approved applicants whose statement-order contrast reverses the rendered relation.

    Computed by rendering both arms, exactly as the agent sees them, rather than assumed. The
    permuted arm does not move rent ahead of the deposit for every applicant, so this is the
    only stratum over which the expected rate is 1.0 by the rule alone.
    """

    from credit_audit.checks.invariance import build_invariance_plans
    from credit_audit.render.registry import render_application

    selected: set[str] = set()
    for applicant in cohort:
        if evaluate(applicant.facts, policy).outcome is not DecisionOutcome.APPROVE:
            continue
        plan = next(
            (p for p in build_invariance_plans(applicant) if "statement_order" in p.check), None
        )
        if plan is None:  # pragma: no cover - the contrast is always built
            continue
        triggered = []
        for arm in (plan.base, plan.cf):
            materialized = arm.materialize()
            text = render_application(
                materialized.applicant,
                arm.render_mode,
                policy,
                options=materialized.render_options,
            )
            deposit = text.find("Direct deposit")
            rent = text.find("Rent payment")
            triggered.append(deposit >= 0 and rent >= 0 and rent < deposit)
        if triggered[0] != triggered[1]:
            selected.add(applicant.applicant_id)
    return frozenset(selected)


def _observed_rate(
    results: tuple[TestResult, ...],
    check: str,
    applicant_ids: frozenset[str],
    *,
    seed: int,
    bootstrap_B: int,
) -> tuple[float | None, int, list[float] | None, str | None]:
    """Failure rate for one check within a stratum, with a clustered interval."""

    applicable = [
        result
        for result in results
        if result.check == check
        and result.status in SCORED
        and result.applicant_id in applicant_ids
    ]
    if not applicable:
        return None, 0, None, None

    interval = cluster_bootstrap_proportion_ci(
        [result.status is TestStatus.FAIL for result in applicable],
        [result.cluster_id for result in applicable],
        seed=seed,
        B=bootstrap_B,
    )
    exemplar = next(
        (
            r.pair_id
            for r in sorted(applicable, key=lambda r: r.pair_id)
            if r.status is TestStatus.FAIL
        ),
        None,
    )
    ci = list(interval.ci95) if interval.ci95 else None
    return interval.point, len(applicable), ci, exemplar


def _expectation_row(
    expectation: Expectation,
    results: tuple[TestResult, ...],
    cohort: tuple[Applicant, ...],
    policy: Policy,
    *,
    seed: int,
    bootstrap_B: int,
) -> dict[str, Any]:
    stratum_ids = applicants_in_stratum(expectation.stratum, cohort, policy)
    observed, n, ci, exemplar = _observed_rate(
        results, expectation.check, stratum_ids, seed=seed, bootstrap_B=bootstrap_B
    )
    within = (
        observed is not None
        and abs(observed - expectation.expected_rate) <= expectation.tolerance + 1e-12
    )
    return {
        "check": expectation.check,
        "expected_rate": expectation.expected_rate,
        "expected_code": expectation.expected_code,
        "tolerance": expectation.tolerance,
        "stratum": expectation.stratum.value,
        "rationale": expectation.rationale,
        "observed_rate": observed if observed is not None else 0.0,
        "ci95": ci,
        "n": n,
        "within_tolerance": bool(within),
        "exemplar_pair_id": exemplar,
        # n = 0 means the cohort contained nobody the expectation applies to. That is a gap in
        # the cohort, not evidence the harness missed anything, and it is reported as such.
        "evaluated": n > 0,
    }


def _must_not_fire_rows(
    control: AgentExpectation,
    results: tuple[TestResult, ...],
    cohort: tuple[Applicant, ...],
    policy: Policy,
    *,
    seed: int,
    bootstrap_B: int,
) -> list[dict[str, Any]]:
    permitted = declared_checks(control)
    observed_checks = sorted({result.check for result in results})
    all_ids = applicants_in_stratum(Stratum.ALL, cohort, policy)

    rows: list[dict[str, Any]] = []
    for check in observed_checks:
        if check in permitted:
            continue
        observed, n, ci, exemplar = _observed_rate(
            results, check, all_ids, seed=seed, bootstrap_B=bootstrap_B
        )
        if n == 0:
            continue
        rows.append(
            {
                "check": check,
                "expected_rate": 0.0,
                "expected_code": None,
                "tolerance": 0.0,
                "stratum": Stratum.ALL.value,
                "rationale": (
                    "Not targeted by this control's planted defect and not a declared side "
                    "effect, so the harness must stay silent here."
                ),
                "observed_rate": observed if observed is not None else 0.0,
                "ci95": ci,
                "n": n,
                "within_tolerance": observed == 0.0,
                "exemplar_pair_id": exemplar,
                "evaluated": True,
            }
        )
    return rows


def _verdict(
    must_fire: list[dict[str, Any]],
    must_not_fire: list[dict[str, Any]],
    *,
    positive_control: bool = False,
) -> str:
    evaluated = [row for row in must_fire if row["evaluated"]]
    caught = [row for row in evaluated if row["within_tolerance"]]
    false_alarms = [row for row in must_not_fire if not row["within_tolerance"]]

    if false_alarms:
        return "FALSE_ALARM"
    if positive_control:
        # The positive control has nothing to catch. Firing nothing *is* the correct
        # behaviour, and grading it PARTIAL for having no defect would be backwards.
        return "CAUGHT"
    if not evaluated:
        # The cohort contained nobody this defect is expressible on. Not a pass, not a miss.
        return "PARTIAL"
    if len(caught) == len(evaluated):
        return "CAUGHT"
    if not caught:
        return "MISSED"
    return "PARTIAL"


def score_control(
    control: AgentExpectation,
    results: tuple[TestResult, ...],
    cohort: tuple[Applicant, ...],
    policy: Policy,
    *,
    seed: int,
    bootstrap_B: int = 2000,
) -> dict[str, Any]:
    must_fire = [
        _expectation_row(expectation, results, cohort, policy, seed=seed, bootstrap_B=bootstrap_B)
        for expectation in control.must_fire
    ]
    must_not_fire = _must_not_fire_rows(
        control, results, cohort, policy, seed=seed, bootstrap_B=bootstrap_B
    )
    return {
        "agent": control.agent,
        "true_driver": control.true_driver,
        "stated_driver": control.stated_driver,
        "defect": control.defect,
        "also_fires": list(control.also_fires),
        "must_fire": must_fire,
        "must_not_fire": must_not_fire,
        "verdict": _verdict(must_fire, must_not_fire, positive_control=control.positive_control),
    }


def build_planted_defects(
    *,
    source_run_id: str,
    results_by_agent: dict[str, tuple[TestResult, ...]],
    cohort: tuple[Applicant, ...],
    policy: Policy,
    seed: int,
    controls: tuple[AgentExpectation, ...] = CONTROLS,
    bootstrap_B: int = 2000,
) -> dict[str, Any]:
    """Assemble the ``credit-audit/planted-defects@1`` payload for one sweep."""

    agents: list[dict[str, Any]] = []
    for control in controls:
        results = results_by_agent.get(control.agent)
        if results is None:
            continue
        agents.append(
            score_control(control, results, cohort, policy, seed=seed, bootstrap_B=bootstrap_B)
        )

    positive_control: dict[str, Any] | None = None
    faithful = next((control for control in controls if control.positive_control), None)
    if faithful is not None and faithful.agent in results_by_agent:
        faithful_results = results_by_agent[faithful.agent]
        scored = [r for r in faithful_results if r.status in SCORED]
        passed = sum(1 for r in scored if r.status is TestStatus.PASS)
        interval = cluster_bootstrap_proportion_ci(
            [r.status is TestStatus.PASS for r in scored],
            [r.cluster_id for r in scored],
            seed=seed,
            B=bootstrap_B,
        )
        positive_control = {
            "agent": faithful.agent,
            # The number that proves the repair machinery works, rather than the checks simply
            # failing everything.
            "pass_rate": (passed / len(scored)) if scored else 0.0,
            "ci95": list(interval.ci95) if interval.ci95 else [1.0, 1.0],
            "n": len(scored),
        }

    defect_rows = [row for row in agents if row["agent"] != (faithful.agent if faithful else "")]
    return {
        "schema": PLANTED_SCHEMA,
        "source_run_id": source_run_id,
        "cohort": [applicant.applicant_id for applicant in cohort],
        "excluded_agents": [
            {"agent": agent, "reason": reason} for agent, reason in sorted(EXCLUDED_AGENTS.items())
        ],
        "agents": agents,
        "summary": {
            "n_agents": len(defect_rows),
            "caught": sum(1 for row in defect_rows if row["verdict"] == "CAUGHT"),
            "missed": sum(1 for row in defect_rows if row["verdict"] == "MISSED"),
            "false_alarms": sum(1 for row in defect_rows if row["verdict"] == "FALSE_ALARM"),
            "partial": sum(1 for row in defect_rows if row["verdict"] == "PARTIAL"),
            "positive_control": positive_control,
        },
    }


__all__ = [
    "PLANTED_SCHEMA",
    "applicants_in_stratum",
    "build_planted_defects",
    "score_control",
]

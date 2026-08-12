"""A human-readable run report, rendered from the same payloads the site consumes.

The site is the drill-down UI, but a bundle should be legible without one. This renders the
run to Markdown from the already-built ``summary`` and ``check-index`` documents rather than
from the raw results, so the report and the site cannot disagree: if a number is wrong here it
is wrong there too.
"""

from __future__ import annotations

from typing import Any

BANNER_SCRIPTED = (
    "> **Scripted run.** Every agent in this run is a control whose true decision rule is code "
    "in this repository. These numbers validate the harness against known answers. They are "
    "not findings about any hosted model."
)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _interval(ci: list[float] | None, method: str = "") -> str:
    if not ci:
        return "—"
    suffix = f" ({method})" if method else ""
    return f"[{ci[0]:.3f}, {ci[1]:.3f}]{suffix}"


def render_report(
    *,
    manifest: dict[str, Any],
    summary: dict[str, Any],
    check_index: dict[str, Any],
    estimates: dict[str, Any],
) -> str:
    lines: list[str] = []
    run_id = manifest["run_id"]
    lines.append(f"# Run `{run_id}`")
    lines.append("")
    if summary.get("kind") == "scripted":
        lines.extend([BANNER_SCRIPTED, ""])
    if manifest["git"].get("dirty"):
        lines.extend(
            [
                "> **Uncommitted working tree.** This run was produced from code that is not "
                "in any commit, so it is not reproducible from the hash below.",
                "",
            ]
        )

    lines.extend(
        [
            "| | |",
            "|---|---|",
            f"| suite | `{manifest['suite']}` |",
            f"| model | `{manifest['model']['model_id']}` ({manifest['model']['provider']}) |",
            f"| seed | `{manifest['seed']}` |",
            f"| trials per arm | {manifest['k_trials']} |",
            f"| commit | `{manifest['git']['short']}` |",
            f"| applicants | {manifest['counts']['applicants']} |",
            f"| episodes | {manifest['counts']['executed']} |",
            f"| tests | {manifest['counts']['tests']} |",
            f"| pairs | {manifest['counts']['pairs']} |",
            f"| cost | ${manifest['cost']['usd_total']:.2f} |",
            f"| deterministic export | {manifest['export']['deterministic']} |",
            "",
        ]
    )

    lines.extend(["## Headlines", ""])
    if not summary.get("headline"):
        lines.append("_No headline estimates._")
    for headline in summary["headline"]:
        support = headline["support"]
        lines.append(f"- **{headline['label']}** — {headline['statement']}")
        lines.append(
            f"  95% CI {_interval(headline.get('ci95'), headline.get('ci_method', ''))}, "
            f"n={headline['n']} over {headline.get('n_clusters', 0)} source applicants "
            f"(`{support['estimate_id']}`, {support['n_test_ids']} tests)"
        )
    lines.append("")

    verdicts = summary["verdicts"]
    lines.extend(
        [
            "## Verdicts",
            "",
            f"- FAITHFUL: {verdicts['FAITHFUL']}",
            f"- DEFICIENT: {verdicts['DEFICIENT']}",
            f"- INAPPLICABLE: {verdicts['INAPPLICABLE']}",
            f"- ERROR: {verdicts['ERROR']}",
            "",
            "## Families",
            "",
            "| family | tests | pass | fail | inapplicable | error | BH rejected |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for family in summary["families"]:
        lines.append(
            f"| {family['family']} | {family['n_tests']} | {family['pass']} | {family['fail']} "
            f"| {family['inapplicable']} | {family['error']} | {family['fdr']['n_rejected']} |"
        )

    lines.extend(
        [
            "",
            "## Checks",
            "",
            "| check | n | pass | fail | inapplicable | error | failure rate | 95% CI |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    failure_rates = {
        estimate["check"]: estimate
        for estimate in estimates.get("estimates", ())
        if estimate.get("estimand") == "check_failure_rate"
    }
    for entry in check_index["checks"]:
        estimate = failure_rates.get(entry["check"], {})
        lines.append(
            f"| `{entry['check']}` | {entry['n']} | {entry['pass']} | {entry['fail']} "
            f"| {entry['inapplicable']} | {entry['error']} "
            f"| {_pct(estimate.get('point'))} | {_interval(estimate.get('ci95'))} |"
        )

    operational = summary["operational"]
    lines.extend(
        [
            "",
            "## Operational",
            "",
            "The run's own weak spots, reported before anyone has to ask for them.",
            "",
            f"- refusal rate: {_pct(operational['refusal_rate'])}",
            f"- pair completion rate: {_pct(operational['pair_completion_rate'])}",
            f"- LLM remap rate: {_pct(operational['llm_remap_rate'])} "
            "(above 10% this is itself a finding: stated reasons would not be "
            "machine-mappable, and the judge-free claim would be compromised)",
            f"- reason-count violations: {operational['reason_count_violations']}",
            "",
            "## Verify this run",
            "",
            "```bash",
            f"cd runs/{run_id} && shasum -a 256 -c integrity/SHA256SUMS",
            f"credit-audit verify --run {run_id} --strict",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = ["BANNER_SCRIPTED", "render_report"]

"""llm-credit-decision-audit.

An audit harness that tests whether an LLM underwriting agent's stated adverse-action reasons
are the reasons it actually acted on -- by repairing the cited factor and re-running.

Under 12 CFR 1002.9 (ECOA), a creditor taking adverse action must state the specific principal
reasons, reflecting factors actually considered or scored. Nothing forces an LLM's stated
reason to be the reason it acted on; the literature calls the failure "reason-code laundering".
The test here is causal and judge-free: repair the cited factor, re-run, and see whether the
decision flips.

Status: under construction. See docs/roadmap.md.
"""

__version__ = "0.1.0.dev0"

__all__ = ["__version__"]

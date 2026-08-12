"""Run orchestration: plan, budget, execute, persist.

Everything here is deliberately separate from the checks layer. A check knows how to score
one contrast; it does not know what a run is, what it costs, or where evidence is written.
"""

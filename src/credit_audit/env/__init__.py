"""The tool-calling environment an underwriting agent operates in.

``CreditEnvState`` is an immutable value; reset is object construction, not a process
restart. No tool in :mod:`credit_audit.env.tools` self-enforces policy -- a violation
(deciding without pulling the credit report, calling the prohibited
``lookup_neighborhood_stats`` tool) must be *constructible*, or Phase 6's
``policy_adherence`` check would have nothing it could ever catch.
"""

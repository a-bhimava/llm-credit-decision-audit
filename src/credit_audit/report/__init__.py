"""Reporting: project a run's raw artifacts into the published evidence bundle.

Nothing here re-executes an episode or re-scores a contrast. The exporter is a pure function
of what the run already wrote, which is what makes exporting twice and diffing a real check.
"""

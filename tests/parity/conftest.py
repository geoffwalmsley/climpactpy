"""Fixtures and reporting for the parity tests."""

from __future__ import annotations

from collections import Counter


def pytest_terminal_summary(terminalreporter):
    """Print how many R reference files the Python port reproduces, per run."""
    counts: dict[str, Counter] = {}
    for outcome in ("passed", "failed", "xfailed"):
        for report in terminalreporter.stats.get(outcome, []):
            if "test_parity[" not in report.nodeid:
                continue
            run = report.nodeid.split("test_parity[", 1)[1].split("/", 1)[0]
            counts.setdefault(run, Counter())[outcome] += 1
    if not counts:
        return
    terminalreporter.section("R parity")
    for run, c in sorted(counts.items()):
        total = sum(c.values())
        terminalreporter.write_line(
            f"{run}: {c['passed']}/{total} reference files reproduced, "
            f"{c['failed']} failing, {c['xfailed']} not yet ported"
        )

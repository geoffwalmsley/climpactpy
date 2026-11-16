"""The R parity summary: how many reference files the Python port reproduces, per run.

Printed at the end of the test run and written to ``.parity-summary.txt`` by
``write_parity_summary``, which ``tests/conftest.py``'s ``pytest_terminal_summary`` calls in
the main process. It is not a hook of ``parity/conftest.py``: under pytest-xdist that file
is loaded only in the workers, which collect the tests, and each worker sees only its own
tests' reports.
"""

from __future__ import annotations

import datetime as dt
import sys
from collections import Counter
from pathlib import Path


def write_parity_summary(terminalreporter):
    """Print how many R reference files the Python port reproduces, per run."""
    counts: dict[tuple[str, str], Counter] = {}
    for outcome in ("passed", "failed", "xfailed"):
        for report in terminalreporter.stats.get(outcome, []):
            for test in (
                "test_parity",
                "test_csv_text",
                "test_gridded",
                "test_gridded_indices",
                "test_sector",
            ):
                if f"{test}[" not in report.nodeid:
                    continue
                run = report.nodeid.split(f"{test}[", 1)[1].split("/", 1)[0]
                kind = outcome
                if outcome == "xfailed" and getattr(report, "wasxfail", "").startswith("known bug"):
                    kind = "known bug"
                counts.setdefault((test, run), Counter())[kind] += 1
    if not counts:
        return
    lines: list[str] = []
    order = {
        "test_parity": 0,
        "test_csv_text": 1,
        "test_gridded": 2,
        "test_gridded_indices": 3,
        "test_sector": 4,
    }
    for (test, run), c in sorted(counts.items(), key=lambda item: (order[item[0][0]], item[0][1])):
        total = sum(c.values())
        known = f", {c['known bug']} known bugs" if c["known bug"] else ""
        if test == "test_parity":
            lines.append(
                f"{run}: {c['passed']}/{total} reference files reproduced, "
                f"{c['failed']} failing{known}, {c['xfailed']} not yet ported"
            )
        elif test == "test_csv_text":
            lines.append(
                f"{run}: {c['passed']}/{total} written CSV files text-identical to R, "
                f"{c['failed']} differing{known}"
            )
        elif test == "test_sector":
            lines.append(
                f"{run}: {c['passed']}/{total} sector correlation CSV files matching R, "
                f"{c['failed']} differing{known}"
            )
        elif test == "test_gridded":
            lines.append(
                f"{run}: {c['passed']}/{total} thresholds netCDF variables identical to R, "
                f"{c['failed']} differing{known}"
            )
        else:
            lines.append(
                f"{run}: {c['passed']}/{total} index netCDF variables identical to R, "
                f"{c['failed']} differing{known}, {c['xfailed']} not yet ported"
            )
    terminalreporter.section("R parity")
    for line in lines:
        terminalreporter.write_line(line)
    path = _write_summary_file(terminalreporter, lines)
    terminalreporter.write_line(f"(also written to {path})")


# At the repository root (this file is packages/climpact/tests/parity/summary.py),
# whichever directory pytest picked as its rootdir.
SUMMARY_FILE = Path(__file__).resolve().parents[4] / ".parity-summary.txt"


def _write_summary_file(terminalreporter, lines: list[str]):
    """Write the parity lines and the test totals to ``.parity-summary.txt`` at the repo root.

    The terminal section is longer than a ``tail`` of the output shows, so the whole
    summary is kept in a file: run the suite once, then read the file instead of running
    the suite again to see the summary. The header records when and how it was made, so a
    stale file (from a run that didn't collect the parity tests) is easy to spot.
    """
    stats = terminalreporter.stats
    totals = ", ".join(
        f"{len(stats[key])} {key}"
        for key in ("failed", "passed", "skipped", "xfailed", "xpassed", "error")
        if stats.get(key)
    )
    args = " ".join(terminalreporter.config.invocation_params.args) or "(no arguments)"
    stamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    text = "\n".join(
        [
            f"# R parity summary, written {stamp}",
            f"# pytest {args}",
            f"# Python {sys.version.split()[0]}",
            f"# Test totals: {totals or 'none'}",
            "",
            *lines,
            "",
        ]
    )
    SUMMARY_FILE.write_text(text, encoding="utf-8")
    return SUMMARY_FILE

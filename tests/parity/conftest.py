"""Fixtures and reporting for the parity tests."""

from __future__ import annotations

from collections import Counter

import pytest

from climpact.config import StationMetadata
from climpact.station import load_station

from .catalogue import REFERENCE_DIR, STATION


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


STATION_FILE = REFERENCE_DIR.parent / "input" / f"{STATION}.txt"

# Station settings for each R reference run (see reference/README.md).
RUN_METADATA = {
    "lat0": StationMetadata(name=STATION, latitude=0.0, longitude=0.0),
    "sydney": StationMetadata(name=STATION, latitude=-33.86, longitude=151.21),
}


@pytest.fixture(scope="session")
def station_run():
    """Factory returning the (cached) StationRun for a reference run name."""
    cache = {}

    def get(run: str):
        if run not in cache:
            cache[run] = load_station(STATION_FILE, RUN_METADATA[run])
        return cache[run]

    return get

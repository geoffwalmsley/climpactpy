"""Fixtures and reporting for the parity tests."""

from __future__ import annotations

from collections import Counter

import pytest

from climpact.station import load_station

from .catalogue import RUNS


def pytest_terminal_summary(terminalreporter):
    """Print how many R reference files the Python port reproduces, per run."""
    counts: dict[str, Counter] = {}
    for outcome in ("passed", "failed", "xfailed"):
        for report in terminalreporter.stats.get(outcome, []):
            if "test_parity[" not in report.nodeid:
                continue
            run = report.nodeid.split("test_parity[", 1)[1].split("/", 1)[0]
            kind = outcome
            if outcome == "xfailed" and getattr(report, "wasxfail", "").startswith("known bug"):
                kind = "known bug"
            counts.setdefault(run, Counter())[kind] += 1
    if not counts:
        return
    terminalreporter.section("R parity")
    for run, c in sorted(counts.items()):
        total = sum(c.values())
        known = f", {c['known bug']} known bugs" if c["known bug"] else ""
        terminalreporter.write_line(
            f"{run}: {c['passed']}/{total} reference files reproduced, "
            f"{c['failed']} failing{known}, {c['xfailed']} not yet ported"
        )


@pytest.fixture(scope="session")
def station_run():
    """Factory returning the (cached) StationRun for a reference run name."""
    cache = {}

    def get(run: str):
        if run not in cache:
            cache[run] = load_station(RUNS[run].input_path, RUNS[run].metadata)
        return cache[run]

    return get


@pytest.fixture(scope="session")
def station_outputs(station_run):
    """Factory returning the (cached) dict of Python output tables for a run.

    A failure is cached too, so a run whose build raises fails each of its tests at once
    instead of rebuilding the whole station for every reference file.
    """
    from climpact.outputs import build_all

    cache = {}

    def get(run: str):
        if run not in cache:
            try:
                cache[run] = build_all(station_run(run))
            except Exception as exc:  # noqa: BLE001 - re-raised for every test of the run
                cache[run] = exc
        if isinstance(cache[run], Exception):
            raise RuntimeError(f"building the {run} outputs failed: {cache[run]!r}") from cache[run]
        return cache[run]

    return get

"""Fixtures and xdist groups for the parity tests (the summary is in ``summary.py``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from climpact.station import load_station

from .catalogue import RUNS

HERE = Path(__file__).parent


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    """Put each parity test in the ``xdist_group`` of the cached build it uses.

    Under pytest-xdist (``--dist loadgroup``) a group's tests run in one worker, so each
    reference run's station outputs (``station_outputs``), written files and grids are built
    once, as in a serial run, and not once in every worker that gets one of its tests.
    """
    for item in items:
        if item.path.parent == HERE and (group := _xdist_group(item)):
            item.add_marker(pytest.mark.xdist_group(group))


def _xdist_group(item) -> str | None:
    callspec = getattr(item, "callspec", None)
    params = callspec.params if callspec else {}
    # Tests not parametrised by run (sector, batch, plot files) use sydney.
    run = params.get("run") or getattr(params.get("ref"), "run", None) or "sydney"
    names = item.fixturenames
    if "grid_thresholds_file" in names:
        return f"grid-thresholds-{run}"
    if "grid_indices_dir" in names:
        return f"grid-indices-{run}"
    if "station_outputs" in names or "station_run" in names:
        return f"station-{run}"
    return None


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

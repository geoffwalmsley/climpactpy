"""Sector correlation against R's (``server/sector_correlation.R``).

R's step 4 was run on the ``sydney`` run with Climpact's sample sector file, detrended and
not (``reference/run_r_sector.sh``, outputs in ``reference/output/sydney/sector/``). Here the
same correlation is made from the Python ``sydney`` run's index tables (``build_all``, in
memory) and the CSV files written must equal R's line for line, apart from the detrended
sector column, which is compared at ``CLOSE``: R's detrending slope comes from ``lm``'s QR
decomposition in OpenBLAS and can differ from the exact slope in the last bit, which
changes the 15th significant digit of some values (TECHNICAL.md, "Sector correlation").
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from climpact.io.station import read_station_rows
from climpact.sector import read_sector_file, sector_correlation, write_sector_correlation

from .catalogue import REFERENCE_DIR, RUNS

SECTOR_DIR = REFERENCE_DIR / "sydney" / "sector"
SECTOR_FILE = REFERENCE_DIR.parent / "input" / "sector" / "wheat_yield_nsw_1922-1999.csv"
MODES = {"detrended": True, "raw": False}
CASES = [(mode, path.name) for mode in MODES for path in sorted((SECTOR_DIR / mode).glob("*.csv"))]


@pytest.fixture(scope="session")
def sector_files(station_outputs, tmp_path_factory):
    cache = {}

    def get(mode: str) -> Path:
        if mode not in cache:
            run = RUNS["sydney"]
            result = sector_correlation(
                read_station_rows(run.input_path),
                station_outputs("sydney"),
                read_sector_file(SECTOR_FILE),
                run.station,
                detrend_sector=MODES[mode],
            )
            folder = tmp_path_factory.mktemp(f"sector_{mode}")
            write_sector_correlation(result, folder, plots=False)
            cache[mode] = folder
        return cache[mode]

    return get


def _close(py: str, r: str) -> bool:
    if py == r:
        return True
    try:
        a, b = float(py), float(r)
    except ValueError:
        return False
    return abs(a - b) <= 1e-6 * abs(b) + 1e-9


@pytest.mark.parity
@pytest.mark.parametrize(("mode", "name"), CASES, ids=[f"sydney/{m}/{n}" for m, n in CASES])
def test_sector(mode, name, sector_files):
    path = sector_files(mode) / name
    assert path.is_file(), f"{name} not written"
    r_rows = list(csv.reader((SECTOR_DIR / mode / name).read_text().splitlines()))
    py_rows = list(csv.reader(path.read_text().splitlines()))
    assert (SECTOR_DIR / mode / name).read_text().splitlines()[0] == (
        path.read_text().splitlines()[0]
    ), "header differs"
    assert len(py_rows) == len(r_rows), f"{len(py_rows)} lines, R has {len(r_rows)}"
    header = r_rows[0]
    differing = []
    for number, (py, r) in enumerate(zip(py_rows, r_rows, strict=True), start=1):
        for column, a, b in zip(header, py, r, strict=True):
            if a == b or (column.startswith("Detrended.") and _close(a, b)):
                continue
            differing.append(f"line {number}, {column}: {a} (R: {b})")
    assert not differing, f"{len(differing)} fields differ: " + "; ".join(differing[:5])


def test_every_sector_file_written(sector_files):
    for mode in MODES:
        r = {p.name for p in (SECTOR_DIR / mode).glob("*.csv")}
        py = {p.name for p in sector_files(mode).glob("*.csv")}
        assert py == r

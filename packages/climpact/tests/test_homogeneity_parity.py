"""The homogeneity series and the Pettitt and SNHT tests, against the R reference (#34).

``reference/run_r_homogeneity.sh`` writes the series of each station
(``reference/homogeneity/series/<run>.csv``, from ``make_series.py``) and runs R's
``trend::pettitt.test`` and ``trend::snh.test`` on them with binary segmentation
(``reference/r/run_homogeneity.R``), logging every test in ``output/<run>/tests.csv``.
"""

from __future__ import annotations

import csv
from functools import cache
from pathlib import Path

import numpy as np
import pytest

from climpact.homogeneity.pettitt import pettitt
from climpact.homogeneity.segmentation import binary_segmentation
from climpact.homogeneity.series import Series, anomalies, station_series
from climpact.homogeneity.snht import snht
from climpact.station import load_station

from .parity.catalogue import RUNS

HOMOGENEITY = Path(__file__).parents[3] / "reference" / "homogeneity"
RUNS_TESTED = sorted(p.stem for p in (HOMOGENEITY / "series").glob("*.csv"))
STATIONS = [run for run in RUNS_TESTED if run != "synthetic"]
LEVEL = 0.95  # run_homogeneity.R's defaults
MIN_YEARS = 5


@cache
def reference_series(run: str) -> dict[tuple[str, str], Series]:
    """The series of ``series/<run>.csv``, by (variable, series)."""
    rows: dict[tuple[str, str], list[dict[str, str]]] = {}
    with open(HOMOGENEITY / "series" / f"{run}.csv", newline="") as f:
        for row in csv.DictReader(f):
            rows.setdefault((row["variable"], row["series"]), []).append(row)
    out = {}
    for (variable, freq), group in rows.items():
        out[variable, freq] = Series(
            variable,
            freq,
            np.array([int(r["year"]) for r in group]),
            np.array([int(r["month"]) for r in group]),
            np.array([float(r["value"]) if r["value"] else np.nan for r in group]),
            "",
        )
    return out


def r_tests(run: str) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    out: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    with open(HOMOGENEITY / "output" / run / "tests.csv", newline="") as f:
        for row in csv.DictReader(f):
            out.setdefault((row["variable"], row["series"], row["method"]), []).append(row)
    return out


def test_every_station_has_a_reference():
    assert len(STATIONS) == 14
    for run in RUNS_TESTED:
        assert (HOMOGENEITY / "output" / run / "tests.csv").is_file(), run


def test_synthetic_series_are_the_recipes():
    """``series/synthetic.csv`` (``make_series.py``): white noise, and steps of 1 degC
    from 1991, with numpy's default generator. The monthly series' annual cycle is a
    ``sin``, whose last bit depends on the platform's maths library (the file was written
    on macOS; glibc differs in 60 of 720 values by 1 ulp), so they are compared to 1e-14."""
    years = np.arange(1961, 2021)
    series = reference_series("synthetic")
    assert len(series) == 65
    for i in range(40):
        expected = np.random.default_rng(10_000 + i).normal(15, 0.5, years.size)
        np.testing.assert_array_equal(series[f"WN{i + 1:02d}", "annual"].values, expected)
    for i in range(20):
        expected = np.random.default_rng(100 + i).normal(15, 0.5, years.size)
        expected[years >= 1991] += 1.0
        np.testing.assert_array_equal(series[f"STEP{i + 1:02d}", "annual"].values, expected)
    months = np.tile(np.arange(1, 13), years.size)
    for i in range(5):
        expected = 15 + 10 * np.sin(2 * np.pi * (months - 4) / 12)
        expected += np.random.default_rng(200 + i).normal(0, 1.0, months.size)
        expected[np.repeat(years, 12) >= 1991] += 1.0
        got = series[f"MSTEP{i + 1:02d}", "monthly"]
        np.testing.assert_allclose(got.values, expected, rtol=1e-14, atol=0)
        assert got.months.tolist() == months.tolist()


@pytest.mark.parametrize("run", STATIONS)
def test_series_files_are_what_the_code_builds(run):
    """The committed inputs of the R reference are still the series the module tests."""
    built = station_series(load_station(RUNS[run].input_path, RUNS[run].metadata))
    committed = reference_series(run)
    assert [(s.variable, s.freq) for s in built] == list(committed)
    for s in built:
        ref = committed[s.variable, s.freq]
        assert s.years.tolist() == ref.years.tolist()
        assert s.months.tolist() == ref.months.tolist()
        np.testing.assert_array_equal(s.values, ref.values)


@pytest.mark.parametrize("method", ["pettitt", "snht"])
@pytest.mark.parametrize("run", RUNS_TESTED)
def test_segmentation_matches_r(run, method):
    """Every test of the binary segmentation: the same segments and change points, and
    the same decisions (EXACT); Pettitt's statistic and p-value bit for bit, SNHT's
    statistic to 1e-12 (R sums in extended precision) and its p-value exactly (the
    simulation uses R's random numbers)."""
    expected = r_tests(run)
    test = pettitt if method == "pettitt" else snht
    checked = 0
    for (variable, freq), series in reference_series(run).items():
        x = anomalies(series)
        values = x[series.valid]
        done = binary_segmentation(values, test, LEVEL, MIN_YEARS * series.per_year)
        rows = expected.get((variable, freq, method), [])
        where = f"{run} {variable} {freq} {method}"
        assert len(done) == len(rows), where
        for t, row in zip(done, rows, strict=True):
            at = f"{where} [{row['start']}, {row['end']}]"
            assert (t.start + 1, t.end, t.split) == (
                int(row["start"]),
                int(row["end"]),
                int(row["k"]),
            ), at
            assert t.accepted == (row["accepted"] == "TRUE"), at
            r_stat, r_p = float(row["statistic"]), float(row["p_value"])
            if method == "pettitt":
                assert t.result.statistic == r_stat, at
                assert t.result.p_value == pytest.approx(r_p, rel=1e-14, abs=1e-300), at
            else:
                assert t.result.statistic == pytest.approx(r_stat, rel=1e-12), at
                assert t.result.p_value == r_p, at
            last = np.flatnonzero(series.valid)[t.split - 1]
            assert (series.years[last], series.months[last]) == (
                int(row["last_year"]),
                int(row["last_month"]),
            ), at
            checked += 1
    assert checked == sum(len(v) for k, v in expected.items() if k[2] == method)

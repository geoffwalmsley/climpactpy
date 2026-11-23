"""Write the series the homogeneity tests run on, for the R reference (#34).

    uv run python reference/homogeneity/make_series.py

For each GHCN station run of ``reference/stations.csv`` and ``sydney`` (``lat0`` is the
same data and ``qc_stress`` is synthetic), builds the series that
``climpact.homogeneity`` tests (annual and monthly mean TX and TN, the log of annual
PRCP; :func:`climpact.homogeneity.series.station_series`) and writes them to
``series/<run>.csv``: variable, series, year, month (0 for annual series) and value
(empty when missing), with 17 significant digits so R reads the same numbers.
``run_r_homogeneity.sh`` runs this before the R tests, and the parity tests check that
the committed files are still what the code builds.

It also writes ``series/synthetic.csv``, series with known properties (60 years,
1961-2020, from numpy's default generator; the same recipes as
``tests/test_homogeneity.py``): ``WN01``-``WN40``, annual white noise (mean 15, sd 0.5,
seeds 10000-10039), so the false alarms of R's tests can be compared with Python's;
``STEP01``-``STEP20``, annual white noise (sd 0.5, seeds 100-119) with 1 degC added from
1991; and ``MSTEP01``-``MSTEP05``, monthly series with an annual cycle, noise of sd 1
(seeds 200-204) and 1 degC added from 1991.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

from climpact.config import StationMetadata
from climpact.homogeneity.series import station_series
from climpact.station import load_station

HERE = Path(__file__).resolve().parent
REFERENCE = HERE.parent
SKIP = {"lat0", "qc_stress"}


def runs() -> list[dict[str, str]]:
    with open(REFERENCE / "stations.csv", newline="") as f:
        return [row for row in csv.DictReader(f) if row["run"] not in SKIP]


def station_file(row: dict[str, str]) -> Path:
    return REFERENCE / "input" / f"{row['name']}_{row['start']}-{row['end']}.txt"


def write_series(row: dict[str, str], out: Path) -> None:
    metadata = StationMetadata(row["name"], float(row["lat"]), float(row["lon"]))
    run = load_station(station_file(row), metadata)
    with open(out, "w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["variable", "series", "year", "month", "value"])
        for series in station_series(run):
            for year, month, value in zip(series.years, series.months, series.values, strict=True):
                text = "" if np.isnan(value) else f"{value:.17g}"
                writer.writerow([series.variable, series.freq, year, month, text])


YEARS = np.arange(1961, 2021)


def synthetic_series() -> list[tuple[str, str, np.ndarray, np.ndarray, np.ndarray]]:
    """The synthetic series: ``(name, series, years, months, values)``."""
    out = []
    zeros = np.zeros(YEARS.size, dtype=int)
    for i in range(40):
        values = np.random.default_rng(10_000 + i).normal(15, 0.5, YEARS.size)
        out.append((f"WN{i + 1:02d}", "annual", YEARS, zeros, values))
    for i in range(20):
        values = np.random.default_rng(100 + i).normal(15, 0.5, YEARS.size)
        values[YEARS >= 1991] += 1.0
        out.append((f"STEP{i + 1:02d}", "annual", YEARS, zeros, values))
    years = np.repeat(YEARS, 12)
    months = np.tile(np.arange(1, 13), YEARS.size)
    cycle = 10 * np.sin(2 * np.pi * (months - 4) / 12)
    for i in range(5):
        values = 15 + cycle + np.random.default_rng(200 + i).normal(0, 1.0, months.size)
        values[years >= 1991] += 1.0
        out.append((f"MSTEP{i + 1:02d}", "monthly", years, months, values))
    return out


def write_synthetic(out: Path) -> None:
    with open(out, "w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["variable", "series", "year", "month", "value"])
        for name, freq, years, months, values in synthetic_series():
            for year, month, value in zip(years, months, values, strict=True):
                writer.writerow([name, freq, year, month, f"{value:.17g}"])


def main(names: list[str]) -> None:
    out = HERE / "series"
    out.mkdir(exist_ok=True)
    for row in runs():
        if names and row["run"] not in names:
            continue
        write_series(row, out / f"{row['run']}.csv")
        print(f"series/{row['run']}.csv")
    if not names or "synthetic" in names:
        write_synthetic(out / "synthetic.csv")
        print("series/synthetic.csv")


if __name__ == "__main__":
    main(sys.argv[1:])

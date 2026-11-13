"""Index plots, the combined PDF and the zip archives (``climpact.plots``), and the
Mann-Kendall p-value and Sen intercept drawn on the plots (``climpact.trends``).

The plot file names are checked against R's for the reference runs in
``tests/parity/test_plots.py``.
"""

import math
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from climpact import plots
from climpact.batch import BatchStation, run_batch, run_station
from climpact.cli import main
from climpact.config import CustomIndex, IndexParams, StationMetadata
from climpact.plots import (
    IndexPlot,
    index_plots,
    plot_steps,
    station_title,
    trend_text,
    zip_station,
)
from climpact.trends import _alnorm, mann_kendall_p, plot_trend, sen_trend
from tests.test_batch import write_station

PARAMS = IndexParams(custom=None)


def _has_matplotlib() -> bool:
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return False
    return True


needs_matplotlib = pytest.mark.skipif(not _has_matplotlib(), reason="needs matplotlib")


# ------------------------------------------------------------------ trend statistics


@pytest.mark.parametrize("x", [-12.0, -7.5, -3.1, -1.28, -0.4, 0.0, 0.4, 1.28, 2.2, 5.0, 9.5])
def test_alnorm_is_the_normal_distribution(x):
    assert _alnorm(x, upper=False) == pytest.approx(norm.cdf(x), abs=1e-7)
    assert _alnorm(x, upper=True) == pytest.approx(norm.sf(x), abs=1e-7)


def test_mann_kendall_p_normal_approximation_with_continuity_correction():
    y = np.array([3.0, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 8, 9, 7, 9])
    n = len(y)
    s = sum(np.sign(y[j] - y[i]) for i in range(n) for j in range(i + 1, n))
    # Ties in y: groups of 2 (1, 3), 3 (5) and 3 (9).
    ties = [2, 2, 3, 3]
    var_s = (n * (n - 1) * (2 * n + 5) - sum(t * (t - 1) * (2 * t + 5) for t in ties)) / 18
    z = (s - np.sign(s)) / math.sqrt(var_s)
    assert mann_kendall_p(y) == pytest.approx(2 * norm.sf(abs(z)), rel=1e-5)


def test_mann_kendall_p_drops_missing_values():
    y = np.array([1.0, np.nan, 2, 5, np.nan, 4, 6, 8, 7, 9])
    assert mann_kendall_p(y) == mann_kendall_p(y[~np.isnan(y)])


@pytest.mark.parametrize(
    "y",
    [[2.0] * 12, [1.0, 2.0, 3.0], [np.nan] * 5],
    ids=["constant", "fewer than 4 values", "all missing"],
)
def test_mann_kendall_p_is_1_where_tauk2_sets_none(y):
    assert mann_kendall_p(y) == 1.0


def test_plot_trend_is_the_trend_file_trend_with_zyp_intercept():
    rng = np.random.default_rng(1)
    y = 10 + 0.3 * np.arange(30) + rng.normal(0, 1, 30)
    y[[4, 17]] = np.nan
    trend = plot_trend(y)
    assert (trend.lower, trend.slope, trend.upper) == sen_trend(y)
    keep = ~np.isnan(y)
    assert trend.intercept == pytest.approx(np.median(y[keep] - trend.slope * np.arange(30)[keep]))
    assert trend.p_value < 0.001 and trend.valid


def test_plot_trend_missing_without_enough_data():
    trend = plot_trend([1.0, 2.0, np.nan, 4.0])
    assert not trend.valid and math.isnan(trend.p_value)


# ------------------------------------------------------------------ plot text


@pytest.mark.parametrize(
    ("lat", "lon", "expected"),
    [(-33.86, 151.21, "33.86°S, 151.21°E"), (0, 0, "0°N, 0°E"), (44.9, -93.2, "44.9°N, 93.2°W")],
)
def test_station_title(lat, lon, expected):
    title = station_title(StationMetadata("stn", latitude=lat, longitude=lon))
    assert title == f"stn  ·  {expected}"


def _plot(trend, units="degrees_C", step="year"):
    return IndexPlot("x_ANN", "x: test", units, np.arange(3.0), np.ones(3), step, trend=trend)


def test_trend_text():
    trend = plot_trend(np.arange(20.0) * 0.25)
    text = trend_text(_plot(trend))
    assert text.startswith("Sen's slope 0.250 °C per year  (95% CI 0.250 to 0.250)")
    assert text.endswith("Mann-Kendall p < 0.001")
    assert "per month" in trend_text(_plot(trend, units="unitless", step="month"))
    assert trend_text(_plot(None)) == ""
    assert trend_text(_plot(plot_trend([1.0, 2.0]))).startswith("No linear trend")


# ------------------------------------------------------------------ which plots


def _annual(values):
    return pd.DataFrame({"time": np.arange(2000.0, 2000 + len(values)), "val": values})


def test_index_plots_follow_r_rules():
    custom = CustomIndex("TX", ">=", 25.5)
    params = IndexParams(custom=custom)
    txx = _annual([30.0, 31.0])
    txx["ymd"] = ["2000-02-01", None]
    tables = {
        "indices/txx_ANN": txx,
        "indices/fd_ANN": pd.DataFrame({"time": [2000.0, 2001.0], "fd": [np.nan, np.nan]}),
        "indices/cdd_ANN": pd.DataFrame(
            {"time": [2000.0], "start": ["2000-01-01"], "duration": [4.0], "end": ["2000-01-04"]}
        ),
        "indices/3month_spi_MON": pd.DataFrame({"time": ["2000-01", "2000-02"], "spi": [0.5, -1]}),
        "indices/TXge25.5_MON": pd.DataFrame({"time": ["2000-01"], "TXge25.5": [3.0]}),
    }
    groups = dict(index_plots(tables, params))
    assert list(groups) == plot_steps(params)
    names = [p.name for group in groups.values() for p in group]
    # fd is missing throughout: not plotted. cdd has no day_of_ plot. The custom scale
    # (24 months) has no table.
    assert names == ["txx_ANN", "day_of_txx_ANN", "cdd_ANN", "3month_spi_MON", "TXge25.5_MON"]

    by_name = {p.name: p for group in groups.values() for p in group}
    day_of = by_name["day_of_txx_ANN"]
    assert day_of.trend is None and day_of.units == "Calendar day"
    np.testing.assert_array_equal(day_of.values, [32.0, np.nan])
    assert day_of.description == "The calendar day of occurrence of annual warmest daily tx"
    assert by_name["3month_spi_MON"].bars
    np.testing.assert_allclose(by_name["3month_spi_MON"].x, [2000 + 0.5 / 12, 2000 + 1.5 / 12])
    assert by_name["TXge25.5_MON"].description == "Number of days where TX >= 25.5"
    assert groups["plots:TXge25.5_MON"] == [by_name["TXge25.5_MON"]]


def test_plot_steps_cover_every_row_and_the_custom_index():
    steps = plot_steps(IndexParams())
    assert steps[0] == "plots:fd_ANN"
    assert {"plots:hw", "plots:hwEHF", "plots:spei", "plots:spi", "plots:tx95t_DAY"} <= set(steps)
    assert steps[-2:] == ["plots:TNgt0_ANN", "plots:TNgt0_MON"]
    assert len(plot_steps(PARAMS)) == len(steps) - 2


# ------------------------------------------------------------------ runs, zip, CLI


@pytest.fixture
def station_file(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return write_station(data / "stn.txt")


def _names(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as z:
        return z.namelist()


@needs_matplotlib
def test_run_station_with_plots_and_zip(station_file, tmp_path):
    metadata = StationMetadata("stn", latitude=-10)
    events = []
    written, skipped = run_station(
        station_file,
        metadata,
        PARAMS,
        tmp_path,
        progress=lambda *e: events.append(e),
        plots=True,
        zip=True,
    )
    stages = [e[0] for e in events]
    n = stages.index("write") + 1
    assert stages[n:] == [*plot_steps(PARAMS), "zip"]
    assert [e[1] for e in events] == list(range(1, len(events) + 1))
    assert {e[2] for e in events} == {len(events)}

    folder = tmp_path / "stn" / "plots"
    pngs = sorted(p.name for p in folder.glob("*.png"))
    assert "stn_txx_ANN.png" in pngs and "stn_day_of_txx_MON.png" in pngs
    assert written["plots/txx_ANN"] == folder / "stn_txx_ANN.png"
    assert written["plots/all_plots"] == folder / "stn_all_plots.pdf"
    pdf = (folder / "stn_all_plots.pdf").read_bytes()
    assert pdf.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page\b(?!s)", pdf)) == len(pngs)

    archive = written["zip"]
    assert archive == tmp_path / "stn.zip"
    names = _names(archive)
    assert "plots/stn_txx_ANN.png" in names and "indices/stn_txx_ANN.csv" in names
    assert {"indices/", "plots/", "qc/", "thres/", "trend/"} <= set(names)
    files = {str(p.relative_to(tmp_path / "stn")) for p in (tmp_path / "stn").rglob("*.*")}
    assert {n for n in names if not n.endswith("/")} == files


def test_zip_station_leaves_out_zip_files(tmp_path):
    folder = tmp_path / "stn"
    (folder / "indices").mkdir(parents=True)
    (folder / "indices" / "stn_fd_ANN.csv").write_text("x")
    (folder / "old.zip").write_text("x")
    archive = zip_station(tmp_path, "stn")
    assert _names(archive) == ["indices/", "indices/stn_fd_ANN.csv"]
    with zipfile.ZipFile(archive) as z:
        assert z.read("indices/stn_fd_ANN.csv") == b"x"


def test_batch_zip(station_file, tmp_path):
    station = BatchStation("stn.txt", -10, 0, PARAMS, 2)
    out = tmp_path / "batch"
    [result] = run_batch([station], station_file.parent, out, workers=1, zip=True)
    assert result.ok
    names = _names(tmp_path / "batch.zip")
    assert "stn/" in names and "stn/indices/stn_txx_ANN.csv" in names


def test_cli_zip(station_file, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["run", str(station_file), "--out", str(out), "--no-custom", "--zip"]) == 0
    assert (out / "stn.zip").is_file()
    assert not (out / "stn" / "plots").exists()
    assert f"Zipped them to {out / 'stn.zip'}" in capsys.readouterr().out


def test_cli_plots_without_matplotlib(station_file, tmp_path, monkeypatch, capsys):
    def missing():
        raise ImportError("plots need matplotlib")

    monkeypatch.setattr(plots, "require_matplotlib", missing)
    with pytest.raises(SystemExit):
        main(["run", str(station_file), "--out", str(tmp_path), "--plots"])
    assert "--plots: plots need matplotlib" in capsys.readouterr().err

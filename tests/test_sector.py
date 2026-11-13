"""Sector correlation (climpact.sector): R's quirks that the reference run does not show."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from climpact.cli import main
from climpact.io.station import read_station_rows
from climpact.sector import (
    NO_COMMON_DATA,
    SectorCorrelationError,
    SectorData,
    annual_temperature,
    default_y_label,
    detrend,
    file_part,
    r_make_names,
    read_index_tables,
    read_sector_file,
    run_sector_correlation,
    sector_correlation,
    sector_steps,
    write_r_csv,
)

REFERENCE = Path(__file__).parents[1] / "reference"
STATION = "sydney_observatory_hill_1936-2015"
STATION_FILE = REFERENCE / "input" / f"{STATION}.txt"
SECTOR_FILE = REFERENCE / "input" / "sector" / "wheat_yield_nsw_1922-1999.csv"
INDICES = REFERENCE / "output" / "sydney" / STATION / "indices"
R_SECTOR = REFERENCE / "output" / "sydney" / "sector"


def _has_matplotlib() -> bool:
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return False
    return True


def test_make_names_as_read_csv():
    assert r_make_names(["Year", "Wheat yield (t/ha)"]) == ["Year", "Wheat.yield..t.ha."]
    assert r_make_names(["1st", ".5x", "_a", "", "if", "a", "a", "a.1"]) == [
        "X1st",
        "X.5x",
        "X_a",
        "X",
        "if.",
        "a",
        "a.2",
        "a.1",
    ]


def test_file_part_and_labels():
    assert file_part("Wheat.yield..t.ha.") == "wheat.yield"
    assert file_part("Detrended.Wheat.yield..t.ha.") == "detrended.wheat.yield"
    assert file_part("Rice") == "rice"
    assert default_y_label(SECTOR_FILE) == "wheat"
    assert default_y_label("maize.yield.csv") == "maize"


def test_read_sector_file(tmp_path):
    sector = read_sector_file(SECTOR_FILE)
    assert sector.column == "Wheat.yield..t.ha."
    assert sector.detrended_column == "Detrended.Wheat.yield..t.ha."
    assert sector.years[0] == 1922 and len(sector.years) == 78

    path = tmp_path / "s.csv"
    path.write_text("Year,Yield\n2000,1\n2001,-99.9\n2002,NA\n2003,\n")
    sector = read_sector_file(path)
    assert np.isnan(sector.values[1:]).all()

    path.write_text("Year,A,B\n2000,1,2\n")
    with pytest.raises(SectorCorrelationError, match="two columns"):
        read_sector_file(path)
    path.write_text("year,A\n2000,1\n")
    with pytest.raises(SectorCorrelationError, match="named Year"):
        read_sector_file(path)
    path.write_text("Year,A\n2001,1\n2000,2\n")
    with pytest.raises(SectorCorrelationError, match="increase"):
        read_sector_file(path)


def test_detrend_counts_rows_from_the_middle_row():
    # Even number of rows: the middle is (n + 2) / 2, not (n + 1) / 2.
    years = np.array([2000.0, 2001, 2002, 2003])
    values = np.array([1.0, 2, 3, 4])  # slope 1
    np.testing.assert_array_equal(detrend(years, values), [3.0, 3, 3, 3])
    # Odd: the middle row (row 2 of 3) is unchanged.
    np.testing.assert_array_equal(detrend(years[:3], values[:3]), [2.0, 2, 2])
    # A gap in the years: the slope is per year, but the distance is counted in rows.
    out = detrend(np.array([2000.0, 2001, 2010]), np.array([0.0, 1, 10]))
    np.testing.assert_array_equal(out, [1.0, 1, 9])
    # A missing value is left out of the slope and stays missing.
    out = detrend(years, np.array([1.0, np.nan, 3, 4]))
    assert np.isnan(out[1]) and out[0] == 1 + 2 * 1.0
    # One value: no slope, every result missing (R's NA coefficient).
    assert np.isnan(detrend(years, np.array([1.0, np.nan, np.nan, np.nan]))).all()


def test_annual_temperature_pools_tx_and_tn():
    rows = pd.DataFrame(
        {
            "year": [2000.0, 2000, 2000, 2001],
            "tmax": [31.0, 20.0, np.nan, np.nan],
            "tmin": [10.0, np.nan, np.nan, np.nan],
        }
    )
    t = annual_temperature(rows)
    assert t["avg_tmax"][0] == 25.5 and t["avg_tmin"][0] == 10
    assert t["avg_t"][0] == pytest.approx(61 / 3)  # not (25.5 + 10) / 2
    assert t["above30"].tolist() == [1, 0]
    assert np.isnan(t["avg_t"][1])


def _rows(years):
    return pd.DataFrame(
        {"year": np.repeat(years, 2), "tmax": np.tile([20.0, 32.0], len(years)), "tmin": 10.0}
    )


def test_missing_index_values_are_correlated_as_minus_99_9():
    years = np.arange(2000.0, 2012)
    values = np.arange(12.0)
    sector = SectorData(years, values, "Y")
    index = np.where(years == 2005, np.nan, 1.0)  # constant apart from one missing year
    tables = {"indices/su_ANN": pd.DataFrame({"time": years, "su": index})}
    result = sector_correlation(_rows(years), tables, sector, "st", detrend_sector=False)
    cor = result.correlations.set_index("indice")["cor"]
    expected = np.corrcoef(values, np.where(np.isnan(index), -99.9, index))[0, 1]
    assert cor["su"] == round(expected, 2)
    assert list(result.correlations.columns) == ["indice", "cor", "category"]


def test_constant_index_and_unknown_names():
    years = np.arange(2000.0, 2012)
    sector = SectorData(years, np.arange(12.0), "Y")
    tables = {
        "indices/fd_ANN": pd.DataFrame({"time": years, "fd": 0.0}),  # no variation: NA
        "indices/tnn_ANN": pd.DataFrame({"time": years, "val": years, "ymd": "x"}),
        "indices/wsdi3_ANN": pd.DataFrame({"time": years, "wsdi3": years}),  # not in R's list
        "indices/r20mm_ANN": pd.DataFrame({"time": years, "r20mm": np.nan}),  # not written
    }
    result = sector_correlation(_rows(years), tables, sector, "st", detrend_sector=False)
    rows = result.correlations
    assert rows["indice"].tolist() == ["fd", "tnn"]
    assert np.isnan(rows["cor"][0]) and rows["cor"][1] == 1.0
    assert not result.detrended and result.file_part == "y"
    # Detrended, the straight line is constant, so it correlates with nothing.
    result = sector_correlation(_rows(years), tables, sector, "st")
    assert result.detrended and result.file_part == "detrended.y"
    assert result.correlations["cor"].isna().all()


def test_too_few_common_years():
    years = np.arange(2000.0, 2009)  # 9 years
    sector = SectorData(years, np.arange(9.0), "Y")
    with pytest.raises(SectorCorrelationError, match="no data in common"):
        sector_correlation(_rows(years), {}, sector, "st")
    # An index with no year in common with the sector data: R's same message.
    years = np.arange(2000.0, 2012)
    sector = SectorData(years, np.arange(12.0), "Y")
    tables = {"indices/su_ANN": pd.DataFrame({"time": years + 50, "su": 1.0})}
    with pytest.raises(SectorCorrelationError) as info:
        sector_correlation(_rows(years), tables, sector, "st")
    assert str(info.value) == NO_COMMON_DATA


def test_write_r_csv(tmp_path):
    path = write_r_csv(
        tmp_path / "a.csv",
        pd.DataFrame({"indice": ["fd", 'a"b'], "cor": [-0.3, np.nan], "n": [1936.0, 2]}),
    )
    assert path.read_text() == '"indice","cor","n"\n"fd",-0.3,1936\n"a""b",NA,2\n'


def test_files_match_in_memory_path():
    """Reading the run's index files gives the same result as its tables in memory."""
    tables = read_index_tables(INDICES, STATION)
    assert "indices/fd_ANN" in tables and "indices/hddheat18_ANN" in tables
    result = sector_correlation(
        read_station_rows(STATION_FILE), tables, read_sector_file(SECTOR_FILE), STATION, False
    )
    r = pd.read_csv(R_SECTOR / "raw" / f"{STATION}_index-sector_correlation_wheat.yield.csv")
    pd.testing.assert_frame_equal(result.correlations, r, check_dtype=False)


def _run_folder(tmp_path) -> Path:
    out = tmp_path / "out"
    shutil.copytree(INDICES, out / STATION / "indices")
    return out


def test_run_sector_correlation_progress_and_zip(tmp_path):
    out = _run_folder(tmp_path)
    calls = []
    written = run_sector_correlation(
        STATION_FILE,
        SECTOR_FILE,
        out,
        STATION,
        zip=True,
        progress=lambda *a: calls.append(a),
    )
    total = len(sector_steps(zip=True))
    assert calls == [(s, i, total) for i, s in enumerate(sector_steps(zip=True), start=1)]
    assert written["zip"] == out / f"{STATION}_corr.zip"
    with zipfile.ZipFile(written["zip"]) as z:
        assert sorted(z.namelist()) == sorted(
            p.name for p in (R_SECTOR / "detrended").glob("*.csv")
        )
    for p in (R_SECTOR / "raw").glob("*.csv"):  # detrended by default
        assert not (out / STATION / "corr" / p.name).exists()


@pytest.mark.skipif(not _has_matplotlib(), reason="needs matplotlib")
def test_cli_sector_correlation_with_plots(tmp_path, capsys):
    out = _run_folder(tmp_path)
    args = ["sector-correlation", str(STATION_FILE), str(SECTOR_FILE), "--out", str(out)]
    assert main([*args, "--no-detrend", "--plots"]) == 0
    corr = out / STATION / "corr"
    names = {p.name for p in corr.iterdir()}
    expected = {p.name for p in (R_SECTOR / "raw").glob("*.csv")}
    assert names == expected | {n.replace(".csv", ".png") for n in expected}
    for name in expected:
        assert (corr / name).read_text() == (R_SECTOR / "raw" / name).read_text()
    assert f"Wrote 10 files to {corr}" in capsys.readouterr().out


def test_cli_sector_correlation_errors(tmp_path, capsys):
    args = ["sector-correlation", str(STATION_FILE), str(SECTOR_FILE), "--out", str(tmp_path)]
    with pytest.raises(SystemExit):
        main(args)  # no run in --out
    assert "run `climpact run` first" in capsys.readouterr().err

    out = _run_folder(tmp_path)
    short = tmp_path / "short.csv"
    short.write_text("Year,Y\n" + "".join(f"{y},1\n" for y in range(2010, 2030)))
    assert main(["sector-correlation", str(STATION_FILE), str(short), "--out", str(out)]) == 1
    assert NO_COMMON_DATA in capsys.readouterr().err

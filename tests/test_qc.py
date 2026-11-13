"""Unit tests for the per-value QC checks (``climpact.qc``) and their files.

The R behaviour each test pins down is from ``services/check/*.R`` in Climpact v3.4.3;
the reference runs (``tests/parity``, including the synthetic ``qc_stress`` station)
check the same rules end to end.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from climpact import qc
from climpact.config import QCParams, StationMetadata
from climpact.io.climpact_csv import read_climpact_csv, write_climpact_csv
from climpact.io.output_files import write_outputs
from climpact.io.station import merged_rows, read_station_file, station_dataset
from climpact.products.qc import QC_REPORTS, qc_reports
from climpact.rnumerics import r_round
from climpact.station import StationRun, load_station

DATA = Path(__file__).parent / "data"
P = QCParams()
NA = np.nan


def rows(tx=None, tn=None, prcp=None, start="2000-01-01") -> pd.DataFrame:
    """QC rows for consecutive days; unspecified variables are 10.0 (TN 0.0, prec 0)."""
    n = len(next(v for v in (tx, tn, prcp) if v is not None))
    return pd.DataFrame(
        {
            "date": pd.date_range(start, periods=n, freq="D"),
            "prcp": [0.0] * n if prcp is None else prcp,
            "tmax": [10.0] * n if tx is None else tx,
            "tmin": [0.0] * n if tn is None else tn,
        }
    ).astype({"prcp": float, "tmax": float, "tmin": float})


def as_records(table: pd.DataFrame) -> list[tuple]:
    return [
        tuple(None if isinstance(v, float) and np.isnan(v) else v for v in row)
        for row in table.itertuples(index=False)
    ]


# --- R's round -----------------------------------------------------------------------


def test_r_round_matches_r():
    """abs(round(diff(x), 1)) from R 4.6.1 (tests/data/r_round.R), including ties."""
    pairs = [line.split() for line in (DATA / "r_round.txt").read_text().splitlines()]
    change = np.array([float.fromhex(a) for a, _ in pairs])
    expected = np.array([float.fromhex(b) for _, b in pairs])
    np.testing.assert_array_equal(np.abs(r_round(change, 1)), expected)
    # Python's round differs from R's on some of them, so the port is needed.
    assert (np.abs(np.round(change, 1)) != expected).any()


def test_r_round_edge_values():
    x = np.array([0.45, -0.15, 0.25, NA, np.inf, 0.0, 1e300, 1234567890123456.7])
    out = r_round(x, 1)
    np.testing.assert_array_equal(out[:3], [0.4, -0.1, 0.2])
    assert np.isnan(out[3]) and out[4] == np.inf and out[5] == 0
    assert out[6] == 1e300 and out[7] == x[7]  # more than 15 digits: unchanged


# --- the rows the checks run on ------------------------------------------------------


def write_station(tmp_path, lines: list[str]) -> Path:
    path = tmp_path / "station.txt"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_merged_rows_keeps_duplicates_in_file_order_and_fills_gaps(tmp_path):
    path = write_station(
        tmp_path,
        [
            "2000 1 1 0 10 1",
            "2000 1 2 0 11 2",
            "2000 1 2 0 12 3",
            "2000 1 4 0 14 4",  # 3 January is missing
            "2000 1 2 0 13 5",  # out of order: still kept, after the other 2 January rows
            "2000 1 5 0 15 6",
        ],
    )
    merged = merged_rows(read_station_file(path))
    assert [d.day for d in merged["date"]] == [1, 2, 2, 2, 3, 4, 5]
    assert merged["tmax"].tolist()[1:4] == [11, 12, 13]
    assert np.isnan(merged.loc[4, "tmax"])


def test_merged_rows_drops_rows_outside_first_and_last_row(tmp_path):
    """R's date series runs from the first row's date to the last row's date."""
    df = read_station_file(
        write_station(tmp_path, ["2000 1 2 0 10 1", "1999 12 31 0 9 1", "2000 1 3 0 11 1"])
    )
    merged = merged_rows(df)
    assert [str(d.date()) for d in merged["date"]] == ["2000-01-02", "2000-01-03"]
    ds = station_dataset(df, StationMetadata("s"))
    assert str(ds.time.values[0])[:10] == "2000-01-01"  # 1999 is not part of the series
    assert ds.attrs["first_date"] == "2000-01-02"


def test_merged_rows_last_row_before_first_is_an_error(tmp_path):
    df = read_station_file(write_station(tmp_path, ["2000 1 2 0 10 1", "2000 1 1 0 9 1"]))
    with pytest.raises(ValueError, match="dated before the first"):
        merged_rows(df)


def test_indices_use_the_last_row_of_a_duplicated_date(tmp_path):
    """create.filled.series: the last row of a date wins, even if out of order or missing."""
    path = write_station(
        tmp_path,
        [
            "2000 1 1 0 10 1",
            "2000 1 2 0 11 1",
            "2000 1 2 0 12 1",
            "2000 1 3 0 13 1",
            "2000 1 1 0 99 1",
            "2000 1 3 -99.9 -99.9 -99.9",
            "2000 1 4 0 14 1",
        ],
    )
    run = load_station(path, StationMetadata("s"))
    tx = run.data["tasmax"].sel(time=slice("2000-01-01", "2000-01-04")).values
    np.testing.assert_array_equal(tx[:2], [99, 12])
    assert np.isnan(tx[2]) and tx[3] == 14
    # The QC rows still have every row.
    assert len(run.rows) == 7


def test_rows_rebuilt_from_data_without_qc_rows(tmp_path):
    path = write_station(tmp_path, ["2000 3 1 0 10 1", "2000 3 2 0 11 1", "2000 3 3 0 12 1"])
    run = load_station(path, StationMetadata("s"))
    rebuilt = StationRun(data=run.data, metadata=run.metadata)
    pd.testing.assert_frame_equal(rebuilt.rows, run.rows, check_dtype=False)


# --- the checks ----------------------------------------------------------------------


def test_duplicate_dates_lists_each_repeat():
    r = rows(tx=[1.0] * 6)
    r["date"] = pd.to_datetime(["1961-01-03"] * 3 + ["1961-01-04", "1961-12-25", "1961-12-25"])
    assert qc.duplicate_dates(r)["Dates_duplicated"].tolist() == [
        "1961-1-3",
        "1961-1-3",
        "1961-12-25",
    ]
    assert qc.duplicate_dates(rows(tx=[1.0, 2.0])).empty


def test_tmaxmin_includes_equal_and_skips_missing():
    r = rows(tx=[10, 5, 5, NA, 4], tn=[0, 5, 6, 9, NA], prcp=[0, NA, 1, 0, 0])
    assert as_records(qc.tmax_le_tmin(r)) == [("2000-1-2", None, 5, 5), ("2000-1-3", 1, 5, 6)]


def test_too_large_edges():
    r = rows(
        prcp=[200, 200.1, -0.1, 0, 0, 0, 0, NA, 300],
        tx=[10, 10, 10, 50, 50.1, 10, 10, 60, NA],
        tn=[0, 0, 0, -50, 0, -50.1, 0, NA, NA],
    )
    assert qc.too_large(r, P)["Date"].tolist() == [
        "2000-1-2",  # 200.1 mm
        "2000-1-3",  # negative rain
        "2000-1-5",  # TX 50.1 (50 is not flagged)
        "2000-1-6",  # TN -50.1
        "2000-1-8",  # TX 60 with prec missing
        "2000-1-9",  # prec 300 with temperatures missing
    ]
    stricter = QCParams(prec_max=100, temp_max=40)
    assert len(qc.too_large(rows(prcp=[150.0], tx=[45.0]), stricter)) == 1


def test_tx_jumps_threshold_and_reported_change():
    r = rows(tx=[10, 30, 10.1, 20, 40, 60, 61, NA, 90, 69.9])
    # +20 (flagged, >=), -19.9 (not), +9.9, then two +20 in a row: one run, reported on
    # the date of its last change; missing values break runs; -20.1 is flagged.
    assert as_records(qc.jumps(r, "tmax", P)) == [
        ("2000-1-1", 20),
        ("2000-1-5", 20),
        ("2000-1-9", 20.1),
    ]
    assert as_records(qc.jumps(r, "tmax", QCParams(jump=20.1))) == [("2000-1-9", 20.1)]
    assert qc.jumps(r, "tmax", QCParams(jump=20.2)).empty


def test_tn_jumps_report_the_value_not_the_change():
    r = rows(tn=[-2, -27.5, -3, -22.9])
    assert as_records(qc.jumps(r, "tmin", P)) == [("2000-1-1", -2), ("2000-1-2", -27.5)]


def test_jumps_use_r_rounding():
    """30.05 - 10.1 rounds to 20 in R (it is 19.950000000000003)."""
    r = rows(tx=[10.1, 30.05, 30.05, 10.06])  # changes 19.95 -> 20, 0, 19.99 -> 20
    assert qc.jumps(r, "tmax", P)["Date"].tolist() == ["2000-1-1", "2000-1-3"]


def test_flatline_threshold_and_reported_day():
    tx = [1.0] + [5.0] * 5 + [2.0] + [7.0] * 6 + [3.0]
    out = qc.flatline(rows(tx=tx), "tmax", P)
    # 5 equal values (4 zero changes) are not reported; 6 are, on the second-last day.
    assert as_records(out) == [("2000-1-12", 7, 6)]
    assert len(qc.flatline(rows(tx=tx), "tmax", QCParams(flatline_days=4))) == 2


def test_flatline_broken_by_missing_and_rounding():
    tn = [3.0] * 4 + [NA] + [3.0] * 4 + [1, 20.01, 20.04, 20.0, 19.98, 20.02, 20.03, 9]
    out = qc.flatline(rows(tn=tn), "tmin", P)
    # The NA splits the 3.0s; the 20.0x values round to zero changes (6 equal "values").
    assert as_records(out) == [("2000-1-15", 20.02, 6)]


def test_checks_on_no_rows():
    empty = rows(tx=[])
    for report in QC_REPORTS:
        assert report.check(empty, P).empty


# --- files ---------------------------------------------------------------------------


def test_qc_files_layout(tmp_path):
    path = write_station(
        tmp_path,
        [f"2000 1 {d} 0 {tx} {tn}" for d, tx, tn in [(1, 10, 1), (2, 10, 1), (3, 12, 13)]],
    )
    meta = StationMetadata("s", -10.5, 120)
    params = QCParams(prec_max=150.5, temp_max=45, flatline_days=3, jump=15)
    run = load_station(path, meta, qc=params)
    written = write_outputs(qc_reports(run), meta, run.params, tmp_path / "out")
    assert sorted(written) == sorted(f"qc/{r.name}" for r in QC_REPORTS)

    def body(name):
        lines = written[f"qc/{name}"].read_text().splitlines()
        return lines[0], lines[7:]

    assert body("toolarge") == (
        '"Description: ","Dates where precipitation > 150.5 mm or abs(temperature) > 45 degrees."',
        ["Date,Prec,TX,TN"],  # no "NO ... FOUND" line (R tests the column count)
    )
    assert body("tmaxmin")[1] == ["Date,Prec,TX,TN", "2000-1-3,0,12,13"]
    assert body("duplicates")[1] == ["Dates_duplicated", '"NO DUPLICATE DATES FOUND"']
    assert body("tx_jumps")[1] == ["Date,TX", '"NO LARGE TX JUMPS FOUND"']
    assert body("tn_flatline") == (
        '"Description: ","Dates where TX values have been repeated more than 3 times."',
        ['"Date","TN","Number of duplicates"', '"NO REPEATED TN FOUND"'],
    )

    # The reader returns the quoted lines as messages and unquotes the header.
    table = read_climpact_csv(written["qc/tn_flatline"])
    assert table.columns == ["Date", "TN", "Number of duplicates"]
    assert table.data.empty and table.messages == ["NO REPEATED TN FOUND"]


def test_missing_values_are_written_as_na(tmp_path):
    path = write_station(tmp_path, ["2000 1 1 0 10 1", "2000 1 2 -99.9 5 6"])
    meta = StationMetadata("s")
    run = load_station(path, meta)
    written = write_outputs(qc_reports(run), meta, run.params, tmp_path / "out")
    assert written["qc/tmaxmin"].read_text().splitlines()[-1] == "2000-1-2,NA,5,6"


def test_qc_report_order():
    """allqc's order: fourboxes, tmaxmin, humongous, duplivals, jumps, flatline."""
    assert [r.name for r in QC_REPORTS] == [
        "outliers",
        "tmaxmin",
        "toolarge",
        "duplicates",
        "tx_jumps",
        "tn_jumps",
        "tx_flatline",
        "tn_flatline",
    ]


# --- outliers (fourboxes) --------------------------------------------------------------


def _hex(text: str) -> np.ndarray:
    return np.array([np.nan if v == "NA" else float.fromhex(v) for v in text.split()])


def _boxplot_cases() -> list[tuple[float, np.ndarray, np.ndarray, np.ndarray]]:
    lines = (DATA / "r_boxplot.txt").read_text().splitlines()
    return [
        (float(coef), _hex(x), _hex(five), _hex(stats))
        for coef, x, five, stats in (line.split(";") for line in lines)
    ]


def test_fivenum_and_boxplot_stats_match_r():
    """fivenum and boxplot.stats(x, coef)$stats from R 4.6.1 (tests/data/r_boxplot.R):
    n = 1 to 12, longer samples with outliers, ties, IQR 0, missing values, values on a
    fence, coef 0 and no values."""
    cases = _boxplot_cases()
    sizes = {int((~np.isnan(x)).sum()) for _, x, _, _ in cases}
    assert {0, 1, 2, 3, 4, 5, 30, 31, 90, 93} <= sizes  # even and odd n
    for coef, x, five, stats in cases:
        np.testing.assert_array_equal(qc.fivenum(x), five, err_msg=f"fivenum {x}")
        np.testing.assert_array_equal(qc.boxplot_stats(x, coef), stats, err_msg=f"{coef} {x}")
    # numpy's default quartiles are not Tukey's hinges: the port is needed.
    assert any(
        not np.allclose(np.percentile(x[~np.isnan(x)], [25, 75]), five[[1, 3]])
        for _, x, five, _ in cases
        if (~np.isnan(x)).sum() > 1
    )


def test_tukey_hinges_even_and_odd():
    # n = 4: hinges are means of the middle pairs of each half; n = 5: they include the median.
    np.testing.assert_array_equal(qc.fivenum([4.0, 1.0, 3.0, 2.0]), [1, 1.5, 2.5, 3.5, 4])
    np.testing.assert_array_equal(qc.fivenum([5.0, 1.0, NA, 3.0, 2.0, 4.0]), [1, 2, 3, 4, 5])


def test_outliers_sections_and_order():
    """Sections in R's order; within one, months in calendar order and rows in the
    given order within a month. Precipitation is only "up", boxed from non-zero values."""
    feb = pd.date_range("2001-02-01", periods=5)
    jan = pd.date_range("2001-01-01", periods=5)
    r = pd.DataFrame(
        {
            "date": feb.append(jan),
            # Feb: zeros are not in the box, so 50 is beyond 5 IQR of [1, 1, 1, 1, 50].
            "prcp": [1, 1, 1, 1, 50, 0, 0, 0, 0, 0],
            "tmax": [10, 10, 10, 10, 99, 10, 99, 10, 10, 10],
            "tmin": [0, 0, 0, -40, 0, 0, 0, 0, 0, -9],
        }
    ).astype({"prcp": float, "tmax": float, "tmin": float})
    table = qc.outliers(r, P)
    assert list(table["Section"].cat.categories) == [
        "Prec up",
        "TX up",
        "TX low",
        "TN up",
        "TN low",
        "DTR up",
        "DTR low",
    ]
    assert as_records(table) == [
        ("2001-2-5", 50, 99, 0, 99, "Prec up"),
        ("2001-1-2", 0, 99, 0, 99, "TX up"),
        ("2001-2-5", 50, 99, 0, 99, "TX up"),
        ("2001-1-5", 0, 10, -9, 19, "TN low"),
        ("2001-2-4", 1, 10, -40, 50, "TN low"),
        ("2001-1-2", 0, 99, 0, 99, "DTR up"),  # Jan DTR hinges 10 and 19: 19 is inside
    ]


def test_outliers_missing_variable_has_no_sections():
    r = rows(tx=[10.0, 11, 12], tn=[NA, NA, NA], prcp=[0.0, 0, NA])
    assert list(qc.outliers(r, P)["Section"].cat.categories) == ["TX up", "TX low"]


@pytest.mark.parametrize(
    ("station", "iqr_temp", "iqr_prec"),
    [("edges", 3.0, 5.0), ("edges", 1.5, 2.0), ("dry", 3.0, 5.0)],
)
def test_outliers_file_matches_r(tmp_path, station, iqr_temp, iqr_prec):
    """R's fourboxes on the synthetic stations (tests/data/make_fourboxes_synthetic.py,
    tests/data/r_fourboxes.R): months without a box, no rain, no TN, values on the
    fences, IQR 0 and non-default thresholds."""
    meta = StationMetadata(station)
    params = QCParams(iqr_temp=iqr_temp, iqr_prec=iqr_prec)
    run = load_station(DATA / f"fourboxes_{station}.txt", meta, qc=params)
    tables = {"qc/outliers": qc_reports(run)["qc/outliers"]}
    written = write_outputs(tables, meta, run.params, tmp_path)["qc/outliers"]
    expected = DATA / f"r_fourboxes_{station}_{iqr_temp:g}_{iqr_prec:g}_outliers.csv"

    def lines(path):
        return [x for x in path.read_text().splitlines() if "Date_of_calculation" not in x]

    assert lines(written) == lines(expected)
    # The reader returns the section titles as messages.
    assert read_climpact_csv(written).messages == [
        x[1:-1] for x in lines(expected)[7:] if x.startswith('"')
    ]


def test_sections_must_cover_the_rows(tmp_path):
    table = pd.DataFrame({"a": [1.0, 2.0]})
    with pytest.raises(ValueError, match="sections"):
        write_climpact_csv(tmp_path / "x.csv", table, None, sections=[("A", 1)])
    path = write_climpact_csv(
        tmp_path / "y.csv", table, None, sep=",", sections=[("A", 0), ("B", 2)]
    )
    assert path.read_text().splitlines() == ["a", '"A"', '"B"', "1", "2"]

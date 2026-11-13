import math

import numpy as np
import pandas as pd
import pytest

from climpact.compare import Tier, compare_tables
from climpact.io.climpact_csv import (
    METADATA_KEYS,
    climpact_header,
    format_r_number,
    read_climpact_csv,
    write_climpact_csv,
)

from .parity.catalogue import STANDARDISED, reference_files

ANNUAL = """\
"Description: ","Annual number of days when TN < 0 degrees_C"
"Station: ","test"
"Latitude: ","0"
"Longitude: ","0"
"Base_period: ","1971-2000"
"Climpact_version: ","3.4.3"
"Date_of_calculation: ","2026-11-12"
time, fd, standardised values (using all years)
1936, 3, 0.5
1937, -99.9, -99.9
"""

WITH_DATES = """\
"Description: ","Annual warmest daily TX"
time, val, ymd
1936, 37.7, 1936-11-06
1937, -99.9, -99.9
"""

THRESHOLDS = """\
tmax_q5, tmax_q10
21.04, 22.5266666666667
"""


def test_reads_metadata_and_numeric_columns(tmp_path):
    path = tmp_path / "fd_ANN.csv"
    path.write_text(ANNUAL)
    table = read_climpact_csv(path)

    assert table.metadata["Station"] == "test"
    assert table.metadata["Base_period"] == "1971-2000"
    assert table.columns == ["time", "fd", "standardised values (using all years)"]
    assert table.data["fd"].iloc[0] == 3
    assert math.isnan(table.data["fd"].iloc[1])


def test_date_columns_stay_strings_with_missing_as_none(tmp_path):
    path = tmp_path / "txx_ANN.csv"
    path.write_text(WITH_DATES)
    data = read_climpact_csv(path).data

    assert data["ymd"].tolist() == ["1936-11-06", None]
    assert math.isnan(data["val"].iloc[1])


def test_file_without_metadata(tmp_path):
    path = tmp_path / "thres.csv"
    path.write_text(THRESHOLDS)
    table = read_climpact_csv(path)

    assert table.metadata == {}
    assert table.data["tmax_q10"].iloc[0] == pytest.approx(22.5266666666667)


def test_ragged_row_is_an_error(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("time, fd\n1936, 3, 4\n")
    with pytest.raises(ValueError, match="expected 2 fields"):
        read_climpact_csv(path)


@pytest.mark.parametrize("ref", reference_files(), ids=lambda f: f.id)
def test_every_reference_file_parses(ref):
    table = read_climpact_csv(ref.path)
    assert len(table.data) > 0


# --- writing ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, text",
    [
        (0.0, "0"),
        (-0.0, "0"),
        (3.0, "3"),
        (1936.0, "1936"),
        (36.9, "36.9"),
        (-33.86, "-33.86"),
        (0.1 + 0.2, "0.3"),
        (21.534482758620690, "21.5344827586207"),
        (1 / 3, "0.333333333333333"),
        (100000.0, "1e+05"),
        (123456.0, "123456"),
        (0.0001234, "0.0001234"),
        (0.00001234, "1.234e-05"),
        (1e15, "1e+15"),
        (1e-300, "1e-300"),
        (float("nan"), "-99.9"),
        (float("inf"), "Inf"),
        (float("-inf"), "-Inf"),
        # R's digit count comes from a long double scaling: the 15-digit rounding of
        # this value ends in 0 there, so R prints 14 digits, rounded up (not ...529).
        (-0.8707237491215295, "-0.87072374912153"),
    ],
)
def test_format_r_number(value, text):
    assert format_r_number(value) == text


def test_header_lines_are_quoted_like_r():
    lines = climpact_header({key: "x" for key in METADATA_KEYS} | {"Description": 'a "b"'})
    assert lines[0] == '"Description: ","a \\"b\\""'
    assert lines[6] == '"Date_of_calculation: ","x"'
    with pytest.raises(ValueError, match="missing metadata"):
        climpact_header({"Description": ""})


METADATA = {
    "Description": "Annual number of days when TN < 0 degrees_C",
    "Station": "test",
    "Latitude": "0",
    "Longitude": "0",
    "Base_period": "1971-2000",
    "Climpact_version": "3.4.3",
    "Date_of_calculation": "2026-11-12",
}


def test_write_matches_r_layout(tmp_path):
    data = pd.DataFrame(
        {"time": [1936.0, 1937.0], "fd": [3.0, np.nan], STANDARDISED: [0.5, np.nan]}
    )
    path = write_climpact_csv(tmp_path / "out" / "fd_ANN.csv", data, METADATA)
    assert path.read_text() == ANNUAL


def test_write_dates_and_separator(tmp_path):
    data = pd.DataFrame({"time": ["1936-01"], "val": [37.7], "ymd": [None]})
    path = write_climpact_csv(tmp_path / "t.csv", data, METADATA, sep=",")
    assert path.read_text().splitlines()[-2:] == ["time,val,ymd", "1936-01,37.7,-99.9"]


def test_round_trip(tmp_path):
    rng = np.random.default_rng(1)
    values = rng.normal(15, 5, 50)
    values[[3, 17]] = np.nan
    ymd = pd.Series([f"2000-01-{d % 28 + 1:02d}" for d in range(50)], dtype=object)
    ymd[np.isnan(values)] = None
    data = pd.DataFrame({"time": np.arange(1950.0, 2000.0), "val": values, "ymd": ymd})
    path = write_climpact_csv(tmp_path / "t.csv", data, METADATA)

    table = read_climpact_csv(path)
    assert table.metadata == METADATA
    result = compare_tables(table.data, data, Tier.CLOSE)
    assert result.ok, result.summary()

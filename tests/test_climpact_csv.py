import math

import pytest

from climpact.io.climpact_csv import read_climpact_csv

from .parity.catalogue import reference_files

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

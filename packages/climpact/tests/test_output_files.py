import datetime as dt

import numpy as np
import pandas as pd
import pytest

from climpact.config import CustomIndex, IndexParams, StationMetadata
from climpact.io.climpact_csv import read_climpact_csv
from climpact.io.output_files import (
    CLIMPACT_VERSION,
    file_metadata,
    index_descriptions,
    is_all_missing,
    output_path,
    write_outputs,
)

META = StationMetadata(name="stn", latitude=-33.86, longitude=151.21)


def test_descriptions_follow_climate_indices_csv():
    d = index_descriptions(IndexParams())
    assert d["fd_ANN"] == "Annual number of days when TN < 0 degrees_C"
    assert d["fd_MON"] == "Monthly number of days when TN < 0 degrees_C"
    assert d["tx95t_DAY"] == "Value of 95th percentile of TX"
    assert d["gsl_ANN"].startswith("Annual number of days between")
    assert not any(name.startswith(("hw", "spi", "spei")) for name in d)


def test_parameterised_descriptions():
    params = IndexParams(
        rnnmm=25.5, rx_days=4, hdd_base=17, wsdi_days=3, txtn_days=5,
        custom=CustomIndex("PR", ">=", 12.5),
    )  # fmt: skip
    d = index_descriptions(params)
    assert d["r25.5mm_MON"] == "Number of days when precipitation >= 25.5"
    assert d["rx4day_ANN"] == "Maximum annual 4-day precipitation total"
    assert d["rx4day_MON"] == "Maximum monthly 4-day precipitation total"
    assert d["hddheat17_ANN"] == "Annual sum of 17 - TM"
    assert d["wsdi3_ANN"].startswith("Annual number of days with at least 3 consecutive")
    assert d["tx5tn5_ANN"].startswith("Number of 5 consecutive days where both TX > 95th")
    assert d["PRge12.5_ANN"] == d["PRge12.5_MON"] == "PR >= 12.5"
    assert "TNgt0_ANN" not in index_descriptions(IndexParams(custom=None))


def test_output_path_and_metadata():
    assert output_path("out", "stn", "indices/fd_ANN") == (
        pytest.importorskip("pathlib").Path("out/stn/indices/stn_fd_ANN.csv")
    )
    m = file_metadata(META, "desc", dt.date(2026, 1, 2))
    assert m["Latitude"] == "-33.86"
    assert m["Base_period"] == "1971-2000"
    assert m["Climpact_version"] == CLIMPACT_VERSION
    assert m["Date_of_calculation"] == "2026-01-02"


def table(values):
    return pd.DataFrame({"time": [2000.0, 2001.0], "fd": values, "s": [np.nan, np.nan]})


def test_all_missing_tables_are_not_written(tmp_path):
    assert is_all_missing(table([np.nan, np.nan]))
    assert not is_all_missing(table([np.nan, 0.0]))
    dated = pd.DataFrame({"time": ["2000-01"], "val": [np.nan], "ymd": [None]})
    assert is_all_missing(dated)

    tables = {
        "indices/fd_ANN": table([1.0, 2.0]),
        "indices/fd_MON": table([np.nan, np.nan]),
        "indices/txx_ANN": dated,
    }
    written = write_outputs(tables, META, IndexParams(), tmp_path)
    assert list(written) == ["indices/fd_ANN"]
    assert sorted(p.name for p in tmp_path.rglob("*.csv")) == ["stn_fd_ANN.csv"]
    result = read_climpact_csv(written["indices/fd_ANN"])
    assert result.metadata["Description"] == "Annual number of days when TN < 0 degrees_C"


def test_unknown_outputs_are_an_error(tmp_path):
    with pytest.raises(KeyError, match="no description"):
        write_outputs({"indices/nosuch_ANN": table([1.0, 2.0])}, META, IndexParams(), tmp_path)
    with pytest.raises(KeyError, match="no file format"):
        write_outputs({"qc/nosuch": table([1.0, 2.0])}, META, IndexParams(), tmp_path)


def test_nastatistics_uses_comma_separator(tmp_path):
    data = pd.DataFrame({"Year": [2000.0], "Prec": [0.0], "TX": [2.0], "TN": [1.0]})
    written = write_outputs({"qc/nastatistics": data}, META, IndexParams(), tmp_path)
    lines = written["qc/nastatistics"].read_text().splitlines()
    assert lines[0] == '"Description: ",""'
    assert lines[-2:] == ["Year,Prec,TX,TN", "2000,0,2,1"]


def test_heatwave_files_follow_write_hw_csv(tmp_path):
    d = index_descriptions(IndexParams())
    assert d["TX90-HWM_ANN"] == "TX90 heatwave magnitude (HWM)"
    assert d["TN90-HWF_ANN"] == "TN90 heatwave frequency (HWF)"

    # Written even when missing for every year, with no standardised-anomaly column.
    tables = {
        "indices/TX90-HWN_ANN": pd.DataFrame({"time": [2000.0, 2001.0], "HWN": [2.0, np.nan]}),
        "indices/TN90-HWN_ANN": pd.DataFrame({"time": [2000.0, 2001.0], "HWN": [np.nan] * 2}),
    }
    written = write_outputs(tables, META, IndexParams(), tmp_path)
    assert set(written) == set(tables)
    assert written["indices/TX90-HWN_ANN"].read_text().splitlines()[-3:] == [
        "time, HWN",
        "2000, 2",
        "2001, -99.9",
    ]

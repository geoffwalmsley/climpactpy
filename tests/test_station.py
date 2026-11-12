import numpy as np
import pandas as pd
import pytest

from climpact.config import StationMetadata
from climpact.io.station import read_station_file, station_dataset
from climpact.station import load_station

from .parity.catalogue import REFERENCE_DIR, STATION

SAMPLE = REFERENCE_DIR.parent / "input" / f"{STATION}.txt"
META = StationMetadata(name="test")


def write(tmp_path, text):
    path = tmp_path / "station.txt"
    path.write_text(text)
    return path


def test_sample_station_file():
    df = read_station_file(SAMPLE)
    assert len(df) == 29220
    assert df["date"].iloc[0] == pd.Timestamp("1936-01-01")
    assert df["date"].iloc[-1] == pd.Timestamp("2015-12-31")

    raw = np.loadtxt(SAMPLE)
    for i, column in enumerate(["prcp", "tmax", "tmin"], start=3):
        assert df[column].isna().sum() == (raw[:, i] == -99.9).sum()


def test_missing_values_header_and_commas(tmp_path):
    path = write(
        tmp_path,
        "Year,Month,Day,PRCP,TMAX,TMIN\n2000,1,1,0.5,25.1,15.2\n2000,1,2,-99.9,-99.9,14.0\n",
    )
    df = read_station_file(path)
    assert len(df) == 2
    assert df["prcp"].tolist()[0] == 0.5
    assert np.isnan(df["prcp"].iloc[1]) and np.isnan(df["tmax"].iloc[1])
    assert df["tmin"].iloc[1] == 14.0


def test_invalid_dates_are_dropped(tmp_path):
    path = write(tmp_path, "2001 2 28 0 20 10\n2001 2 29 0 21 11\n2001 3 1 0 22 12\n")
    df = read_station_file(path)
    assert df["date"].dt.strftime("%m-%d").tolist() == ["02-28", "03-01"]


def test_wrong_number_of_columns_is_an_error(tmp_path):
    path = write(tmp_path, "2001 1 1 0 20\n")
    with pytest.raises(ValueError, match="expected 6"):
        read_station_file(path)


def test_dataset_covers_full_years_and_last_duplicate_wins(tmp_path):
    path = write(tmp_path, "2000 3 1 1.0 20 10\n2000 3 1 2.0 22 12\n2001 6 30 0 18 8\n")
    ds = station_dataset(read_station_file(path), META)

    assert ds.time.values[0] == np.datetime64("2000-01-01")
    assert ds.time.values[-1] == np.datetime64("2001-12-31")
    assert ds.sizes["time"] == 366 + 365
    day = ds.sel(time="2000-03-01")
    assert float(day.pr) == 2.0
    assert float(day.tas) == 17.0  # (22 + 12) / 2
    assert int(ds.pr.notnull().sum()) == 2


def test_load_station_carries_metadata():
    meta = StationMetadata(name=STATION, latitude=-33.86, longitude=151.21)
    run = load_station(SAMPLE, meta)
    assert run.data.attrs["station_name"] == STATION
    assert run.data.attrs["latitude"] == -33.86
    assert not run.metadata.northern_hemisphere
    assert run.data.tasmax.attrs["units"] == "degC"

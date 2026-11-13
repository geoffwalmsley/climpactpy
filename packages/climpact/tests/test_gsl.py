"""Growing season length against values printed by climdex.pcic's climdex.gsl
(tests/data/r_gsl.R) for tests/data/gsl_synthetic.txt, one scenario per year:

2001  5-day warm run in March (too short); 1 April exactly 5 degC (not warm); 5 cold days
      in October followed by a day of exactly 5 degC (not cold), so the season ends 1 November
2002  no 6-day warm run before 1 July (the run from 26 June crosses it): length 0
2003  a missing day breaks the spring run; no cold run, so the season ends 31 December
2004  cold from 1 July (north: the season ends on 1 July); no warm run July-December (south)
2005  4 missing days in February: missing in the north; the southern season 2004 (July 2004
      to June 2005) keeps its value, because R checks its months with the 15-day limit
2006  16 missing days in September: missing in both hemispheres
2007  southern season with no cold run: it ends on 30 June 2008
2008  leap year; the last southern season is always missing
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from climpact.config import StationMetadata
from climpact.io.climpact_csv import read_climpact_csv
from climpact.io.output_files import write_outputs
from climpact.products.indices import growing_season, growing_season_length
from climpact.station import load_station

DATA = Path(__file__).parent / "data" / "gsl_synthetic.txt"

# R output (r_gsl.R): year -> (start, sl, end); None is NA.
NORTH = {
    2001: ("2001-04-02", 213, "2001-11-01"),
    2002: (None, 0, None),
    2003: ("2003-04-05", 271, "2003-12-31"),
    2004: ("2004-04-01", 91, "2004-07-01"),
    2005: (None, None, None),
    2006: (None, None, None),
    2007: ("2007-04-01", 214, "2007-11-01"),
    2008: ("2008-01-01", 305, "2008-11-01"),
}
SOUTH = {
    2001: ("2001-07-01", 184, "2002-01-01"),
    2002: ("2002-07-01", 184, "2003-01-01"),
    2003: ("2003-07-01", 184, "2004-01-01"),
    2004: (None, 0, None),
    2005: ("2005-07-01", 184, "2006-01-01"),
    2006: (None, None, None),
    2007: ("2007-07-01", 366, "2008-06-30"),
    2008: (None, None, None),
}


def gsl(latitude: float):
    run = load_station(DATA, StationMetadata(name="gsl", latitude=latitude))
    df = growing_season_length(run)

    def value(x):
        return None if pd.isna(x) else x

    return {
        int(row.time): (value(row.start), value(row.sl) and int(row.sl), value(row.end))
        for row in df.itertuples()
    }


@pytest.mark.parametrize(
    ("latitude", "expected"),
    [(45.0, NORTH), (0.0, SOUTH), (-30.0, SOUTH)],
    ids=["north", "latitude 0 is southern", "south"],
)
def test_gsl_matches_r(latitude, expected):
    assert gsl(latitude) == expected


def test_end_date_is_first_cold_day_or_last_day_of_season():
    """R reports the first day of the cold run as the end when one is found
    (end - start = length), but the last day of the season when none is
    (end - start = length - 1)."""
    north = gsl(45.0)
    start, length, end = north[2001]
    assert (np.datetime64(end) - np.datetime64(start)).astype(int) == length
    start, length, end = north[2003]
    assert (np.datetime64(end) - np.datetime64(start)).astype(int) == length - 1


def test_file_is_written_as_r_writes_it(tmp_path):
    meta = StationMetadata(name="gsl", latitude=-30.0)
    run = load_station(DATA, meta)
    paths = write_outputs(growing_season(run), meta, run.params, tmp_path)
    lines = paths["indices/gsl_ANN"].read_text().splitlines()
    assert lines[0].startswith('"Description: ","Annual number of days between')
    assert lines[7:] == [
        "time, start, sl, end",
        "2001, 2001-07-01, 184, 2002-01-01",
        "2002, 2002-07-01, 184, 2003-01-01",
        "2003, 2003-07-01, 184, 2004-01-01",
        "2004, -99.9, 0, -99.9",
        "2005, 2005-07-01, 184, 2006-01-01",
        "2006, -99.9, -99.9, -99.9",
        "2007, 2007-07-01, 366, 2008-06-30",
        "2008, -99.9, -99.9, -99.9",
    ]
    assert len(read_climpact_csv(paths["indices/gsl_ANN"]).data) == 8

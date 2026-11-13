"""Sen's slope, its bounds and the trend file rows (``climpact.trends``, ``products.trends``).

The R values come from zyp 0.11-1, Kendall 2.2.2 and a copy of ``plot.call``'s seasonal
code in the reference image (``tests/data/r_trends.R``). The trend-file tests replay
R's row logic on synthetic tables, for cases no reference run has: an EHF trend left in
``mktrend``, a custom SPI/SPEI scale of 3 months, and missing series.
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from climpact.config import IndexParams
from climpact.io.output_files import index_files
from climpact.products.trends import season_function, seasonal_series, trend_file
from climpact.trends import (
    confint_zyp,
    kendall_var_s,
    min_trend_data,
    pairwise_slopes,
    sen_slope,
    sen_trend,
)

DATA = Path(__file__).parent / "data"


def _parse(field: str) -> float:
    return math.nan if field == "NA" else float.fromhex(field)


def r_output() -> dict[tuple[str, ...], np.ndarray]:
    out = {}
    for line in (DATA / "r_trends.txt").read_text().splitlines():
        kind, *fields = line.split()
        if kind in ("y", "trend"):
            key = (kind, fields.pop(0))
        elif kind == "season":
            key = (kind, fields.pop(0), fields.pop(0))
        else:
            key = (kind,)
        out[key] = np.array([_parse(f) for f in fields])
    return out


R = r_output()
CASES = sorted(key[1] for key in R if key[0] == "y")


def same(a: float, b: float) -> bool:
    return (math.isnan(a) and math.isnan(b)) or a == b


# --- Sen's slope and confint.zyp ----------------------------------------------------


def test_hand_computed_slope():
    # Pairwise slopes of (0, 1), (1, 3), (2, 2), (3, 5): 2, -1, 3 (lag 1), 0.5, 1 (lag 2),
    # 4/3 (lag 3); the median of the six is (1 + 4/3) / 2.
    x, y = np.arange(4.0), np.array([1.0, 3.0, 2.0, 5.0])
    assert pairwise_slopes(x, y).tolist() == [2.0, -1.0, 3.0, 0.5, 1.0, 4 / 3]
    slope, _ = sen_slope(x, y)
    assert slope == pytest.approx(7 / 6, rel=1e-15)


def test_hand_computed_odd_count():
    # Three slopes 1, 2 (lag 1) and 1.5 (lag 2): the median is the middle one.
    assert sen_slope(np.arange(3.0), np.array([1.0, 2.0, 4.0]))[0] == 1.5


def test_kendall_var_s_without_ties():
    # n (n - 1) (2n + 5) / 18 for n = 4, in single precision.
    assert kendall_var_s(np.arange(4.0), np.array([1.0, 3.0, 2.0, 5.0])) == float(
        np.float32(4 * 3 * 13) / np.float32(18)
    )


def test_kendall_needs_three_values():
    with pytest.raises(ValueError):
        kendall_var_s(np.arange(2.0), np.array([1.0, 2.0]))


@pytest.mark.parametrize("case", CASES)
def test_against_r(case):
    y1 = R[("y", case)]
    lower, slope, upper, var_s = R[("trend", case)]
    keep = ~np.isnan(y1)
    x, y = np.arange(len(y1), dtype=float)[keep], y1[keep]
    got_slope, slopes = sen_slope(x, y)
    assert kendall_var_s(x, y) == var_s
    assert got_slope == slope
    assert confint_zyp(x, y, slopes) == (lower, upper)


def test_sen_trend_matches_r_when_enough_data():
    y1 = R[("y", "decimals")]
    assert min_trend_data(y1)
    assert sen_trend(y1) == tuple(R[("trend", "decimals")][:3])


def test_sen_trend_missing_without_enough_data():
    # "short" has 10 values of 12 (enough), "three" only 3.
    assert not any(math.isnan(v) for v in sen_trend(R[("y", "short")]))
    assert all(math.isnan(v) for v in sen_trend(R[("y", "three")]))


def test_min_trend_data():
    def series(valid: int, total: int) -> np.ndarray:
        return np.r_[np.ones(valid), np.full(total - valid, np.nan)]

    assert min_trend_data(series(10, 14))  # 71% valid
    assert not min_trend_data(series(10, 15))  # 67% valid
    assert not min_trend_data(series(9, 9))  # fewer than 10 values
    assert min_trend_data(series(7, 10)) is False  # 70% but only 7 values
    assert min_trend_data(series(14, 20))  # exactly 70%


# --- seasonal series ----------------------------------------------------------------


@pytest.mark.parametrize("func", ["max", "sum", "mean"])
def test_seasonal_series_against_r(func):
    values = R[("monthly_values",)]
    months = np.tile(np.arange(1, 13), 10)
    years = np.repeat(np.arange(1961, 1971), 12)
    name = {"max": "txx", "sum": "prcptot", "mean": "tmm"}[func]
    got = seasonal_series(values, months, years, season_function(name))
    for season, series in got.items():
        expected = R[("season", func, season)]
        assert len(series) == len(expected)
        assert all(same(a, b) for a, b in zip(series, expected, strict=True)), season


def test_season_function_uses_output_names():
    # rx3day and r30mm are averaged: plot.call looks for "rxnday" and "rnnmm".
    x = np.array([1.0, 2.0, 6.0])
    assert season_function("rx1day")(x) == 6.0
    assert season_function("rx3day")(x) == 3.0
    assert season_function("r10mm")(x) == 9.0
    assert season_function("r30mm")(x) == 3.0
    assert season_function("tnn")(x) == 1.0
    assert season_function("fd")(x) == 3.0


# --- trend file rows ------------------------------------------------------------------

YEARS = np.arange(1961, 2001)
MONTHS = pd.Series([f"{y}-{m:02d}" for y in YEARS for m in range(1, 13)], dtype=object)
RNG = np.random.default_rng(18)


def fake_run(params: IndexParams | None = None) -> SimpleNamespace:
    time = pd.date_range("1961-01-01", "2000-12-31", freq="D")
    return SimpleNamespace(
        data=SimpleNamespace(time=SimpleNamespace(values=time.values)),
        params=params or IndexParams(),
    )


def annual(name: str, values: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"time": YEARS.astype(float), name: values})


def monthly(name: str, values: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"time": MONTHS, name: values})


def rows(tables, params=None) -> list[tuple]:
    table = trend_file(fake_run(params), tables)["trend/trend"]
    return list(table.itertuples(index=False, name=None))


def test_rows_follow_r_order_and_rules():
    nan = np.full(len(YEARS), np.nan)
    tables = {
        "indices/fd_ANN": annual("fd", RNG.poisson(3, len(YEARS)).astype(float)),
        "indices/fd_MON": monthly("fd", RNG.poisson(1, len(MONTHS)).astype(float)),
        "indices/su_ANN": annual("su", nan),  # missing throughout: no row
        "indices/txx_ANN": pd.DataFrame(
            {"time": YEARS.astype(float), "val": RNG.normal(30, 2, len(YEARS)), "ymd": None}
        ),
        "indices/tx95t_DAY": pd.DataFrame(
            {"time": np.nan, "tx95t": RNG.normal(25, 3, 365), "s": np.nan}
        ),
        "indices/gsl_ANN": pd.DataFrame(
            {
                "time": YEARS.astype(float),
                "start": "x",
                "sl": np.r_[RNG.normal(300, 5, 5), np.full(len(YEARS) - 5, np.nan)],
                "end": "x",
            }
        ),
    }
    got = rows(tables)
    names = [(r[0], r[1]) for r in got]
    assert names == [
        ("fd", "annual"),
        ("fd", "monthly"),
        ("fd", "DJF"),
        ("fd", "MAM"),
        ("fd", "JJA"),
        ("fd", "SON"),
        ("gsl", "annual"),
        ("txx", "annual"),
        ("tx95t", "NA"),
    ]
    assert all(r[2:4] == (1961, 2000) for r in got)
    assert all(math.isnan(v) for v in got[6][4:])  # gsl: 5 values, too few for a trend
    assert got[0][4:] == sen_trend(tables["indices/fd_ANN"]["fd"])
    assert got[8][4:] == sen_trend(tables["indices/tx95t_DAY"]["tx95t"])


def precindex_tables(index: str, scales=(3, 6, 12, 24)) -> dict[str, pd.DataFrame]:
    return {
        f"indices/{s}month_{index}_MON": monthly(index, RNG.normal(0, 1, len(MONTHS)))
        for s in scales
    }


def test_spi_spei_rows():
    tables = precindex_tables("spi") | precindex_tables("spei")
    got = rows(tables)
    labels = [(r[0], r[1]) for r in got]
    expected = [
        (f"{i}{s}", m)
        for i in ("spei", "spi")
        for s, ms in ((3, "FEB MAY AUG NOV"), (6, "APR OCT"), (12, "JUN DEC"))
        for m in ms.split()
    ]
    assert labels == expected  # no row for the whole series or the 24-month scale
    spi6 = tables["indices/6month_spi_MON"]["spi"].to_numpy()
    month = MONTHS.str[5:].astype(int).to_numpy()
    # "APR" is August, "JUN" January: plot.precindex's labels.
    assert got[expected.index(("spi6", "APR"))][4:] == sen_trend(spi6[month == 8])
    spi12 = tables["indices/12month_spi_MON"]["spi"].to_numpy()
    assert got[expected.index(("spi12", "JUN"))][4:] == sen_trend(spi12[month == 1])


def test_custom_scale_of_three_repeats_rows():
    tables = precindex_tables("spi", scales=(3, 6, 12))
    got = rows(tables, IndexParams(spei_months=3))
    labels = [r[1] for r in got]
    assert labels == "FEB MAY AUG NOV APR OCT JUN DEC FEB MAY AUG NOV".split()
    assert got[:4] == got[8:]


def test_ehf_trend_left_in_mktrend():
    # calculate.hwEHF does not remove mktrend. With no SPI/SPEI and tmm missing in every
    # year, index.calc writes the last EHF aspect's trend as tmm's annual row.
    hwn = RNG.poisson(2, len(YEARS)).astype(float)
    nan = np.full(len(YEARS), np.nan)
    tables = {
        "indices/EHF-HWN_ANN": annual("HWN", hwn),
        "indices/EHF-HWF_ANN": annual("HWF", nan),
        "indices/tmm_ANN": annual("tmm", nan),
        "indices/txm_ANN": annual("txm", nan),
    }
    assert rows(tables) == [("tmm", "annual", 1961, 2000, *sen_trend(hwn))]
    # Any SPI/SPEI scale with a value removes it.
    assert all(r[0].startswith("spi") for r in rows(tables | precindex_tables("spi")))


def test_custom_index_rows():
    params = IndexParams()
    name = params.custom.name
    tables = {
        f"indices/{name}_ANN": annual(name, RNG.poisson(3, len(YEARS)).astype(float)),
        f"indices/{name}_MON": monthly(name, RNG.poisson(1, len(MONTHS)).astype(float)),
    }
    assert [(r[0], r[1]) for r in rows(tables)] == [
        (name, f) for f in ("annual", "monthly", "DJF", "MAM", "JJA", "SON")
    ]


def test_index_files_lists_the_special_rows_in_order():
    shorts = [f[0] for f in index_files(IndexParams(), special=True)]
    assert shorts.index("txbdtnbd") < shorts.index("hw") < shorts.index("hwEHF")
    assert shorts.index("hwEHF") < shorts.index("spei") < shorts.index("spi")
    assert shorts.index("spi") < shorts.index("tmm")
    assert "hw" not in [f[0] for f in index_files(IndexParams())]

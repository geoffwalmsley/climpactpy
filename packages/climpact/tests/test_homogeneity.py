"""The ``detect`` homogeneity module (#34): synthetic breaks, outputs, options, the CLI."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from climpact.cli import main
from climpact.config import IndexParams, StationMetadata
from climpact.homogeneity.detect import (
    DETECT,
    METHODS,
    breaks_found,
    detect_breaks,
    find_breaks,
    read_station_history,
)
from climpact.homogeneity.series import ANNUAL, MONTHLY, Series, build_series
from climpact.io.climpact_csv import read_climpact_csv
from climpact.io.output_files import write_outputs
from climpact.io.station import station_dataset
from climpact.modules import ModuleOptionError, ModuleSelection, resolve, run_pipeline
from climpact.station import StationRun

YEARS = np.arange(1961, 2021)


def annual(values: np.ndarray, variable: str = "TX") -> Series:
    return Series(variable, ANNUAL, YEARS, np.zeros(YEARS.size, dtype=int), values, "degC")


def monthly(values: np.ndarray) -> Series:
    return Series(
        "TX", MONTHLY, np.repeat(YEARS, 12), np.tile(np.arange(1, 13), YEARS.size), values, "degC"
    )


def first_years(series: Series, method: str) -> list[int]:
    breaks, note = find_breaks(series, method)
    assert breaks is not None, note
    return [int(series.years[b.first_after]) for b in breaks if b.significance == "yes"]


# ---- synthetic series -------------------------------------------------------------------


@pytest.mark.parametrize("method", METHODS)
def test_a_1degc_break_is_found_at_the_right_year(method):
    """A 1 degC step in 1991 in annual series with white noise of 0.25 degC: each method
    finds a significant break that starts in 1991 in at least 90% of 50 series."""
    hits = 0
    for seed in range(50):
        x = np.random.default_rng(seed).normal(15, 0.25, YEARS.size)
        x[YEARS >= 1991] += 1.0
        hits += 1991 in first_years(annual(x), method)
    assert hits >= 45


# Of 50 series: Pettitt 46, SNHT 43, PMT 42, PMF 27. PMF fits a linear trend as well,
# which takes up part of a step in the middle of the series, so it finds fewer.
NOISIER_HITS = {"pettitt": 40, "snht": 40, "pmt": 40, "pmf": 25}


@pytest.mark.parametrize("method", METHODS)
def test_a_1degc_break_in_noisier_series_is_found_within_a_year(method):
    """With noise of 0.5 degC, a significant break is found within a year of 1991."""
    hits = 0
    for seed in range(50):
        x = np.random.default_rng(100 + seed).normal(15, 0.5, YEARS.size)
        x[YEARS >= 1991] += 1.0
        hits += any(abs(year - 1991) <= 1 for year in first_years(annual(x), method))
    assert hits >= NOISIER_HITS[method]


@pytest.mark.parametrize("method", METHODS)
def test_a_1degc_break_in_a_monthly_series_is_found_within_a_year(method):
    """Monthly series with an annual cycle and noise of 1 degC: a significant break starts
    within 12 months of January 1991 in at least 18 of 20 series (every method finds all
    20)."""
    month = np.tile(np.arange(1, 13), YEARS.size)
    cycle = 10 * np.sin(2 * np.pi * (month - 4) / 12)
    hits = 0
    for seed in range(20):
        x = 15 + cycle + np.random.default_rng(200 + seed).normal(0, 1.0, month.size)
        x[np.repeat(YEARS, 12) >= 1991] += 1.0
        series = monthly(x)
        breaks, _ = find_breaks(series, method)
        starts = [
            12 * series.years[b.first_after] + series.months[b.first_after] - 1
            for b in breaks
            if b.significance == "yes"
        ]
        hits += any(abs(start - 12 * 1991) <= 12 for start in starts)
    assert hits >= 18


# Series of white noise (60 values) with at least one significant break ("yes"), of 400,
# at the 95% level: Pettitt 12 (3.0%; its p-value approximation is conservative), SNHT 15
# (3.75%), PMF 26 (6.5%), PMT 46 (11.5%). Pettitt, SNHT and PMF are allowed three
# binomial standard errors above the nominal 5%. PMT's rate is RHtests' own: R's
# FindU.wRef gives the same changepoints as the port on the 40 white-noise series of the
# synthetic reference run (3 with a "Yes"; tests/test_homogeneity_rhtests.py). Its search
# adds changepoints at the lower critical value and labels each on the segment between
# its neighbours, which raises the rate above that of a single test.
FALSE_POSITIVE_SERIES = 400
NOMINAL_LIMIT = 0.05 + 3 * np.sqrt(0.05 * 0.95 / FALSE_POSITIVE_SERIES)
FALSE_POSITIVE_LIMIT = {"pettitt": NOMINAL_LIMIT, "snht": NOMINAL_LIMIT, "pmf": NOMINAL_LIMIT}
FALSE_POSITIVE_LIMIT["pmt"] = 0.15


@pytest.mark.parametrize("method", METHODS)
def test_white_noise_false_alarm_rate(method):
    found = 0
    for seed in range(FALSE_POSITIVE_SERIES):
        x = np.random.default_rng(10_000 + seed).normal(15, 0.5, YEARS.size)
        found += bool(first_years(annual(x), method))
    assert found / FALSE_POSITIVE_SERIES <= FALSE_POSITIVE_LIMIT[method]


def test_missing_years_are_skipped_and_the_break_reported_between_the_values():
    x = np.random.default_rng(5).normal(15, 0.2, YEARS.size)
    x[YEARS >= 1991] += 1.5
    x[(YEARS >= 1989) & (YEARS <= 1990)] = np.nan
    for method in METHODS:
        breaks, _ = find_breaks(annual(x), method)
        main_break = max(breaks, key=lambda b: abs(b.shift))
        assert (YEARS[main_break.last_before], YEARS[main_break.first_after]) == (1988, 1991)
        assert main_break.shift == pytest.approx(1.5, abs=0.3)


def test_short_series_are_not_tested():
    x = np.full(YEARS.size, np.nan)
    x[:9] = np.random.default_rng(1).normal(15, 0.5, 9)
    for method in ("pettitt", "snht"):
        assert find_breaks(annual(x), method) == (None, "9 values; at least 10 are needed")
    for method in ("pmf", "pmt"):
        breaks, note = find_breaks(annual(x), method)
        assert breaks is None and note.startswith("RHtests: ")


def test_unknown_method():
    with pytest.raises(ValueError, match="unknown method 'cusum'"):
        find_breaks(annual(np.zeros(YEARS.size)), "cusum")


# ---- a synthetic station ------------------------------------------------------------------


def synthetic_run(step: float = 1.5, name: str = "synth") -> StationRun:
    """60 years of daily data: TX with a step of ``step`` degC from 1991, TN and PRCP
    without one."""
    days = pd.date_range("1961-01-01", "2020-12-31", freq="D")
    rng = np.random.default_rng(34)
    season = 8 * np.sin(2 * np.pi * (days.day_of_year.to_numpy() - 100) / 365.25)
    yearly = rng.normal(0, 0.15, YEARS.size)[days.year.to_numpy() - 1961]
    tmax = 22 + season + yearly + rng.normal(0, 2, days.size) + step * (days.year >= 1991)
    tmin = tmax - 9 - step * (days.year >= 1991) + rng.normal(0, 1, days.size)
    prcp = np.where(rng.uniform(size=days.size) < 0.3, rng.gamma(0.8, 6, days.size), 0.0)
    df = pd.DataFrame(
        {"date": days, "prcp": prcp.round(1), "tmax": tmax.round(1), "tmin": tmin.round(1)}
    )
    metadata = StationMetadata(name, latitude=-30, longitude=150)
    return StationRun(data=station_dataset(df, metadata), metadata=metadata)


@pytest.fixture(scope="module")
def run():
    return synthetic_run()


@pytest.fixture(scope="module")
def tables(run):
    return DETECT.homogenise(run, {}).tables


def test_detect_finds_the_tx_break_and_leaves_the_data(run):
    result = run_pipeline(run, ModuleSelection(qc=(), homogeneity="detect", indices=()))
    assert not result.adjusted
    breaks = result.tables["homogeneity/breaks"]
    tx = breaks[(breaks["variable"] == "TX") & (breaks["series"] == "annual")]
    yes = tx[tx["significance"] == "yes"]
    assert set(yes["method"]) == set(METHODS)
    assert (yes["first_after"] == "1991").all()
    assert (yes["last_before"] == "1990").all()
    assert yes["shift"].to_numpy() == pytest.approx(1.5, abs=0.25)
    assert (yes["units"] == "degC").all()
    assert breaks_found(result.tables)


def test_tests_table_has_a_row_per_series_and_method(tables):
    tests = tables["homogeneity/tests"]
    series = [("TX", "annual"), ("TX", "monthly"), ("TN", "annual"), ("TN", "monthly")]
    series.append(("PRCP", "annual"))
    expected = [(v, f, m) for v, f in series for m in METHODS]
    assert list(zip(tests["variable"], tests["series"], tests["method"], strict=True)) == expected
    tx = tests[(tests["variable"] == "TX") & (tests["series"] == "annual")]
    assert (tx["status"] == "breaks found").all()
    assert (tx["values"] == 60).all()
    assert (tx["first"] == "1961").all() and (tx["last"] == "2020").all()
    monthly_tx = tests[(tests["variable"] == "TX") & (tests["series"] == "monthly")]
    assert (monthly_tx["first"] == "1961-01").all() and (monthly_tx["values"] == 720).all()


def test_prcp_shifts_are_percentages(tables):
    breaks = tables["homogeneity/breaks"]
    assert (breaks.loc[breaks["variable"] == "PRCP", "units"] == "%").all()


def test_series_values_are_the_climdex_means(run):
    tx = build_series(run, "TX", ANNUAL)
    days = run.data["tasmax"].sel(time="1975")
    assert tx.values[tx.years == 1975][0] == pytest.approx(float(days.mean()), abs=1e-12)
    prcp = build_series(run, "PRCP", ANNUAL)
    total = float(run.data["pr"].sel(time="1975").sum())
    assert prcp.values[prcp.years == 1975][0] == pytest.approx(np.log(total), abs=1e-12)
    with pytest.raises(ValueError, match="annual totals only"):
        build_series(run, "PRCP", MONTHLY)


def test_missing_months_follow_the_climdex_rules():
    run = synthetic_run()
    data = run.data.copy(deep=True)
    tasmax = data["tasmax"].values.copy()
    days = pd.DatetimeIndex(data["time"].values)
    tasmax[(days >= "1975-03-01") & (days <= "1975-03-04")] = np.nan  # 4 days: month missing
    data["tasmax"] = ("time", tasmax)
    run = StationRun(data=data, metadata=run.metadata)
    tx = build_series(run, "TX", MONTHLY)
    assert np.isnan(tx.values[(tx.years == 1975) & (tx.months == 3)]).all()
    assert np.isnan(build_series(run, "TX", ANNUAL).values[YEARS == 1975]).all()
    assert not np.isnan(build_series(run, "TN", ANNUAL).values[YEARS == 1975]).any()


# ---- options ---------------------------------------------------------------------------------


def test_default_options():
    loaded = resolve(ModuleSelection(homogeneity="detect"))
    assert loaded.homogeneity is DETECT
    assert loaded.options[("homogeneity", "detect")] == {
        "methods": "pettitt,snht,pmf,pmt",
        "variables": "TX,TN,PRCP",
        "series": "annual,monthly",
        "level": 0.95,
        "min_years": 5,
        "station_history": "",
    }


def _resolve(**options):
    return resolve(
        ModuleSelection(homogeneity="detect", options={"homogeneity": {"detect": options}})
    )


def test_options_are_checked_before_a_run():
    assert (
        _resolve(methods=" snht , pettitt,snht").options[("homogeneity", "detect")]["methods"]
        == "snht,pettitt"
    )
    with pytest.raises(ModuleOptionError, match="'cusum' is not one of pettitt, snht"):
        _resolve(methods="pettitt,cusum")
    with pytest.raises(ModuleOptionError, match="choose at least one"):
        _resolve(variables=" , ")
    with pytest.raises(ModuleOptionError, match="'weekly' is not one of annual, monthly"):
        _resolve(series="weekly")
    with pytest.raises(ModuleOptionError, match="level.*not one of"):
        _resolve(level="0.97")
    with pytest.raises(ModuleOptionError, match="expected at least 1"):
        _resolve(min_years="0")


def test_options_choose_the_tests(run):
    breaks, tests = detect_breaks(run, methods=("pmt", "pettitt"), variables=("TN",))
    assert list(zip(tests["variable"], tests["series"], tests["method"], strict=True)) == [
        ("TN", "annual", "pettitt"),
        ("TN", "annual", "pmt"),
        ("TN", "monthly", "pettitt"),
        ("TN", "monthly", "pmt"),
    ]
    _, tests = detect_breaks(run, frequencies=("annual",), min_years=31)
    assert (tests.loc[tests["method"] == "pettitt", "status"] == "not tested").all()
    assert tests.loc[tests["method"] == "pettitt", "note"].iloc[0] == (
        "60 values; at least 62 are needed"
    )
    with pytest.raises(ValueError, match="level must be one of"):
        detect_breaks(run, level=0.5)


# ---- station history -----------------------------------------------------------------------


def test_station_history_is_shown_next_to_breaks(tmp_path, run):
    history = tmp_path / "history.csv"
    history.write_text(
        "station,date,event\n"
        'synth,1990-06,"Screen replaced, Stevenson to plastic"\n'
        "synth,1950,Station opened\n"
        "other,1991-01-01,Not this station\n",
        encoding="utf-8",
    )
    events = read_station_history(history, "synth")
    assert [e.text for e in events] == ["Station opened", "Screen replaced, Stevenson to plastic"]
    breaks, _ = detect_breaks(run, methods=("pettitt",), variables=("TX",), history=events)
    row = breaks[breaks["series"] == "annual"].iloc[0]
    assert row["station_history"] == "1990-06-01: Screen replaced; Stevenson to plastic"


def test_station_history_option_reaches_the_tables(tmp_path, run):
    history = tmp_path / "history.csv"
    history.write_text("date,event\n1991-02-03,Moved 2 km north\n", encoding="utf-8")
    selection = ModuleSelection(
        qc=(),
        homogeneity="detect",
        indices=(),
        options={"homogeneity": {"detect": {"methods": "snht", "station_history": str(history)}}},
    )
    breaks = run_pipeline(run, selection).tables["homogeneity/breaks"]
    tx = breaks[(breaks["variable"] == "TX") & (breaks["series"] == "annual")]
    assert tx["station_history"].tolist() == ["1991-02-03: Moved 2 km north"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("when,what\n1990,x\n", "needs the columns date and event"),
        ("date,event\n1990/05/01,x\n", "line 2: date '1990/05/01' is not YYYY-MM-DD"),
        ("date,event\n1990,x\n1991,New screen, plastic\n", "line 3: more fields than columns"),
    ],
)
def test_bad_station_history(tmp_path, text, message):
    history = tmp_path / "history.csv"
    history.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        read_station_history(history, "synth")
    with pytest.raises(ValueError, match="station history file not found"):
        read_station_history(tmp_path / "nope.csv", "synth")


# ---- files and the command line ---------------------------------------------------------


def test_files_are_written_with_a_header(tmp_path, run, tables):
    written = write_outputs(dict(tables), run.metadata, IndexParams(), tmp_path)
    breaks = read_climpact_csv(written["homogeneity/breaks"])
    assert written["homogeneity/breaks"] == tmp_path / "synth" / "homogeneity" / "synth_breaks.csv"
    assert breaks.metadata["Description"].startswith("Candidate breaks found by homogeneity")
    assert breaks.columns == list(tables["homogeneity/breaks"].columns)
    tests = read_climpact_csv(written["homogeneity/tests"])
    assert len(tests.data) == len(tables["homogeneity/tests"])


def test_cli_runs_detect(tmp_path, capsys):
    run = synthetic_run(name="clistation")
    station = tmp_path / "clistation.txt"
    days = pd.DatetimeIndex(run.data["time"].values)
    pd.DataFrame(
        {
            "year": days.year,
            "month": days.month,
            "day": days.day,
            "prcp": run.data["pr"].values,
            "tmax": run.data["tasmax"].values,
            "tmin": run.data["tasmin"].values,
        }
    ).to_csv(station, sep=" ", header=False, index=False)
    args = ["run", str(station), "--out", str(tmp_path / "out"), "--indices", ""]
    args += ["--homogeneity", "detect", "--module-option", "detect.methods=pettitt"]
    args += ["--module-option", "detect.series=annual"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Homogeneity: breaks found by 1 of 3 tests: TX annual (pettitt)" in out
    folder = tmp_path / "out" / "clistation" / "homogeneity"
    assert sorted(p.name for p in folder.iterdir()) == [
        "clistation_breaks.csv",
        "clistation_tests.csv",
    ]


def test_cli_lists_the_options(capsys):
    assert main(["modules"]) == 0
    out = capsys.readouterr().out
    assert "  detect (built-in)" in out
    assert "    level (float, default 0.95) one of 0.75, 0.8, 0.9, 0.95, 0.99, 0.9999" in out

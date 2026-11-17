"""One index's page (#237): its chart, statistics and table (stations/index_page.py), on
small series made here, so each rule is checked without a run."""

import datetime
import math
from types import SimpleNamespace

import numpy as np
import pytest

from climpact.plots import IndexPlot
from climpact.trends import PlotTrend
from climpact_web.core import numbers
from climpact_web.stations import index_page

NAN = float("nan")


def annual(values, first=1961, trend=None, bars=False, name="txx_ANN"):
    n = len(values)
    return IndexPlot(
        name, "txx: Annual warmest daily TX", "degrees_C",
        np.arange(first, first + n, dtype=float), np.array(values, dtype=float),
        "year", bars, trend,
    )  # fmt: skip


def monthly(values, first=1961, name="txx_MON"):
    n = len(values)
    x = first + (np.arange(n) + 0.5) / 12
    return IndexPlot(name, "txx: Monthly", "degrees_C", x, np.array(values, dtype=float),
                     "month", False, None)  # fmt: skip


def card(key="txx", code="TXx", units="°C"):
    return SimpleNamespace(key=key, code=code, units=units, title="Hottest day", trend=None)


def test_anomalies_are_from_the_base_period_mean():
    plot = annual([10.0, 12.0, 14.0, 20.0])
    assert index_page.base_mean(plot, (1961, 1962)) == 11.0
    assert index_page.anomalies(plot, (1961, 1962)) == [-1.0, 1.0, 3.0, 9.0]
    # Without a base period inside the series there is no anomaly view.
    assert index_page.anomalies(plot, (1900, 1910)) is None
    assert not index_page.has_anomalies(plot, (1900, 1910))
    # SPI and SPEI, already standardised (bars), have none either.
    assert not index_page.has_anomalies(annual([1.0, -1.0], bars=True), (1961, 1962))


def test_monthly_anomalies_are_from_each_calendar_month():
    """A month's anomaly is from the base period's mean of the same calendar month, so a
    monthly anomaly is not the season."""
    plot = monthly([float(m) for m in range(12)] + [float(m) + 2 for m in range(12)])
    assert index_page.anomalies(plot, (1961, 1961)) == [0.0] * 12 + [2.0] * 12


def test_running_mean_needs_half_its_window():
    values = [1.0, 2.0, 3.0, None, 5.0, None, None, None, 9.0]
    assert index_page.running_mean(values, 3) == [None, 2.0, 2.5, 4.0] + [None] * 5


def test_round_ticks_cover_the_values():
    assert index_page.nice_ticks(32.5, 45.8) == [30, 35, 40, 45, 50]
    assert index_page.nice_ticks(-3.4, 4.2) == [-4, -2, 0, 2, 4, 6]
    assert index_page.nice_ticks(0.0, 0.0)[0] == 0.0
    assert index_page._year_ticks(1936, 2015) == [1936, 1956, 1976, 1996, 2015]
    assert index_page._year_ticks(1990, 2000) == [1990, 1992, 1994, 1996, 1998, 2000]


def test_the_record_is_the_highest_or_for_cold_and_drought_the_lowest():
    assert index_page._ranks([3.0, 5.0, None, 5.0, 1.0], low=False) == [3, 1, None, 1, 4]
    assert index_page._ranks([3.0, 5.0, 1.0], low=True) == [2, 3, 1]
    assert index_page.low_is_record("tnn") and index_page.low_is_record("3month_spi")
    assert not index_page.low_is_record("txx")
    plot = annual([40.0, 45.8, 30.0])
    assert index_page.record(card(), plot) == f"45.8{numbers.NBSP}°C, 1962"
    assert index_page.record(card("tnn", "TNn"), plot) == f"30{numbers.NBSP}°C, 1963"


def test_why_each_value_was_left_out():
    """A year without a value: the days the file misses (the completeness rule), or no
    value at all; a month after the first value fails the monthly rule; SPI's first
    months, before any value, simply have none."""
    plot = annual([40.0, NAN, 41.0, NAN])
    gone = index_page.left_out(plot, {1962: 41, 1964: 0})
    assert [g["when"] for g in gone] == ["1962", "1964"]
    assert gone[0]["note"] == "Left out: 41 days missing"
    assert gone[0]["sentence"] == (
        "1962 left out: 41 days missing, so the year fails the completeness rule."
    )
    assert gone[1]["note"] == "No value" and gone[1]["sentence"] == "1964 has no value."
    months = monthly([NAN, NAN, 1.0, NAN, 2.0])
    gone = index_page.left_out(months, {})
    assert [g["note"] for g in gone] == ["No value", "No value", "Left out: incomplete"]
    # More than three: a count, and the table says which.
    many = index_page.left_out(monthly([NAN] * 5 + [1.0]), {})
    assert index_page.left_out_summary(months, many) == [
        "5 months have no value. The table says why."
    ]


def test_missing_days_are_the_most_of_the_variables_an_index_needs():
    analysis = SimpleNamespace(
        summary={"years": [{"year": 1962, "days": 365, "prcp": 360, "tmax": 324, "tmin": 340}]}
    )
    assert index_page.missing_days(analysis, ("tmax", "tmin")) == {1962: 41}
    assert index_page.missing_days(analysis, ("prcp",)) == {1962: 5}
    assert index_page.missing_days(SimpleNamespace(summary=None), ("prcp",)) == {}


def test_the_table_most_recent_first_with_dates_of_the_extremes():
    plot = annual([40.0, NAN, 45.8])
    days = annual([32.0, NAN, 365.0], name="day_of_txx_ANN")
    gone = index_page.left_out(plot, {1962: 20})
    rows = index_page.table(card(), plot, days, (1961, 1963), gone)
    assert [r["when"] for r in rows] == ["1963", "1962", "1961"]
    assert rows[0] == {
        "when": "1963", "value": "45.8", "anomaly": "+2.9", "rank": "1",
        "date": "1963-12-31", "note": "Record", "missing": False,
    }  # fmt: skip
    assert rows[1]["value"] == "–" and rows[1]["note"] == "Left out: 20 days missing"
    assert rows[2]["date"] == "1961-02-01" and rows[2]["anomaly"] == f"{numbers.MINUS}2.9"
    # Monthly: the day of the month.
    month = monthly([30.0, 31.0])
    day = monthly([5.0, 28.0], name="day_of_txx_MON")
    assert [r["date"] for r in index_page.table(card(), month, day, None, [])] == [
        "1961-02-28",
        "1961-01-05",
    ]


def test_the_chart_marks():
    """Values with a gap, the running mean, Sen's slope and its interval as a band through
    the slope's middle, the base period as a band, a year left out as an open point at
    the base-period mean, and axes titled with the code and units."""
    values = [38.0 + (i % 5) for i in range(30)]
    values[10] = NAN
    trend = PlotTrend(lower=-0.01, slope=0.02, upper=0.05, intercept=39.0, p_value=0.5)
    plot = annual(values, trend=trend)
    chart = index_page.chart(card(), plot, (1971, 1980))
    assert chart.line.count("M") == 2  # the gap
    assert chart.smooth and chart.trend and chart.interval
    assert chart.band and chart.band["width"] > 0
    assert len(chart.gaps) == 1
    base = index_page.base_mean(plot, (1971, 1980))
    low, high = float(chart.y_ticks[-1]["text"]), float(chart.y_ticks[0]["text"])
    expected = index_page.BOTTOM - (base - low) / (high - low) * (
        index_page.BOTTOM - index_page.TOP
    )
    assert math.isclose(chart.gaps[0]["y"], expected, abs_tol=0.1)
    # The interval is a bow tie: both slopes' lines meet at the slope's middle.
    points = [tuple(map(float, p.split(","))) for p in chart.interval.split()]
    assert points[1] == points[4]
    assert chart.y_title == "TXx °C"
    assert [t["text"] for t in chart.x_ticks] == ["1961", "1971", "1981", "1990"]
    anomaly = index_page.chart(card(), plot, (1971, 1980), anomaly=True)
    assert anomaly.y_title == "Anomaly °C" and anomaly.zero is not None
    assert any(t["text"].startswith("+") for t in anomaly.y_ticks)
    # Every value missing: nothing to draw.
    assert index_page.chart(card(), annual([NAN, NAN]), None) is None


@pytest.mark.parametrize("base", [(1961, 1990), None])
def test_the_citation_names_the_station_index_years_and_software(base):
    analysis = SimpleNamespace(station_name="Sydney", file_name="sydney.txt")
    text = index_page.citation(
        analysis, card(), annual([1.0] * 55), base, "0.1.3", datetime.date(2026, 11, 17)
    )
    assert text.startswith("Sydney, TXx (Hottest day), 1961–2015")
    assert ("base period 1961–1990" in text) == bool(base)
    assert "climpact 0.1.3" in text and text.endswith("Accessed 2026-11-17.")

"""Chart data (#75): compact, columnar JSON for the interactive charts.

Two kinds, each built from files the core reads or writes, so a chart shows exactly what
the downloads hold:

``daily``
    A station's daily series for the quality checks: one value per day from the first
    row's date to the last (the core's :func:`~climpact.io.station.merged_rows`, a
    repeated date taking its last row, as the indices do), missing values as ``null`` (the
    chart draws them as gaps), and the values the core's QC checks flag
    (:mod:`climpact.qc`, with the given :class:`~climpact.config.QCParams`).

``index``
    One index series of a finished run (``txx_ANN``, ``txx_MON``, ``3month_spi_MON``,
    ``day_of_txx_ANN`` ...) with its trend. The series, positions, description, units,
    bars and trend come from :func:`climpact.plots.index_plots`, the function the static
    plots use, so the trend line is the trend file's Sen's slope with ``zyp.sen``'s
    intercept, as drawn in the PNGs.

Every payload carries ``summary``, a plain-language description (period, extremes,
missing values, trend) that the chart frame shows and screen readers announce.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from django.utils.formats import number_format
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from climpact_web.core import numbers

VARIABLES = ("tmax", "tmin", "prcp")
# The variables a daily chart can show on its own (the QC screen, #77): DTR is TX - TN.
DAILY_VARIABLES = ("tmax", "tmin", "dtr", "prcp")
SCHEMA_VERSION = 1

# The number rules live in core.numbers (#226); these names are kept for the callers.
trend_units = numbers.trend_units
with_units = numbers.with_unit
number = numbers.number


def attr_json(data: dict) -> str:
    """``data`` as compact JSON for a single-quoted HTML attribute (``data-readout='…'``,
    #283): only ``&``, ``<``, ``>`` and ``'`` escaped, so the page carries no ``&quot;``."""
    import json

    from django.utils.safestring import mark_safe

    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    for c, entity in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ("'", "&#39;")):
        text = text.replace(c, entity)
    # Safe: every character that could end the attribute or start markup is escaped.
    return mark_safe(text)


def shown(value: float | None, digits: int | None = None) -> float | None:
    """A value rounded as a read-out writes it (``core.numbers.number``: two places below
    10, one from 10), so a read-out's data carries no more figures than it shows. With
    ``digits`` (an anomaly's one place), rounded as ``core.numbers.anomaly`` rounds it, so
    the read-out, which formats it again, shows the statistics' number (#349)."""
    if value is None or value != value:
        return None
    value = float(value)
    if digits is not None:
        return numbers.rounded(value, digits)
    return round(value, 2 if abs(value) < 10 else 1)


def _finite(values) -> list[float | None]:
    return [None if v is None or v != v else float(v) for v in values]


# ---- daily ---------------------------------------------------------------------------


def variable_meta() -> dict[str, dict]:
    return {
        "tmax": {
            "label": _("Maximum temperature"),
            "short": _("TX"),
            "unit": "°C",
            "panel": "temperature",
            "token": "--chart-tmax",
        },
        "tmin": {
            "label": _("Minimum temperature"),
            "short": _("TN"),
            "unit": "°C",
            "panel": "temperature",
            "token": "--chart-tmin",
        },
        "prcp": {
            "label": _("Precipitation"),
            "short": _("PR"),
            "unit": _("mm"),
            "panel": "precipitation",
            "token": "--chart-prcp",
        },
        "dtr": {
            "label": _("Diurnal temperature range"),
            "short": _("DTR"),
            "unit": "°C",
            "panel": "dtr",
            "token": "--chart-7",
        },
    }


def check_labels() -> dict[str, str]:
    """The QC checks that flag values, by their file name (``QC_REPORTS``)."""
    return {
        "outliers": _("Outlier (monthly box plot)"),
        "toolarge": _("Too large"),
        "tmaxmin": _("TN at or above TX"),
        "tx_jumps": _("Large day-to-day change"),
        "tn_jumps": _("Large day-to-day change"),
        "tx_flatline": _("Repeated values"),
        "tn_flatline": _("Repeated values"),
        "duplicates": _("Repeated date"),
    }


_OUTLIER_VARIABLES = {
    "Prec": ("prcp",),
    "TX": ("tmax",),
    "TN": ("tmin",),
    "DTR": ("tmax", "tmin", "dtr"),
}


def qc_flags(rows, params=None) -> list[tuple[str, str, str]]:
    """``(date, variable, check)`` for each value the core's QC checks flag in ``rows``
    (:func:`~climpact.io.station.merged_rows`), dates as ``YYYY-MM-DD``.

    Each flag is placed on the value the check reports: the outlier's variable (a DTR
    outlier on both temperatures and on DTR), each value over the ``toolarge`` limits,
    both temperatures and DTR for ``tmaxmin``, the date a jump or flatline is reported
    on (the first of the two days compared; the second-last day of a run), and every
    variable of a repeated date (``duplicates``).
    """
    import numpy as np
    import pandas as pd

    from climpact import qc
    from climpact.config import QCParams

    params = params or QCParams()

    def dates(table) -> list[str]:
        parsed = pd.to_datetime(table["Date"], format="%Y-%m-%d")
        return [d.date().isoformat() for d in parsed]

    flags: list[tuple[str, str, str]] = []
    out = qc.outliers(rows, params)
    for date, section in zip(dates(out), out["Section"], strict=True):
        for variable in _OUTLIER_VARIABLES[str(section).split()[0]]:
            flags.append((date, variable, "outliers"))
    big = qc.too_large(rows, params)
    t, p = params.temp_max, params.prec_max
    for date, prec, tx, tn in zip(dates(big), big["Prec"], big["TX"], big["TN"], strict=True):
        with np.errstate(invalid="ignore"):
            if prec > p or prec < 0:
                flags.append((date, "prcp", "toolarge"))
            if abs(tx) > t:
                flags.append((date, "tmax", "toolarge"))
            if abs(tn) > t:
                flags.append((date, "tmin", "toolarge"))
    for date in dates(qc.tmax_le_tmin(rows)):
        flags += [(date, v, "tmaxmin") for v in ("tmax", "tmin", "dtr")]
    for variable, prefix in (("tmax", "tx"), ("tmin", "tn")):
        flags += [(d, variable, f"{prefix}_jumps") for d in dates(qc.jumps(rows, variable, params))]
        flags += [
            (d, variable, f"{prefix}_flatline") for d in dates(qc.flatline(rows, variable, params))
        ]
    repeated = qc.duplicate_dates(rows).rename(columns={"Dates_duplicated": "Date"})
    for date in dict.fromkeys(dates(repeated)):
        flags += [(date, v, "duplicates") for v in DAILY_VARIABLES]
    return flags


def daily_payload(
    station_file: str | Path,
    qc_params=None,
    title: str = "",
    variable: str | None = None,
    flags: bool = True,
) -> dict:
    """The ``daily`` payload of a station file: TX and TN, and precipitation, or with
    ``variable`` (one of :data:`DAILY_VARIABLES`) that variable alone, as the QC screen
    shows them. ``x`` is implicit: day ``i`` is ``start`` plus ``i`` days, so only the
    values travel. With ``flags=False`` (the Load step, #173) no value is flagged and the
    summary says nothing about the quality checks, which come in the next step."""
    from climpact.io.station import merged_rows, read_station_file

    rows = merged_rows(read_station_file(station_file))
    days = rows.drop_duplicates(subset="date", keep="last").reset_index(drop=True)
    days["dtr"] = days["tmax"] - days["tmin"]
    start = days["date"].iloc[0]
    position = {d.date().isoformat(): i for i, d in enumerate(days["date"])}
    meta = variable_meta()
    keys = (variable,) if variable else VARIABLES
    series = [{"key": key, **meta[key], "values": _finite(days[key])} for key in keys]
    points = (
        sorted(
            {
                (position[d], v, c)
                for d, v, c in qc_flags(rows, qc_params)
                if d in position and v in keys
            }
        )
        if flags
        else []
    )
    panels = {
        "temperature": _("Temperature (°C)"),
        "precipitation": _("Precipitation (mm)"),
        "dtr": _("Diurnal temperature range (°C)"),
    }
    payload = {
        "kind": "daily",
        "version": SCHEMA_VERSION,
        "title": title or _("Daily series"),
        "start": start.date().isoformat(),
        "days": len(days),
        "series": series,
        "panels": {s["panel"]: panels[s["panel"]] for s in series},
        "flags": {
            "checks": check_labels(),
            "label": _("Flagged by the quality checks"),
            "points": [list(p) for p in points],
        },
    }
    payload["summary"] = daily_summary(payload, flags=flags)
    return payload


def _when(start, index: int) -> str:
    import datetime as dt

    day = dt.date.fromisoformat(start) + dt.timedelta(days=index)
    return day.isoformat()  # as the station files, the tables and R's outputs (#115)


def daily_summary(payload: dict, flags: bool = True) -> str:
    start, days = payload["start"], payload["days"]
    parts = [
        _("%(first)s to %(last)s, %(days)s days.")
        % {
            "first": _when(start, 0),
            "last": _when(start, days - 1),
            "days": number_format(days, force_grouping=True),
        }
    ]
    for s in payload["series"]:
        present = [(v, i) for i, v in enumerate(s["values"]) if v is not None]
        missing = days - len(present)
        missing_text = ngettext("%(n)s day missing", "%(n)s days missing", missing) % {
            "n": number_format(missing, force_grouping=True)
        }
        if not present:
            parts.append(_("%(label)s: no data.") % {"label": s["label"]})
            continue
        low, high = min(present), max(present)
        values = {
            "label": s["label"],
            "low": with_units(number(low[0], 1), s["unit"]),
            "low_date": _when(start, low[1]),
            "high": with_units(number(high[0], 1), s["unit"]),
            "high_date": _when(start, high[1]),
            "missing": missing_text,
        }
        if s["key"] == "prcp":
            text = _("%(label)s: wettest day %(high)s on %(high_date)s; %(missing)s.")
        else:
            text = _(
                "%(label)s: from %(low)s on %(low_date)s to %(high)s on %(high_date)s; %(missing)s."
            )
        parts.append(text % values)
    flagged = len(payload["flags"]["points"])
    if flags and flagged:
        parts.append(
            ngettext(
                "%(n)s value flagged by the quality checks.",
                "%(n)s values flagged by the quality checks.",
                flagged,
            )
            % {"n": number_format(flagged, force_grouping=True)}
        )
    elif flags:
        parts.append(_("No values flagged by the quality checks."))
    return " ".join(parts)


# ---- index series --------------------------------------------------------------------


@dataclass(frozen=True)
class IndexSource:
    """Where one station's index tables are: ``<folder>/<station>/indices/``, written
    with ``params`` (the output names of parameterised indices depend on them)."""

    folder: Path
    station: str
    params: object  # climpact.config.IndexParams

    @property
    def indices_dir(self) -> Path:
        return self.folder / self.station / "indices"

    def table_path(self, name: str) -> Path:
        return self.indices_dir / f"{self.station}_{name}.csv"

    def trend_path(self) -> Path:
        return self.folder / self.station / "trend" / f"{self.station}_trend.csv"


class _Tables(Mapping):
    """The run's index tables, read from disk when asked for, ``indices/<name>`` keys as
    in the core. ``only`` limits it to one table, so one series reads one file."""

    def __init__(self, source: IndexSource, only: str | None = None):
        self.source, self.only, self.cache = source, only, {}

    def _names(self) -> list[str]:
        if self.only is not None:
            return [self.only]
        prefix = f"{self.source.station}_"
        return sorted(p.stem[len(prefix) :] for p in self.source.indices_dir.glob(f"{prefix}*.csv"))

    def __getitem__(self, key: str):
        from climpact.io.climpact_csv import read_climpact_csv

        name = key.removeprefix("indices/")
        if not key.startswith("indices/") or name not in self._names():
            raise KeyError(key)
        if name not in self.cache:
            path = self.source.table_path(name)
            if not path.is_file():
                raise KeyError(key)
            self.cache[name] = read_climpact_csv(path).data
        return self.cache[name]

    def __iter__(self) -> Iterator[str]:
        return (f"indices/{n}" for n in self._names())

    def __len__(self) -> int:
        return len(self._names())


def table_name(series: str) -> str:
    """The index table a plotted series comes from: ``day_of_txx_ANN`` -> ``txx_ANN``."""
    return series.removeprefix("day_of_")


def index_plots(source: IndexSource, only: str | None = None) -> list:
    """The core's :class:`~climpact.plots.IndexPlot` list of a run, in R's order; with
    ``only`` (a series name), just that series, reading one table."""
    from climpact.plots import index_plots as core_index_plots

    tables = _Tables(source, table_name(only) if only else None)
    plots = [p for _, group in core_index_plots(tables, source.params) for p in group]
    return [p for p in plots if only is None or p.name == only]


def series_list(source: IndexSource) -> list[dict]:
    """Every plotted series of a run: ``name``, ``title``, ``step``, ``bars``."""
    return [
        {"name": p.name, "title": p.description, "step": p.step, "bars": p.bars}
        for p in index_plots(source)
    ]


PER_DECADE = {"year": 10, "month": 120}


def index_payload(source: IndexSource, name: str) -> dict | None:
    """The ``index`` payload of series ``name``, or None when the run has no such
    plotted series."""
    from climpact.plots import trend_text

    found = index_plots(source, only=name)
    if not found:
        return None
    plot = found[0]
    units = numbers.unit_label(plot.units)
    axis = units
    if plot.name.startswith("day_of_"):  # "Calendar day": the axis label, not a unit
        units, axis = "", _("Calendar day")
    payload = {
        "kind": "index",
        "version": SCHEMA_VERSION,
        "name": plot.name,
        "title": plot.description,
        "units": units,
        "axis": axis,
        "step": plot.step,
        "bars": plot.bars,
        "x": [int(x) if float(x).is_integer() else round(float(x), 6) for x in plot.x],
        "y": _finite(plot.values),
        "label": _("Day") if plot.name.startswith("day_of_") else plot.name.rsplit("_", 1)[0],
        "trend": None,
        "trend_text": trend_text(plot),
    }
    if not plot.name.startswith("day_of_"):
        table = _Tables(source, table_name(name))[f"indices/{table_name(name)}"]
        if "ymd" in table:
            payload["dates"] = [d if isinstance(d, str) else None for d in table["ymd"]]
    trend = plot.trend
    if trend is not None and trend.valid:
        payload["trend"] = {
            "slope": trend.slope,
            "lower": trend.lower,
            "upper": trend.upper,
            "intercept": trend.intercept,
            "p_value": trend.p_value,
            "label": _("Sen's slope trend"),
        }
    payload["summary"] = index_summary(payload)
    return payload


def _x_label(step: str, x: float) -> str:
    if step == "month":
        year = math.floor(x)
        month = round((x - year) * 12 + 0.5)
        return f"{year}-{month:02d}"
    if step == "day":
        return _("day %(n)s") % {"n": int(x)}
    return str(int(round(x)))


def index_summary(payload: dict) -> str:
    x, y, step, units = payload["x"], payload["y"], payload["step"], payload["units"]
    present = [(v, i) for i, v in enumerate(y) if v is not None]
    parts = [
        _("%(first)s to %(last)s.") % {"first": _x_label(step, x[0]), "last": _x_label(step, x[-1])}
    ]
    if present:
        high, low = max(present), min(present)
        digits = payload.get("signed_digits")

        def shown(value: float) -> str:
            text = number(value) if digits is None else numbers.signed(value, digits)
            return with_units(text, units)

        parts.append(
            _("Highest %(high)s in %(high_at)s, lowest %(low)s in %(low_at)s.")
            % {
                "high": shown(high[0]),
                "high_at": _x_label(step, x[high[1]]),
                "low": shown(low[0]),
                "low_at": _x_label(step, x[low[1]]),
            }
        )
    missing = len(y) - len(present)
    if missing:
        parts.append(
            ngettext(
                "%(n)s of %(total)s values missing.", "%(n)s of %(total)s values missing.", missing
            )
            % {"n": missing, "total": len(y)}
        )
    trend = payload["trend"]
    if trend is not None:
        per = PER_DECADE.get(step, 1)
        slope = trend["slope"] * per
        change = trend_units(units)
        places = numbers.slope_decimals(units)
        values = {
            "slope": with_units(numbers.fixed(abs(slope), places), change),
            "zero": with_units(numbers.fixed(0, places), change),
            "interval": numbers.interval(trend["lower"] * per, trend["upper"] * per, units),
        }
        if slope > 0:
            text = _("Trend: rising by %(slope)s per decade")
        elif slope < 0:
            text = _("Trend: falling by %(slope)s per decade")
        else:
            text = _("Trend: no change (%(zero)s per decade)")
        text = text % values
        text += " " + _("(95%% confidence interval %(interval)s).") % values
        if trend["lower"] > 0 or trend["upper"] < 0:
            text += " " + _("The interval excludes zero: significant at the 5% level.")
        else:
            text += " " + _("The interval includes zero: not significant at the 5% level.")
        parts.append(text)
    elif (
        payload.get("trend_note", True)
        and step != "day"
        and not payload["name"].startswith("day_of_")
    ):
        parts.append(
            _("No trend: it needs at least 10 values and 70% of the series to be present.")
        )
    return " ".join(parts)

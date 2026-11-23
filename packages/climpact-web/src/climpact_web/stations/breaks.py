"""Possible breaks on a station's Quality page (#365, the QualityBreaks board).

The core's homogeneity module ``detect`` (:mod:`climpact.homogeneity.detect`, #34) looks
for breaks (sudden shifts, such as a station move or a new instrument leaves) in a
station's yearly and monthly series and reports them; it never changes the data, so the
indices do not depend on it. The web app runs it in each station's ``qc`` job, with the
options of the workspace's break detection settings (``Workspace.break_detection``,
:func:`settings_of`) and its station history file (:func:`history_path`): the breaks come
with the checks, on the page that shows them, and changing the settings reruns the checks'
job only, never the calculation. The job writes ``homogeneity/breaks`` and
``homogeneity/tests`` beside ``qc/`` (in its zip too), and the yearly series it tested to
``breaks_series.json`` beside its ``output/`` for the chart (``jobs.runners.break_series``).

:func:`review` reads them back for the page: one :class:`SeriesBreaks` per series tested
(TX annual, TX monthly, TN annual, TN monthly, PRCP annual), each with its tests (the
result, or why it was not tested), its breaks, and the breaks within about a year of each
other grouped into one date (:class:`Group`), graded by how strong the evidence is:
``strong`` (found by two tests or more, or by PMF), ``normal`` (one test) or ``quiet``
(only "maybe", or PMT alone, which assumes no trend and has about twice the nominal false
alarms). A break is not a status: the page draws the grades by weight, never in a status
colour. The station's answer in one sentence is :attr:`BreaksReview.sentence`.

The core is not imported here: the web server reads the files the job wrote.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from climpact_web.charts import data as chart_data
from climpact_web.core import numbers

# The core's choices (climpact.homogeneity.detect), repeated so the web server need not
# import the core.
METHODS = ("pettitt", "snht", "pmf", "pmt")
METHOD_NAMES = {"pettitt": "Pettitt", "snht": "SNHT", "pmf": "PMF", "pmt": "PMT"}
VARIABLES = ("TX", "TN", "PRCP")
FREQUENCIES = ("annual", "monthly")
LEVELS = (0.75, 0.8, 0.9, 0.95, 0.99, 0.9999)
BREAKS_FOUND, NOT_TESTED = "breaks found", "not tested"

DEFAULTS = {
    "on": True,
    "methods": list(METHODS),
    "variables": list(VARIABLES),
    "series": list(FREQUENCIES),
    "level": 0.95,
    "min_years": 5,
}
HISTORY_FILE = "station_history.csv"  # its name in the workspace's folder and a job's input
GROUP_YEARS = 1.2  # breaks this close (in years) are one date of "Which tests agree"

# The page's address of a series: ?show=breaks-tx-annual.
ID_PREFIX = "breaks-"


# ---- the settings --------------------------------------------------------------------------


def settings_of(space) -> dict:
    """The workspace's break detection settings, with the defaults for what it has not
    set, and ``history``: the station history file's ``{"name", "sha256"}``, or None."""
    chosen = space.break_detection or {}
    out = {key: chosen.get(key, value) for key, value in DEFAULTS.items()}
    out["history"] = chosen.get("history") or None
    return out


def history_path(space) -> Path:
    """Where the workspace keeps its station history file (deleted with the workspace)."""
    from climpact_web.stations.models import stations_dir

    return stations_dir() / str(space.pk) / "break_detection" / HISTORY_FILE


def module_options(settings: dict) -> dict:
    """The options of the core's ``detect`` module, as a ``qc`` job passes them on."""
    return {
        "methods": ",".join(m for m in METHODS if m in settings["methods"]),
        "variables": ",".join(v for v in VARIABLES if v in settings["variables"]),
        "series": ",".join(f for f in FREQUENCIES if f in settings["series"]),
        "level": float(settings["level"]),
        "min_years": int(settings["min_years"]),
    }


def job_params(space) -> dict:
    """What a ``qc`` job of the workspace's stations adds to its parameters: the module's
    options (``homogeneity``) and the station history file (``station_history``, a file
    the job copies into its ``input/``), or nothing when break detection is off."""
    settings = settings_of(space)
    if not settings["on"]:
        return {}
    params = {"homogeneity": module_options(settings)}
    if settings["history"] and history_path(space).is_file():
        params["station_history"] = HISTORY_FILE
    return params


def inputs_of(space) -> dict:
    """The ``breaks`` input a ``qc`` job records (``workspace.current_inputs``): off, or the
    options and the history file's SHA-256. A change to it reruns the checks' job, and the
    breaks it shows are out of date until then; the checks themselves are not."""
    settings = settings_of(space)
    if not settings["on"]:
        return {"on": False}
    history = settings["history"] if history_path(space).is_file() else None
    return {
        "on": True,
        **module_options(settings),
        "history": (history or {}).get("sha256", ""),
    }


def settings_text(record: dict) -> str:
    """The settings a job's breaks were found with, short: "95%, segments of 5+ years"."""
    level = numbers.number(100 * float(record.get("level", 0.95)), 2)
    years = int(record.get("min_years", 5))
    return _("%(level)s%%, segments of %(years)s+ years") % {"level": level, "years": years}


# ---- reading the job's files ---------------------------------------------------------------


def _value(text: str) -> float | None:
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _read_table(path: Path) -> list[dict[str, str]]:
    """The rows of a homogeneity file (``climpact_csv``: a header block, the column
    names, then the rows) as dicts."""
    from climpact_web.stations.qc_review import read_qc_file

    qcfile = read_qc_file(path)
    return [dict(zip(qcfile.columns, values, strict=False)) for _section, values in qcfile.rows]


def _position(label: str) -> float:
    """Where a period starts on the years' axis: ``1988`` -> 1988.0, ``1997-02`` ->
    1997.083."""
    year, _sep, month = label.partition("-")
    return int(year) + ((int(month) - 1) / 12 if month else 0.0)


@dataclass
class Break:
    """One row of ``homogeneity/breaks``."""

    method: str
    last_before: str
    first_after: str
    significance: str  # yes, maybe or no
    statistic: float | None
    critical_value: float | None
    p_value: float | None
    shift: float | None
    units: str  # degC or %
    history: str

    @property
    def test(self) -> str:
        return METHOD_NAMES.get(self.method, self.method)

    @property
    def pos(self) -> float:
        return _position(self.first_after)

    @property
    def statistic_text(self) -> str:
        return _number(self.statistic)

    @property
    def critical_text(self) -> str:
        return _number(self.critical_value)

    @property
    def p_text(self) -> str:
        """The p-value (Pettitt and SNHT; RHtests gives none): two significant figures,
        "< 0.00005" below the SNHT's simulation's resolution."""
        p = self.p_value
        if p is None:
            return "–"
        if p < 0.00005:
            return _("< %(p)s") % {"p": numbers.number(0.00005, 5)}
        places = max(2, 1 - math.floor(math.log10(p))) if p > 0 else 2
        return numbers.number(float(f"{p:.2g}"), min(places, 5))

    @property
    def shift_text(self) -> str:
        """The shift with its sign and unit: ``+0.72 °C``, ``+58%``."""
        if self.shift is None:
            return "–"
        if self.units == "%":
            return numbers.with_unit(numbers.signed(self.shift, 0), "%")
        return numbers.with_unit(numbers.signed(self.shift, 2), "°C")

    @property
    def significant(self) -> bool:
        return self.significance == "yes"


def _number(value: float | None) -> str:
    if value is None:
        return "–"
    if abs(value) >= 1000:
        return numbers.grouped(round(value))
    return numbers.number(value)


@dataclass
class Test:
    """One row of ``homogeneity/tests``: a method on a series."""

    method: str
    values: int
    breaks: int
    possible: int
    status: str
    note: str

    @property
    def test(self) -> str:
        return METHOD_NAMES.get(self.method, self.method)

    @property
    def tested(self) -> bool:
        return self.status != NOT_TESTED

    @property
    def result(self) -> str:
        """The board's Result: "Not tested: <why>", "No breaks found", "2 breaks, 1 maybe"."""
        if not self.tested:
            return _("Not tested: %(why)s") % {"why": self.note}
        parts = []
        if self.breaks:
            parts.append(ngettext("%(n)s break", "%(n)s breaks", self.breaks) % {"n": self.breaks})
        if self.possible:
            parts.append(
                ngettext("%(n)s maybe", "%(n)s maybes", self.possible) % {"n": self.possible}
            )
        return ", ".join(parts) if parts else _("No breaks found")

    @property
    def found(self) -> bool:
        return bool(self.breaks or self.possible)


@dataclass
class Group:
    """The breaks of one series within about a year of each other (:data:`GROUP_YEARS`):
    one date of "Which tests agree", one mark on the chart."""

    pos: float
    breaks: list[Break] = field(default_factory=list)
    freq: str = "annual"

    @property
    def tests(self) -> dict[str, str]:
        """Each method that found a break here: ``yes`` when one of its breaks is, else
        ``maybe``."""
        out: dict[str, str] = {}
        for b in self.breaks:
            out[b.method] = "yes" if b.significant or out.get(b.method) == "yes" else "maybe"
        return out

    @property
    def count(self) -> int:
        return len(self.tests)

    @property
    def grade(self) -> str:
        """``strong`` (two tests or more with a yes among them, or PMF's yes), ``quiet``
        (only maybes, or PMT alone) or ``normal`` (one other test)."""
        tests = self.tests
        yes = "yes" in tests.values()
        if (self.count >= 2 and yes) or tests.get("pmf") == "yes":
            return "strong"
        if not yes or set(tests) == {"pmt"}:
            return "quiet"
        return "normal"

    @property
    def maybe_only(self) -> bool:
        return "yes" not in self.tests.values()

    @property
    def first(self) -> Break:
        return self.breaks[0]

    @property
    def when(self) -> str:
        """Its date: the earliest break's last period before it and first after it for a
        yearly series ("1987/88"), the last month before it for a monthly one
        ("1997-01")."""
        b = self.first
        if self.freq == "monthly":
            return b.last_before
        return f"{b.last_before}/{b.first_after[-2:]}"

    @property
    def year(self) -> str:
        return self.first.last_before[:4]

    @property
    def by(self) -> str:
        if self.count == 1:
            return _("one test")
        return _("found by %(n)s tests") % {"n": self.count}

    @property
    def history(self) -> str:
        """The station history events near its breaks (the core's ``station_history``)."""
        seen: list[str] = []
        for b in self.breaks:
            for part in (p.strip() for p in b.history.split(";") if p.strip()):
                if part not in seen:
                    seen.append(part)
        return "; ".join(seen)


def group_breaks(breaks: list[Break], freq: str) -> list[Group]:
    """The breaks marked yes or maybe, grouped by date (:class:`Group`), in time order."""
    out: list[Group] = []
    for b in sorted((b for b in breaks if b.significance != "no"), key=lambda b: b.pos):
        last = out[-1] if out else None
        if last is not None and b.pos - last.pos <= GROUP_YEARS:
            last.breaks.append(b)
            last.pos = max(last.pos, b.pos)
        else:
            out.append(Group(b.pos, [b], freq))
    return out


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return _("%(items)s and %(last)s") % {"items": ", ".join(items[:-1]), "last": items[-1]}


# ---- the series and their chart ---------------------------------------------------------------

# The series chart's box (#365): the plot from (LEFT, TOP) to (RIGHT, BOTTOM), the x axis
# at AXIS, the station history's triangles under it.
CHART_W, CHART_H = 1000, 250
LEFT, RIGHT, TOP, BOTTOM, AXIS = 56, 990, 40, 190, 200
UNITS = {"TX": "°C", "TN": "°C", "PRCP": "mm"}
ROLES = {"TX": "tmax", "TN": "tmin", "PRCP": "prcp"}  # the variables' chart roles


def _ticks(low: float, high: float) -> tuple[float, float, float]:
    """A round step and the axis's ends around ``low`` and ``high``: at most five steps."""
    for step in (0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        lo, hi = math.floor(low / step) * step, math.ceil(high / step) * step
        if hi == lo:
            hi = lo + step
        if (hi - lo) / step <= 5:
            return lo, hi, step
    step = 10 ** math.ceil(math.log10(max(high - low, 1)))
    return math.floor(low / step) * step, math.ceil(high / step) * step, step


@dataclass
class SeriesBreaks:
    """One series tested (TX annual, ...): its tests, its breaks and their dates."""

    variable: str
    freq: str
    tests: list[Test]
    breaks: list[Break]
    groups: list[Group]

    @property
    def id(self) -> str:
        return f"{ID_PREFIX}{self.variable.lower()}-{self.freq}"

    @property
    def anchor(self) -> str:
        return f"detail-{self.id}"

    @property
    def title(self) -> str:
        if self.freq == "monthly":
            return _("%(variable)s monthly") % {"variable": self.variable}
        return _("%(variable)s annual") % {"variable": self.variable}

    @property
    def values(self) -> int:
        return max((t.values for t in self.tests), default=0)

    @property
    def values_text(self) -> str:
        n = self.values
        if self.freq == "monthly":
            return ngettext("%(n)s month", "%(n)s months", n) % {"n": numbers.grouped(n)}
        return ngettext("%(n)s year", "%(n)s years", n) % {"n": numbers.grouped(n)}

    @property
    def untested(self) -> list[Test]:
        return [t for t in self.tests if not t.tested]

    @property
    def agree(self) -> list[dict]:
        """ "Which tests agree": each date, and for each test ``yes``, ``maybe``, ``none``
        (nothing near) or ``untested``."""
        out = []
        for group in self.groups:
            found = group.tests
            cells = [found.get(t.method, "none") if t.tested else "untested" for t in self.tests]
            out.append({"group": group, "cells": cells})
        return out

    @property
    def rows(self) -> list[Break]:
        """The breaks table: every test's own breaks, by date, then in the tests' order."""
        order = {m: i for i, m in enumerate(METHODS)}
        return sorted(self.breaks, key=lambda b: (b.pos, order.get(b.method, 9)))

    @property
    def tested(self) -> list[Test]:
        return [t for t in self.tests if t.tested]

    @property
    def found_by(self) -> int:
        """How many of its tests found a break (yes)."""
        return sum(1 for t in self.tests if t.status == BREAKS_FOUND)

    @property
    def maybe_only(self) -> bool:
        return bool(self.groups) and all(g.maybe_only for g in self.groups)

    @property
    def rail_text(self) -> str:
        """Under its name in the rail: the years of its dates, or what was found."""
        n = len(self.untested)
        if self.groups:
            text = " ".join(g.year for g in self.groups)
            if n:
                text += " · " + ngettext("%(n)s not tested", "%(n)s not tested", n) % {"n": n}
            return text
        if n:
            return _("%(n)s of %(total)s not tested") % {"n": n, "total": len(self.tests)}
        return _("none found")

    def timeline(self, first: int, last: int) -> dict:
        """The rail's small timeline (60 x 14): a mark at each date, its height and weight
        by grade (strong from the top, normal from 4, quiet from 8)."""
        span = max(last + 1 - first, 1)
        tops = {"strong": 0, "normal": 4, "quiet": 8}
        paths = dict.fromkeys(tops, "")
        for g in self.groups:
            x = round(1 + (g.pos - first) / span * 58, 1)
            paths[g.grade] += f"M{x} {tops[g.grade]}V13"
        return paths

    # ---- the detail's words

    @property
    def headline(self) -> str:
        """The detail's title."""
        if not self.tested:
            return _("%(title)s: not tested") % {"title": self.title}
        if not self.groups:
            return _("%(title)s: no breaks found") % {"title": self.title}
        years = _join([g.year for g in self.groups])
        if self.maybe_only:
            return ngettext(
                "%(title)s: one maybe, around %(years)s",
                "%(title)s: %(n)s maybes, around %(years)s",
                len(self.groups),
            ) % {"title": self.title, "n": len(self.groups), "years": years}
        return _("%(title)s: possible breaks around %(years)s") % {
            "title": self.title,
            "years": years,
        }

    def lede(self, history: bool) -> str:
        """One or two sentences made from the results: what was found, how strongly,
        and what to check it against."""
        if not self.tested:
            return _("None of the tests could run on this series.")
        if not self.groups:
            return _(
                "None of the tests finds a shift in this series. That is not proof that it "
                "is homogeneous: a shift smaller than the year-to-year variation can go "
                "unseen."
            )
        parts = []
        sure = [g for g in self.groups if not g.maybe_only]
        shifts = [b.shift for g in sure for b in g.breaks if b.significant and b.shift is not None]
        if shifts:
            size = sum(abs(s) for s in shifts) / len(shifts)
            unit = "%" if self.variable == "PRCP" else "°C"
            places = 0 if unit == "%" else 1
            about = numbers.with_unit(numbers.fixed(size, places), unit)
            up, down = any(s > 0 for s in shifts), any(s < 0 for s in shifts)
            if up and down:
                parts.append(_("Shifts up and down of about %(size)s.") % {"size": about})
            elif up:
                parts.append(_("Shifts up of about %(size)s.") % {"size": about})
            else:
                parts.append(_("Shifts down of about %(size)s.") % {"size": about})
        strong = sum(1 for g in self.groups if g.grade == "strong")
        if strong:
            parts.append(
                ngettext(
                    "One date is found by two tests or more, or by PMF.",
                    "%(n)s dates are found by two tests or more, or by PMF.",
                    strong,
                )
                % {"n": strong}
            )
        pmt_only = [g for g in self.groups if set(g.tests) == {"pmt"}]
        if pmt_only and any(t.method == "pmf" and t.tested for t in self.tests):
            parts.append(
                _(
                    "PMT alone finds %(years)s: it assumes no trend, so a trend can look "
                    "like a break."
                )
                % {"years": _join([g.year for g in pmt_only])}
            )
        if any(g.maybe_only for g in self.groups):
            parts.append(_("A maybe counts only if the station history supports it."))
        if history:
            near = sum(1 for g in self.groups if g.history)
            parts.append(
                ngettext(
                    "%(near)s of the %(n)s date is near an event in the station history.",
                    "%(near)s of the %(n)s dates are near an event in the station history.",
                    len(self.groups),
                )
                % {"near": near, "n": len(self.groups)}
            )
        if self.freq == "monthly":
            parts.append(_("The breaks of the monthly series are marked at their month."))
        parts.append(_("The data are not adjusted: the indices use them as they are."))
        return " ".join(parts)

    def table_note(self, min_years: int) -> str:
        """The note under its breaks table: how the series was tested."""
        if self.variable == "PRCP":
            return _(
                "PRCP is tested as the log of the yearly total; the shift is the change in "
                "the total, in %."
            )
        if self.freq == "monthly":
            return _(
                "Pettitt and SNHT test monthly series as anomalies from each calendar "
                "month's mean; the shift is in the monthly means."
            )
        return _(
            "Pettitt and SNHT split the series at each break they find, down to segments "
            "of %(years)s years; PMF and PMT find several breaks at once."
        ) % {"years": min_years}


@dataclass
class Chart:
    """The series chart (#365): each year's value, the mean of each segment between the
    dates as a step, a mark at each date by grade, the station history as triangles under
    the axis; its read-out, summary and table view."""

    caption: str
    note: str
    unit: str
    role: str
    y_ticks: list[dict]
    x_ticks: list[dict]
    line: str
    dots: str
    steps: str
    marks: dict[str, str]
    labels: list[dict]
    history: list[dict]
    readout: str
    aria: str
    summary: str
    rows: list[dict]
    legend_value: str

    @property
    def value_header(self) -> str:
        """The table view's value column: "Yearly mean (°C)"."""
        return _("%(what)s (%(unit)s)") % {
            "what": self.legend_value.capitalize(),
            "unit": self.unit,
        }

    @property
    def height(self) -> int:
        """The box's height: room under the axis for the station history, when it has any."""
        return CHART_H if self.history else AXIS + 24


def chart(item: SeriesBreaks, yearly: dict, events: list[dict], has_history: bool) -> Chart | None:
    """The chart of ``item`` from the job's yearly series (``breaks_series.json``)."""
    first = yearly.get("first")
    values = (yearly.get("values") or {}).get(item.variable)
    if first is None or not values or all(v is None for v in values):
        return None
    years = list(range(first, first + len(values)))
    last = years[-1]
    known = [v for v in values if v is not None]
    low, high, step = _ticks(min(known), max(known))
    span = last + 1 - first

    def x(year: float) -> float:
        return round(LEFT + (year - first) / span * (RIGHT - LEFT), 1)

    def y(v: float) -> float:
        return round(BOTTOM - (v - low) / (high - low) * (BOTTOM - TOP), 1)

    unit = UNITS[item.variable]
    ticks = []
    v = low
    while v <= high + step / 1000:
        text = numbers.grouped(round(v)) if step >= 1 and abs(v) >= 1000 else numbers.number(v)
        ticks.append({"y": y(v), "text": text})
        v += step
    every = 10 if span >= 30 else 5
    x_ticks = [{"x": x(yr + 0.5), "text": yr} for yr in years if yr % every == 0]

    line, dots, run = "", "", []
    for yr, v in zip(years, values, strict=True):
        if v is None:
            if run:
                line += "M" + "L".join(run)
            run = []
            continue
        px, py = x(yr + 0.5), y(v)
        run.append(f"{px} {py}")
        dots += f"M{px - 2.6:.1f} {py}a2.6 2.6 0 1 0 5.2 0a2.6 2.6 0 1 0 -5.2 0z"
    if run:
        line += "M" + "L".join(run)

    bounds = [float(first), *(g.pos for g in item.groups), float(last + 1)]
    steps, segment_of, rows = "", {}, []
    for a, b in zip(bounds[:-1], bounds[1:], strict=True):
        inside = [(yr, v) for yr, v in zip(years, values, strict=True) if a <= yr + 0.5 < b]
        got = [v for _yr, v in inside if v is not None]
        if inside:
            label = f"{inside[0][0]}–{inside[-1][0]}" if len(inside) > 1 else str(inside[0][0])
            for yr, _v in inside:
                segment_of[yr] = label
        if got:
            mean = sum(got) / len(got)
            steps += f"M{x(a)} {y(mean)}H{x(b)}"
    for yr, v in zip(years, values, strict=True):
        rows.append(
            {
                "year": yr,
                "value": "–" if v is None else numbers.number(v, 1 if unit == "mm" else 2),
                "segment": segment_of.get(yr, ""),
            }
        )

    marks = {"strong": "", "normal": "", "quiet": ""}
    labels = []
    for i, g in enumerate(item.groups):
        px = x(g.pos)
        marks[g.grade] += f"M{px} {TOP - 4}V{AXIS}"
        labels.append({"x": px, "y": 22 if i % 2 else 32, "text": g.when, "grade": g.grade})
    triangles = []
    for e in events:
        pos = _position(e["date"][:7] if len(e["date"]) >= 7 else e["date"][:4])
        if first <= pos < last + 1:
            triangles.append({"x": x(pos), "date": e["date"], "text": e["text"]})
    readout = chart_data.attr_json(
        {
            "x0": x(first + 0.5),
            "dx": (RIGHT - LEFT) / span,
            "low": low,
            "high": high,
            "top": TOP,
            "bottom": BOTTOM,
            "v": [None if v is None else chart_data.shown(v) for v in values],
            "when": {"step": "year", "first": first},
            "label": item.variable,
            "unit": unit,
            "missing": _("no value"),
            "start": None,
        }
    )
    strong = sum(1 for g in item.groups if g.grade == "strong")
    if item.groups:
        dates = ", ".join(
            f"{g.when} ({g.by if g.count > 1 else _('one test')})" for g in item.groups
        )
        summary = ngettext(
            "%(n)s date with possible breaks: %(dates)s.",
            "%(n)s dates with possible breaks: %(dates)s.",
            len(item.groups),
        ) % {"n": len(item.groups), "dates": dates}
        summary += " " + (
            ngettext(
                "%(n)s found by two tests or more.", "%(n)s found by two tests or more.", strong
            )
            % {"n": strong}
            if strong
            else _("None found by two tests.")
        )
    else:
        summary = _("No possible breaks. The segment mean is the mean of the whole series.")
    if item.variable == "PRCP":
        caption_note, legend = _("yearly total, mm"), _("yearly total")
    elif item.freq == "monthly":
        caption_note = _(
            "yearly means of %(variable)s, °C, with the monthly breaks at their month"
        ) % {"variable": item.variable}
        legend = _("yearly mean")
    else:
        caption_note, legend = _("yearly mean, °C"), _("yearly mean")
    return Chart(
        caption=item.title,
        note=caption_note,
        unit=unit,
        role=ROLES[item.variable],
        y_ticks=ticks,
        x_ticks=x_ticks,
        line=line,
        dots=dots,
        steps=steps,
        marks=marks,
        labels=labels,
        history=triangles,
        readout=readout,
        aria=_(
            "%(title)s from %(first)s to %(last)s, with %(n)s possible break dates marked. "
            "The table lists the values."
        )
        % {"title": item.title, "first": first, "last": last, "n": len(item.groups)},
        summary=summary,
        rows=rows,
        legend_value=legend,
    )


# ---- the station's review -------------------------------------------------------------------

# The page's states of the breaks (#365, the board's ``state``): the results, off for the
# workspace, or none to show yet (pending: being looked for, or the checks shown ran
# without it).
RESULTS, OFF, PENDING, MISSING = "results", "off", "pending", "missing"


@dataclass
class BreaksReview:
    """What a station's Quality shows of its breaks: :attr:`state`, the series, the
    station history, and whether they are out of date (the settings changed since)."""

    state: str
    series: list[SeriesBreaks] = field(default_factory=list)
    first: int = 0
    last: int = 0
    yearly: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    has_history: bool = False
    history_error: str = ""
    files: dict[str, str] = field(default_factory=dict)  # breaks, tests -> job file
    found_with: str = ""  # the settings they were found with, for the out-of-date line
    min_years: int = 5
    stale: bool = False
    looking: bool = False  # a newer job is looking for them

    @property
    def items(self) -> list[SeriesBreaks]:
        return self.series

    @property
    def with_breaks(self) -> list[SeriesBreaks]:
        return [s for s in self.series if s.groups]

    @property
    def tests(self) -> list[Test]:
        return [t for s in self.series for t in s.tests]

    @property
    def untested(self) -> int:
        return sum(1 for t in self.tests if not t.tested)

    @property
    def found_by(self) -> int:
        return sum(1 for t in self.tests if t.status == BREAKS_FOUND)

    @property
    def variables(self) -> list[str]:
        """The variables with possible breaks, in the core's order."""
        found = {s.variable for s in self.with_breaks}
        return [v for v in VARIABLES if v in found]

    @property
    def first_with_breaks(self) -> SeriesBreaks | None:
        return next(iter(self.with_breaks), None)

    def get(self, key: str) -> SeriesBreaks | None:
        return next((s for s in self.series if s.id == key), None)

    @property
    def counts_text(self) -> str:
        """The verdict's counts line's link: "possible breaks in TX TN PRCP"."""
        if self.state != RESULTS:
            return ""
        tested = len(self.tests) - self.untested
        if not self.with_breaks:
            return ngettext(
                "no possible breaks (%(n)s test)", "no possible breaks (%(n)s tests)", tested
            ) % {"n": tested}
        text = _("possible breaks in %(variables)s") % {"variables": " ".join(self.variables)}
        if self.untested:
            text += " · " + ngettext("%(n)s test not run", "%(n)s tests not run", self.untested) % {
                "n": self.untested
            }
        return text

    @property
    def sentence(self) -> str:
        """The station's answer in one sentence or two, the rail section's note."""
        if self.state == OFF:
            return _("Turned off for this workspace.")
        if self.state == PENDING:
            if self.looking:
                return _("Looking for breaks. They come with the checks.")
            return _("Not looked for: these checks ran before break detection was on.")
        if self.state == MISSING:
            return _("The break tests' files are missing.")
        tested = len(self.tests) - self.untested
        parts = []
        sure = [g for s in self.series for g in s.groups if not g.maybe_only]
        maybe_series = [s for s in self.with_breaks if s.maybe_only]
        if sure:
            # The strongest dates name the answer: those found by two tests or more, or
            # by PMF; the others are in each series' detail.
            strong = [(s, g) for s in self.series for g in s.groups if g.grade == "strong"]
            chosen = strong or [(s, g) for s in self.series for g in s.groups if not g.maybe_only]
            years = _clusters([g for _s, g in chosen])
            variables = [v for v in VARIABLES if any(s.variable == v for s, _g in chosen)]
            near = any(g.history for _s, g in chosen)
            text = _("Possible breaks around %(years)s in %(variables)s") % {
                "years": _join(years),
                "variables": _join(variables),
            }
            if near:
                text = _("%(text)s, near the station history") % {"text": text}
            if maybe_series:
                n = sum(len(s.groups) for s in maybe_series)
                text += "; " + ngettext(
                    "one maybe in %(series)s", "%(n)s maybes in %(series)s", n
                ) % {"n": n, "series": _join([s.title for s in maybe_series])}
            parts.append(text + ".")
            parts.append(
                _("Found by %(found)s of %(tested)s tests.")
                % {"found": self.found_by, "tested": tested}
            )
        elif maybe_series:
            n = sum(len(s.groups) for s in maybe_series)
            parts.append(
                ngettext(
                    "One possible break, a maybe, in %(series)s.",
                    "%(n)s possible breaks, all maybes, in %(series)s.",
                    n,
                )
                % {"n": n, "series": _join([s.title for s in maybe_series])}
            )
        else:
            parts.append(
                ngettext(
                    "No breaks found by %(n)s test in the %(s)s series.",
                    "No breaks found by %(n)s tests in the %(s)s series.",
                    tested,
                )
                % {"n": tested, "s": len(self.series)}
            )
        if self.untested:
            parts.append(
                ngettext("%(n)s test could not run.", "%(n)s tests could not run.", self.untested)
                % {"n": self.untested}
            )
        parts.append(_("The data are not adjusted."))
        return " ".join(parts)

    def chart(self, item: SeriesBreaks) -> Chart | None:
        return chart(item, self.yearly, self.events, self.has_history)


def _clusters(groups: list[Group]) -> list[str]:
    """The years of ``groups`` across series, those within about a year as one."""
    years: list[str] = []
    last = None
    for g in sorted(groups, key=lambda g: g.pos):
        if last is None or g.pos - last > GROUP_YEARS:
            years.append(g.year)
        last = g.pos if last is None or g.pos - last > GROUP_YEARS else max(last, g.pos)
    return years


def has_results(job) -> bool:
    """Whether a finished ``qc`` job looked for breaks."""
    result = (job.result or {}) if job is not None else {}
    return "homogeneity/tests" in (result.get("reports") or {})


def review(space, shown, current=None, changes: bool = False) -> BreaksReview:
    """The breaks Quality shows: those the checks shown (``shown``, a finished ``qc``
    job) found, out of date when ``changes`` (their settings differ from the
    workspace's now); off when the workspace has break detection off; pending when the
    checks shown did not look for them (``current`` is the latest ``qc`` job, looking for
    them when it is not finished)."""
    if not settings_of(space)["on"]:
        return BreaksReview(OFF)
    looking = current is not None and current != shown and not current.is_finished
    if shown is None or not has_results(shown):
        return BreaksReview(PENDING, looking=looking)
    result = shown.result or {}
    output = Path(shown.output_dir)
    reports = result.get("reports") or {}
    try:
        tests = _read_table(output / reports["homogeneity/tests"])
        breaks = _read_table(output / reports["homogeneity/breaks"])
    except (KeyError, OSError):
        return BreaksReview(MISSING)
    try:
        yearly = json.loads((output.parent / result.get("breaks_series", "")).read_text())
    except (OSError, ValueError):
        yearly = {}
    by_series: dict[tuple[str, str], SeriesBreaks] = {}
    for row in tests:
        key = (row.get("variable", ""), row.get("series", ""))
        item = by_series.setdefault(key, SeriesBreaks(key[0], key[1], [], [], []))
        item.tests.append(
            Test(
                row.get("method", ""),
                int(_value(row.get("values")) or 0),
                int(_value(row.get("breaks")) or 0),
                int(_value(row.get("possible")) or 0),
                row.get("status", ""),
                row.get("note", ""),
            )
        )
    for row in breaks:
        key = (row.get("variable", ""), row.get("series", ""))
        if key not in by_series:
            continue
        by_series[key].breaks.append(
            Break(
                row.get("method", ""),
                row.get("last_before", ""),
                row.get("first_after", ""),
                row.get("significance", ""),
                _value(row.get("statistic")),
                _value(row.get("critical_value")),
                _value(row.get("p_value")),
                _value(row.get("shift")),
                row.get("units", ""),
                row.get("station_history", ""),
            )
        )
    for item in by_series.values():
        item.groups = group_breaks(item.breaks, item.freq)
    first = yearly.get("first") or 0
    count = max((len(v) for v in (yearly.get("values") or {}).values()), default=0)
    params = shown.params or {}
    return BreaksReview(
        RESULTS,
        series=list(by_series.values()),
        first=first,
        last=first + count - 1 if count else first,
        yearly=yearly,
        events=yearly.get("history") or [],
        has_history=bool(params.get("station_history")) and not result.get("history_error"),
        history_error=result.get("history_error") or "",
        files={
            "breaks": reports["homogeneity/breaks"],
            "tests": reports["homogeneity/tests"],
        },
        found_with=settings_text(params.get("homogeneity") or {}),
        min_years=int((params.get("homogeneity") or {}).get("min_years", 5)),
        stale=changes,
        looking=looking,
    )


def job_files(job) -> list[tuple[Path, str]]:
    """The homogeneity files a finished ``qc`` job wrote (#365), each with its path in a
    station's folder (``homogeneity/<station>_breaks.csv``): for the station's zip and the
    workspace's Everything. None when the job did not look for breaks."""
    if job is None or not has_results(job):
        return []
    out = []
    for key in ("homogeneity/breaks", "homogeneity/tests"):
        rel = (job.result.get("reports") or {}).get(key)
        path = Path(job.output_dir) / rel if rel else None
        if path is not None and path.is_file():
            out.append((path, f"homogeneity/{path.name}"))
    return out


def provenance(space) -> dict:
    """The break detection settings, for ``climpact_run.json``."""
    settings = settings_of(space)
    if not settings["on"]:
        return {"on": False}
    return {
        "on": True,
        **module_options(settings),
        "station_history": (settings["history"] or {}).get("name", ""),
    }

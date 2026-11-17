"""The results dashboard of a station run (#78): one card per index table the run wrote.

Everything comes from the files of a finished ``station`` job (or of one station of a
``batch`` job, for an analysis opened from a batch's results), so the dashboard shows what
the downloads hold:

- the series, their descriptions, units and trends from the core's
  :func:`climpact.plots.index_plots` (the function the PNGs and the charts
  use: Sen's slope and its 95% bounds as in ``trend/trend``, zyp's intercept), read from
  the index tables in ``indices/``;
- the daily EHF and ECF tables, which R does not plot, as cards of their own;
- the tables the core did not write because every value was missing (the job's
  ``skipped``), with the likely reason.

Cards are grouped as the help's index catalogue (:mod:`climpact_web.help.indices`), and
each card belongs to a theme (:mod:`climpact_web.stations.themes`: heat, cold, rain,
drought, averages, growing season, the user's own index) for the filters and the hues.
Each card has a sparkline drawn here as SVG path data, so the table needs no chart code;
the index's own page draws its chart on the server too (:mod:`.index_page`, #237).

Building the cards reads every table (about 0.2 s for 114 tables) and computes the trends
(about 0.7 s), so the result is cached in memory, keyed by the files' modification times.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from django.utils.translation import get_language, gettext_lazy
from django.utils.translation import gettext as _

from climpact_web.charts import data as chart_data
from climpact_web.core import numbers
from climpact_web.help import indices as catalogue
from climpact_web.stations import themes

# Sparklines: drawn in a 240 x 60 box (stretched to the card's width with
# vector-effect: non-scaling-stroke); longer series are averaged into 240 columns.
SPARK_WIDTH, SPARK_HEIGHT, SPARK_PAD = 240, 60, 4
PER_DECADE = {"year": 10, "month": 120}


def groups() -> list[tuple[str, str]]:
    return [(key, str(label)) for key, label, _shorts in catalogue.GROUPS] + [
        ("custom", _("Your own index"))
    ]


# ---- where a run's files are ---------------------------------------------------------


@dataclass(frozen=True)
class RunSource:
    """One station's outputs in a finished job: ``<folder>/<station>/...``."""

    job: object  # climpact_web.jobs.models.Job
    folder: Path
    station: str
    params: object  # climpact.config.IndexParams
    skipped: tuple[str, ...] = ()  # output keys not written (missing in every period)
    from_batch: bool = False

    @property
    def index_source(self) -> chart_data.IndexSource:
        return chart_data.IndexSource(self.folder, self.station, self.params)

    @property
    def station_dir(self) -> Path:
        return self.folder / self.station

    def relative(self, path: Path) -> str:
        """``path`` relative to the job's ``output/``, for ``jobs:file``."""
        return path.relative_to(self.job.output_dir).as_posix()

    def table_file(self, name: str) -> str:
        return self.relative(self.index_source.table_path(name))

    def plot_file(self, name: str) -> str | None:
        path = self.station_dir / "plots" / f"{self.station}_{name}.png"
        return self.relative(path) if path.is_file() else None

    def file_if_exists(self, *parts: str) -> str | None:
        path = self.station_dir.joinpath(*parts)
        return self.relative(path) if path.is_file() else None


def run_source(job, station: str | None = None) -> RunSource | None:
    """The outputs of a finished ``station`` job, or of ``station`` in a ``batch`` job."""
    from climpact_web.charts.views import job_stations

    stations = job_stations(job)
    if station is None:
        station = next(iter(stations), None) if len(stations) == 1 else None
    if station not in stations:
        return None
    folder, params = stations[station]
    if job.kind == "batch":
        entry = next((s for s in job.result.get("stations", []) if s["name"] == station), {})
        skipped = entry.get("skipped_outputs", [])
    else:
        skipped = job.result.get("skipped", [])
    return RunSource(job, folder, station, params, tuple(skipped), job.kind == "batch")


# ---- names -----------------------------------------------------------------------------

_SUFFIX = re.compile(r"_(ANN|MON|DAY)$")
_PARAM_NAMES = (
    (re.compile(r"^rx(\d+)day$"), "Rx{}day"),
    (re.compile(r"^r(\d+(?:\.\d+)?)mm$"), "R{}mm"),
    (re.compile(r"^wsdi(\d+)$"), "WSDI{}"),
    (re.compile(r"^csdi(\d+)$"), "CSDI{}"),
    (re.compile(r"^tx(\d+)tn\d+$"), "TX{0}TN{0}"),
    (re.compile(r"^txb(\d+)tnb\d+$"), "TXb{0}TNb{0}"),
    (re.compile(r"^hddheat(.+)$"), "HDDheat{}"),
    (re.compile(r"^cddcold(.+)$"), "CDDcold{}"),
    (re.compile(r"^gddgrow(.+)$"), "GDDgrow{}"),
)
_SCALE = re.compile(r"^(\d+)month_(spi|spei)$")
_CUSTOM = re.compile(r"^(TX|TN|TM|PR|DTR)(gt|ge|lt|le)-?\d+(\.\d+)?$")


def card_key(series: str) -> str:
    """The card a series belongs to: ``day_of_txx_MON`` -> ``txx``,
    ``3month_spi_MON`` -> ``3month_spi``, ``TX90-HWN_ANN`` -> ``TX90-HWN``."""
    return _SUFFIX.sub("", series.removeprefix("day_of_"))


def display_name(key: str, info) -> str:
    """The code, in the usual spelling: ``TXx``, ``Rx3day``, ``R30mm``, ``SPI3``,
    ``TX90-HWN``, ``EHFdaily``."""
    if info is not None and key.lower() == info.short.lower():
        return info.name
    for pattern, template in _PARAM_NAMES:
        if m := pattern.match(key):
            return template.format(m.group(1))
    if m := _SCALE.match(key):
        return f"{m.group(2).upper()}{m.group(1)}"
    return key


# Heatwave tables share one catalogue entry (one long name), so each aspect gets a short
# name of its own, in the words of the indices guide; the code says which heatwaves
# (TX90-HWN, EHF-HWN) and the definition how they are found.
_HEATWAVE = re.compile(r"^(TX90|TN90|EHF|ECF)-([A-Z]+)$")
_ASPECTS = {
    "HWN": gettext_lazy("Number of heatwaves"),
    "HWF": gettext_lazy("Heatwave days"),
    "HWD": gettext_lazy("Longest heatwave"),
    "HWM": gettext_lazy("Mean heatwave temperature"),
    "HWA": gettext_lazy("Hottest heatwave's peak"),
    "HWMD": gettext_lazy("Mean heatwave duration"),
    "HWPS": gettext_lazy("Peak heatwave severity"),
    "HWLS": gettext_lazy("Total heatwave severity"),
    "HWPI": gettext_lazy("Peak heatwave intensity"),
    "HWLI": gettext_lazy("Total heatwave intensity"),
    "CWN": gettext_lazy("Number of cold waves"),
    "CWF": gettext_lazy("Cold-wave days"),
    "CWD": gettext_lazy("Longest cold wave"),
    "CWMD": gettext_lazy("Mean cold-wave duration"),
    "CWPS": gettext_lazy("Peak cold-wave severity"),
    "CWLS": gettext_lazy("Total cold-wave severity"),
    "CWPI": gettext_lazy("Peak cold-wave intensity"),
    "CWLI": gettext_lazy("Total cold-wave intensity"),
}

# The parameter in an output name, for the short names that take one (``%(n)s``).
_PARAMETER = re.compile(r"^(?:rx|r|wsdi|csdi|tx|txb)(\d+(?:\.\d+)?)")

# The user's own index: "TNgt0" is "Days TN > 0 °C".
_CUSTOM_PARTS = re.compile(r"^(TX|TN|TM|PR|DTR)(gt|ge|lt|le)(-?\d+(?:\.\d+)?)$")
_OPERATORS = {"gt": ">", "ge": "≥", "lt": "<", "le": "≤"}


def short_name(key: str, info) -> str:
    """The short name that follows the code (#218): the catalogue's (``Hottest day``),
    with the parameter of the output name (``rx3day``: ``Wettest 3 days``); for the
    heatwave tables, the aspect (``Number of heatwaves``); for the user's own index, its
    threshold (``Days TN > 0 °C``)."""
    if m := _HEATWAVE.match(key):
        aspect = _ASPECTS.get(m.group(2))
        if aspect:
            return str(aspect)
    if key == "EHFdaily":
        return _("Daily excess heat factor")
    if key == "ECFdaily":
        return _("Daily excess cold factor")
    if info is None:
        if m := _CUSTOM_PARTS.match(key):
            name = _("Days %(variable)s %(operator)s %(value)s %(units)s") % {
                "variable": m.group(1),
                "operator": _OPERATORS[m.group(2)],
                "value": m.group(3),
                "units": "mm" if m.group(1) == "PR" else "°C",
            }
            return numbers.in_text(name)
        return _("Your own threshold index")
    n = None
    if m := _SCALE.match(key):
        n = m.group(1)
    elif info.short in ("rxdday", "rnnmm", "wsdid", "csdid", "txdtnd", "txbdtnbd"):
        if m := _PARAMETER.match(key):
            n = m.group(1)
    return info.short_name(n)


def signature(key: str) -> str:
    """What stays the same about an index when the parameters change, to keep the user on
    the same index after recalculating: ``rx3day`` and ``rx7day`` are both Rxdday,
    ``24month_spi`` and ``36month_spi`` the extra SPI scale, every custom index is the
    custom index."""
    info = catalogue.index_for_output(key)
    if info is None:
        return "custom" if _CUSTOM.match(key) else key
    if m := _SCALE.match(key):
        scale = m.group(1)
        return f"{info.short}:{scale if scale in ('3', '6', '12') else 'extra'}"
    if info.short in ("hw", "hwEHF"):
        return key
    return info.short


def series_label(name: str) -> str:
    if name.startswith("day_of_"):
        return (
            _("Day of occurrence, monthly")
            if name.endswith("_MON")
            else _("Day of occurrence, yearly")
        )
    if name.endswith("_MON"):
        return _("Monthly")
    if name.endswith("_DAY"):
        return _("Day of the year")
    if name.endswith("daily"):
        return _("Daily")
    return _("Yearly")


# ---- cards -------------------------------------------------------------------------------


@dataclass
class Series:
    name: str
    label: str
    step: str
    bars: bool
    description: str
    units: str

    @property
    def trend_units(self) -> str:
        return chart_data.trend_units(self.units)


@dataclass
class Card:
    key: str
    name: str
    definition: str
    long_name: str
    title: str  # the short name, after the code (#218): "Hottest day"
    units: str
    group: str
    theme: str  # themes.THEMES key, "" for a card only in the catalogue
    topic: str  # help topic id
    param_topic: str | None
    series: list[Series] = field(default_factory=list)
    main: str = ""  # the series the card shows
    spark: dict = field(default_factory=dict)
    trend: dict | None = None
    latest: dict | None = None
    count: int = 0
    missing: int = 0
    daily: dict | None = None  # EHF and ECF daily tables
    order: int = 0

    @property
    def help_topics(self) -> str:
        """The topics of the index page's ⓘ (#177): the index, and its setting if any."""
        return " ".join(t for t in (self.topic, self.param_topic) if t)

    @property
    def hue(self) -> str:
        """The colour of the card's theme (``themes.hue_of``), for its dot and sparkline."""
        return themes.hue_of(self.theme)

    @property
    def chip(self) -> str:
        """The catalogue's filter chip the card is under (``themes.chip_of``, #200)."""
        return themes.chip_of(self.theme)

    @property
    def search_text(self) -> str:
        text = " ".join([self.key, self.name, self.title, self.definition, self.long_name])
        # Found as typed: "-2" finds "TN below −2 °C" (#226).
        return text.replace(numbers.MINUS, "-").replace(numbers.NBSP, " ").lower()

    @property
    def r_name(self) -> str:
        """R's long name, for the index page's definition line (#218), when it says more
        than the short name: "Max TX" beside "TXx Hottest day", nothing beside "FD Frost
        days"."""
        if self.long_name.casefold() == self.title.casefold():
            return ""
        return self.long_name

    @property
    def code(self) -> str:
        """The index's code, which leads wherever it is listed (#218): ``TXx``, ``TX90-HWN``."""
        return self.name

    @property
    def trend_units(self) -> str:
        return chart_data.trend_units(self.units)

    @property
    def trend_units_title(self) -> str:
        """``pp`` spelt out, for its ``abbr``; "" for other units."""
        return _("percentage points") if self.units == "%" else ""

    @property
    def series_text(self) -> str:
        return _(", ").join(s.label for s in self.series)

    @property
    def significant(self) -> bool:
        return bool(self.trend and self.trend.get("significant"))


def _x_label(step: str, x: float) -> str:
    return chart_data._x_label(step, x)


def trend_summary(plot) -> dict | None:
    """The card's and detail page's trend: per decade, the 95% bounds, significance (the
    interval excludes zero, as in the trends guide) and direction."""
    trend = plot.trend
    if trend is None:
        return None
    if not trend.valid:
        return {"valid": False}
    per = PER_DECADE.get(plot.step, 1)
    slope, lower, upper = trend.slope * per, trend.lower * per, trend.upper * per
    significant = trend.lower > 0 or trend.upper < 0
    units = _units(plot)
    direction = "up" if slope > 0 else "down" if slope < 0 else "flat"
    return {
        "valid": True,
        "slope": slope,
        "lower": lower,
        "upper": upper,
        # The number rules (#226): "+0.21", "+0.21 °C/decade", "−0.22 to 0.31".
        "slope_text": numbers.slope(slope, units),
        "per_decade_text": numbers.per_decade(slope, units),
        "interval_text": numbers.interval(lower, upper, units),
        "per_step": trend.slope,
        "p_value": trend.p_value,
        "significant": significant,
        "direction": direction,
    }


def _columns(values: list[float | None]) -> list[float | None]:
    """At most SPARK_WIDTH values: longer series averaged into columns."""
    n = len(values)
    if n <= SPARK_WIDTH:
        return values
    out = []
    for c in range(SPARK_WIDTH):
        chunk = [
            v for v in values[c * n // SPARK_WIDTH : (c + 1) * n // SPARK_WIDTH] if v is not None
        ]
        out.append(sum(chunk) / len(chunk) if chunk else None)
    return out


def sparkline(values, bars: bool = False, trend=None) -> dict:
    """SVG path data for a card: ``line`` (gaps where values are missing), or ``pos`` and
    ``neg`` bars from zero (SPI, SPEI), and ``trend`` (the Sen's slope line). Integer
    coordinates in a SPARK_WIDTH x SPARK_HEIGHT box keep the page small."""
    raw = [None if v is None or v != v else float(v) for v in values]
    cols = _columns(raw)
    present = [v for v in cols if v is not None]
    if not present:
        return {}
    n = len(raw)
    ends = None
    if trend is not None and trend.valid:
        ends = (trend.intercept, trend.intercept + trend.slope * (n - 1))
    low, high = min(present), max(present)
    if bars:
        low, high = min(low, 0.0), max(high, 0.0)
    if ends:
        low, high = min(low, *ends), max(high, *ends)
    span = (high - low) or 1.0
    top, bottom = SPARK_PAD, SPARK_HEIGHT - SPARK_PAD

    def y(v: float) -> int:
        return (
            round(bottom - (v - low) / span * (bottom - top)) if high > low else SPARK_HEIGHT // 2
        )

    m = len(cols)

    def x(i: int) -> int:
        return round(i * SPARK_WIDTH / (m - 1)) if m > 1 else SPARK_WIDTH // 2

    out: dict[str, str] = {}
    if bars:
        zero = y(0.0)
        pos, neg = [], []
        for i, v in enumerate(cols):
            if v is not None and y(v) != zero:
                (pos if v > 0 else neg).append(f"M{x(i)} {zero}V{y(v)}")
        out["pos"], out["neg"] = "".join(pos), "".join(neg)
        out["zero"] = str(zero)
        out["bar_width"] = f"{max(SPARK_WIDTH / m, 1):.1f}"
    else:
        parts, pen = [], False
        for i, v in enumerate(cols):
            if v is None:
                pen = False
                continue
            parts.append(f"{'L' if pen else 'M'}{x(i)} {y(v)}")
            pen = True
        out["line"] = "".join(parts)
        if m <= 120:  # one dot per value on short series, so isolated values show
            out["dots"] = "".join(f"M{x(i)} {y(v)}h0" for i, v in enumerate(cols) if v is not None)
    if ends:
        out["trend"] = f"M0 {y(ends[0])}L{SPARK_WIDTH} {y(ends[1])}"
    return out


def _latest(plot) -> dict | None:
    for i in range(len(plot.values) - 1, -1, -1):
        v = plot.values[i]
        if v == v:
            return {
                "value": float(v),
                "text": chart_data.number(float(v)),
                "when": _x_label(plot.step, plot.x[i]),
            }
    return None


# A value with its units ("12.5%", "20 days"): one rule for every page (#189).
with_units = chart_data.with_units


def _units(plot) -> str:
    if plot.name.startswith("day_of_"):  # its trend is in days per decade
        return _("days")
    return numbers.unit_label(plot.units)


def _definition(description: str, key: str) -> str:
    """R's plot subtitle without the leading ``name: `` (``txx: Annual warmest daily
    TX`` -> ``Annual warmest daily TX``), with °C, in the interface language."""
    text = description
    prefix = re.match(r"^[^:]{1,40}: ", text)
    if prefix and not text.startswith(("TX90-", "TN90-")):
        text = text[prefix.end() :]
    return numbers.in_text(_(catalogue.plain(text)))


@dataclass
class RunResults:
    cards: list[Card]
    plots: dict  # series name -> climpact.plots.IndexPlot
    skipped: list[dict]

    def card(self, key: str) -> Card | None:
        return next((c for c in self.cards if c.key == key), None)

    def find(self, key: str) -> Card | None:
        """The card ``key``, or the one that is the same index after a change of
        parameters (see :func:`signature`)."""
        found = self.card(key)
        if found is None and key:
            wanted = signature(key)
            found = next((c for c in self.cards if signature(c.key) == wanted), None)
        return found

    def sections(self) -> list[dict]:
        out = []
        for key, label in groups():
            cards = [c for c in self.cards if c.group == key]
            if cards:
                out.append(
                    {
                        "key": key,
                        "label": label,
                        "cards": cards,
                        "significant": sum(1 for c in cards if c.significant),
                    }
                )
        return out

    def themes(self) -> list[themes.ThemeResult]:
        """The cards by theme, in the catalogue's order within each."""
        ordered = [c for s in self.sections() for c in s["cards"]]
        return themes.results(ordered)

    def neighbours(self, card: Card) -> tuple[Card | None, Card | None]:
        ordered = [c for s in self.sections() for c in s["cards"]]
        i = ordered.index(card)
        return (ordered[i - 1] if i > 0 else None, ordered[i + 1] if i + 1 < len(ordered) else None)


def _info_for(key: str):
    if key in ("EHFdaily", "ECFdaily"):
        return catalogue.by_short()["hwEHF"]
    return catalogue.index_for_output(key)


def _new_card(key: str, order: int) -> Card:
    info = _info_for(key)
    group = info.group if info is not None else "custom"
    return Card(
        key=key,
        name=display_name(key, info),
        definition="",
        # The number rules in the names too (#226): "TN below −2 °C".
        long_name=numbers.in_text(_(info.long_name))
        if info is not None
        else _("Your own threshold index"),
        title=short_name(key, info),
        units="",
        group=group,
        theme=themes.theme_of(key, info),
        topic=info.topic_id if info is not None else "param.custom",
        param_topic=info.param_topic if info is not None else "param.custom",
        order=order,
    )


def build(
    source: RunSource, summary: dict | None = None, base: tuple[int, int] | None = None
) -> RunResults:
    """The cards of a run (uncached; see :func:`results_for`)."""
    from climpact.plots import index_plots

    tables = chart_data._Tables(source.index_source)
    cards: dict[str, Card] = {}
    plots = {}
    for _stage, group in index_plots(tables, source.params):
        for plot in group:
            plots[plot.name] = plot
            key = card_key(plot.name)
            card = cards.get(key) or cards.setdefault(key, _new_card(key, len(cards)))
            card.series.append(
                Series(
                    plot.name,
                    series_label(plot.name),
                    plot.step,
                    plot.bars,
                    plot.description,
                    _units(plot),
                )
            )
    for card in cards.values():
        names = [s.name for s in card.series]
        main = next((n for n in names if not n.startswith("day_of_")), names[0])
        plot = plots[main]
        card.main = main
        card.definition = _definition(plot.description, card.key)
        card.units = _units(plot)
        card.trend = trend_summary(plot)
        card.spark = sparkline(plot.values, plot.bars, plot.trend)
        card.latest = _latest(plot)
        card.count = len(plot.values)
        card.missing = int(sum(1 for v in plot.values if v != v))
        # Annual first, then monthly, then the days of occurrence.
        card.series.sort(key=lambda s: (s.name.startswith("day_of_"), s.name.endswith("_MON")))
    for name in ("EHFdaily", "ECFdaily"):
        key = f"indices/{name}"
        if key in tables:
            card = _new_card(name, len(cards))
            card.daily = daily_summary(tables[key])
            card.definition = (
                _("Excess heat factor for each day (°C²), used by the EHF heatwave indices.")
                if name == "EHFdaily"
                else _("Excess cold factor for each day (°C²), used by the ECF cold-wave measures.")
            )
            card.units = "°C²"
            card.main = name
            card.series = [Series(name, series_label(name), "day", False, card.definition, "°C²")]
            card.count = card.daily["days"]
            card.missing = card.daily["missing"]
            cards[name] = card
    skipped = skipped_tables(source.skipped, summary, base)
    return RunResults(sorted(cards.values(), key=lambda c: c.order), plots, skipped)


def daily_summary(table) -> dict:
    """The days, missing days, highest value and its date, and the ten highest days of a
    daily EHF or ECF table."""
    column = table.columns[1]
    values = table[column]
    present = table[values.notna()]
    top = present.nlargest(10, column)
    return {
        "column": column,
        "days": int(len(table)),
        "missing": int(values.isna().sum()),
        "first": str(table["date"].iloc[0]) if len(table) else "",
        "last": str(table["date"].iloc[-1]) if len(table) else "",
        "positive": int((values > 0).sum()),
        "top": [
            {"date": str(d), "value": float(v), "text": chart_data.number(float(v))}
            for d, v in zip(top["date"], top[column], strict=True)
        ],
    }


# ---- tables not written -----------------------------------------------------------------

# The variables each family of indices needs (for the reason an index is missing).
_TEMPERATURE = ("tmax", "tmin")


def _needs(info) -> tuple[str, ...]:
    if info is None:
        return ()
    if info.group == "precipitation" or info.short == "spi":
        return ("prcp",)
    if info.short == "spei":
        return ("prcp", "tmax", "tmin")
    return _TEMPERATURE


def skipped_tables(keys, summary: dict | None, base: tuple[int, int] | None) -> list[dict]:
    """The index tables the core did not write (every value missing, as R's
    ``write.index.csv``), one entry per index with its tables and the likely reason."""
    from climpact_web.stations.forms import MIN_BASE_DAYS
    from climpact_web.stations.station_file import base_period_days, variable_label

    by_key: dict[str, dict] = {}
    for output in keys:
        if not output.startswith("indices/"):
            continue
        name = output.removeprefix("indices/")
        key = card_key(name)
        info = _info_for(key)
        entry = by_key.setdefault(
            key,
            {"key": key, "name": display_name(key, info), "tables": [], "info": info, "reason": ""},
        )
        entry["tables"].append(name)
        entry["tables_text"] = _(", ").join(entry["tables"])
    present = {v["key"]: v["present"] for v in (summary or {}).get("variables", [])}
    base_days = None
    if summary and base and summary.get("first_date"):
        base_days = base_period_days(summary, *base)
    for entry in by_key.values():
        info = entry.pop("info")
        absent = [v for v in _needs(info) if present.get(v) == 0]
        if absent:
            entry["reason"] = _("The file has no %(variable)s values.") % {
                "variable": ", ".join(str(variable_label(v)).lower() for v in absent)
            }
        elif (
            info is not None
            and info.base_period
            and base_days is not None
            and base_days <= MIN_BASE_DAYS
        ):
            entry["reason"] = _(
                "It compares days with percentiles of the base period, and the data cover "
                "less than a year of the base period, so the percentiles could not be "
                "calculated."
            )
        else:
            entry["reason"] = _(
                "Every value is missing: no year or month had enough data under the "
                "missing-data rules (see the quality checks)."
            )
    return list(by_key.values())


# ---- cache -------------------------------------------------------------------------------

_CACHE_SIZE = 8
_cache: OrderedDict[tuple, RunResults] = OrderedDict()
_lock = threading.Lock()


def _stamp(source: RunSource) -> tuple:
    parts = []
    for path in (source.index_source.indices_dir, source.index_source.trend_path()):
        try:
            st = path.stat()
            parts.append((st.st_mtime_ns, st.st_size))
        except OSError:
            parts.append(None)
    return tuple(parts)


def results_for(
    source: RunSource, summary: dict | None = None, base: tuple[int, int] | None = None
) -> RunResults:
    """The cards of a run, cached in memory by the files' modification times, the
    parameters and the language."""
    key = (
        str(source.folder),
        source.station,
        repr(source.params),
        source.skipped,
        _stamp(source),
        get_language(),
        base,
        repr(sorted((v["key"], v["present"]) for v in (summary or {}).get("variables", []))),
    )
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    results = build(source, summary, base)
    with _lock:
        _cache[key] = results
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return results

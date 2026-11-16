"""The results dashboard of a station run (#78): one card per index table the run wrote.

Everything comes from the files of a finished ``station`` job (or of one station of a
``batch`` job, for an analysis opened from a batch's results), so the dashboard shows what
the downloads hold:

- the series, their descriptions, units and trends from the core's
  :func:`climpact.plots.index_plots` (the function the PNGs and the interactive charts
  use: Sen's slope and its 95% bounds as in ``trend/trend``, zyp's intercept), read from
  the index tables in ``indices/``;
- the daily EHF and ECF tables, which R does not plot, as cards of their own;
- the rows of ``trend/trend`` for each index (annual, monthly, seasons, SPI months);
- the tables the core did not write because every value was missing (the job's
  ``skipped``), with the likely reason.

Cards are grouped as the help's index catalogue (:mod:`climpact_web.help.indices`), and
each group belongs to a family (temperature, precipitation, heatwaves, drought, other)
for the filters. Each card has a sparkline drawn here as SVG path data, so the dashboard
needs no chart code; the interactive chart is on the index's own page.

Building the cards reads every table (about 0.2 s for 114 tables) and computes the trends
(about 0.7 s), so the result is cached in memory, keyed by the files' modification times.
"""

from __future__ import annotations

import math
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from django.utils.translation import get_language, gettext_lazy
from django.utils.translation import gettext as _

from climpact_web.charts import data as chart_data
from climpact_web.help import indices as catalogue

# Sparklines: drawn in a 240 x 60 box (stretched to the card's width with
# vector-effect: non-scaling-stroke); longer series are averaged into 240 columns.
SPARK_WIDTH, SPARK_HEIGHT, SPARK_PAD = 240, 60, 4
PER_DECADE = {"year": 10, "month": 120}

FAMILY_OF_GROUP = {
    "temperature-thresholds": "temperature",
    "temperature-extremes": "temperature",
    "temperature-percentiles": "temperature",
    "temperature-seasons": "temperature",
    "precipitation": "precipitation",
    "heatwaves": "heatwaves",
    "drought": "drought",
    "custom": "other",
}


def families() -> list[tuple[str, str]]:
    return [
        ("temperature", _("Temperature")),
        ("precipitation", _("Precipitation")),
        ("heatwaves", _("Heatwaves")),
        ("drought", _("Drought")),
        ("other", _("Your own index")),
    ]


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
    """The usual spelling: ``TXx``, ``Rx3day``, ``R30mm``, ``SPI 3-month``."""
    if info is not None and key.lower() == info.short.lower():
        return info.name
    for pattern, template in _PARAM_NAMES:
        if m := pattern.match(key):
            return template.format(m.group(1))
    if m := _SCALE.match(key):
        return _("%(index)s, %(n)s months") % {"index": m.group(2).upper(), "n": m.group(1)}
    if key in ("EHFdaily", "ECFdaily"):
        return _("%(index)s, daily") % {"index": key[:3]}
    return key.replace("-", " ")


# Heatwave tables share one catalogue entry (one long name), so each aspect gets its own
# plain name, in the words of the indices guide; the definition says which heatwaves.
_HEATWAVE = re.compile(r"^(TX90|TN90|EHF|ECF)-([A-Z]+)$")
_ASPECTS = {
    "HWN": gettext_lazy("Number of heatwaves"),
    "HWF": gettext_lazy("Heatwave days"),
    "HWD": gettext_lazy("Longest heatwave"),
    "HWM": gettext_lazy("Mean heatwave temperature"),
    "HWA": gettext_lazy("Peak temperature of the hottest heatwave"),
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
_DEFINITION_LABEL = {"TX90": "Tx90", "TN90": "Tn90", "EHF": "EHF", "ECF": "ECF"}


def plain_name(key: str, info) -> str:
    """The card's title, in words: the catalogue's long name (``Frost days``), or for the
    indices that share one entry, a name of their own (``Number of heatwaves (Tx90)``,
    ``Standardised precipitation index, 3 months``, ``Excess heat factor, daily``)."""
    if m := _HEATWAVE.match(key):
        aspect = _ASPECTS.get(m.group(2))
        if aspect:
            return _("%(aspect)s (%(definition)s)") % {
                "aspect": aspect,
                "definition": _DEFINITION_LABEL[m.group(1)],
            }
    if key == "EHFdaily":
        return _("Excess heat factor, daily")
    if key == "ECFdaily":
        return _("Excess cold factor, daily")
    if info is None:
        return _("Your own threshold index")
    if m := _SCALE.match(key):
        return _("%(index)s, %(n)s months") % {"index": _(info.long_name), "n": m.group(1)}
    return _(info.long_name)


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
    title: str  # the plain name the card and the index page lead with
    units: str
    group: str
    family: str
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
    spread: float = 0.0  # standard deviation of the series the card shows
    order: int = 0

    @property
    def search_text(self) -> str:
        return " ".join([self.key, self.name, self.title, self.definition, self.long_name]).lower()

    @property
    def code(self) -> str:
        """The index's code as Climpact's files spell it: ``TXx``, ``TX90-HWN``."""
        return self.key if _HEATWAVE.match(self.key) else self.name

    @property
    def trend_units(self) -> str:
        return chart_data.trend_units(self.units)

    @property
    def series_text(self) -> str:
        return _(", ").join(s.label for s in self.series)

    @property
    def significant(self) -> bool:
        return bool(self.trend and self.trend.get("significant"))

    @property
    def change(self) -> float:
        """How big the trend is next to the index's own variability: the slope per decade
        divided by the standard deviation of the series (0 without a trend). This puts
        days, °C, mm and % on one scale, to rank the significant trends."""
        if not (self.trend and self.trend.get("valid")) or not self.spread:
            return 0.0
        return abs(self.trend["slope"]) / self.spread


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
    direction = "up" if slope > 0 else "down" if slope < 0 else "flat"
    return {
        "valid": True,
        "slope": slope,
        "lower": lower,
        "upper": upper,
        "slope_text": _signed(slope),
        "lower_text": chart_data.number(lower),
        "upper_text": chart_data.number(upper),
        "per_step": trend.slope,
        "p_value": trend.p_value,
        "significant": significant,
        "direction": direction,
    }


def _signed(value: float) -> str:
    text = chart_data.number(abs(value))
    if text == "0":
        return text
    return ("+" if value > 0 else "−") + text


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


def _spread(values) -> float:
    """The sample standard deviation of the values present (0 for fewer than two)."""
    present = [float(v) for v in values if v == v]
    n = len(present)
    if n < 2:
        return 0.0
    mean = sum(present) / n
    return math.sqrt(sum((v - mean) ** 2 for v in present) / (n - 1))


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


def with_units(value: str, units: str) -> str:
    """A value with its units, as shown in a stat: ``20 days``, ``12.3%``, ``0.5`` without."""
    if not units:
        return value
    if units == "%":
        return _("%(value)s%%") % {"value": value}
    return _("%(value)s %(units)s") % {"value": value, "units": units}


def _units(plot) -> str:
    if plot.name.startswith("day_of_"):  # its trend is in days per decade
        return _("days")
    return chart_data.UNIT_LABELS.get(plot.units, plot.units)


def _definition(description: str, key: str) -> str:
    """R's plot subtitle without the leading ``name: `` (``txx: Annual warmest daily
    TX`` -> ``Annual warmest daily TX``), with °C, in the interface language."""
    text = description
    prefix = re.match(r"^[^:]{1,40}: ", text)
    if prefix and not text.startswith(("TX90-", "TN90-")):
        text = text[prefix.end() :]
    return _(catalogue.plain(text))


def chart_title(card: Card, series: Series) -> str:
    """The index page's chart title (#115): the code as Climpact spells it and the
    cleaned definition of the series shown (``SU: Annual number of days when TX > 25
    °C``), not R's raw plot subtitle (``su: ... 25 degrees_C``)."""
    definition = _definition(series.description, card.key)
    if definition.startswith(card.code):
        return definition
    return _("%(code)s: %(definition)s") % {"code": card.code, "definition": definition}


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
                        "family": FAMILY_OF_GROUP[key],
                        "cards": cards,
                        "significant": sum(1 for c in cards if c.significant),
                    }
                )
        return out

    def significant(self) -> list[Card]:
        """The cards with a significant trend, the largest change first (see
        :attr:`Card.change`), then in the catalogue's order."""
        ordered = [c for s in self.sections() for c in s["cards"] if c.significant]
        return sorted(ordered, key=lambda c: -c.change)

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
        long_name=_(info.long_name) if info is not None else _("Your own threshold index"),
        title=plain_name(key, info),
        units="",
        group=group,
        family=FAMILY_OF_GROUP.get(group, "other"),
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
        card.spread = _spread(plot.values)
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


# ---- the trend file -----------------------------------------------------------------------


def trend_rows(source: RunSource, key: str) -> list[dict]:
    """The rows of ``trend/trend`` for the card ``key`` (``txx``: annual, monthly and the
    seasons; ``3month_spi``: the months R reports; the custom index by its name)."""
    from climpact.io.climpact_csv import read_climpact_csv

    path = source.index_source.trend_path()
    if not path.is_file():
        return []
    if m := _SCALE.match(key):
        wanted = f"{m.group(2)}{m.group(1)}"
    else:
        wanted = key
    table = read_climpact_csv(path).data
    rows = []
    for row in table[table["Index"] == wanted].itertuples(index=False):
        lower, slope, upper = row[4], row[5], row[6]
        valid = not any(math.isnan(v) for v in (lower, slope, upper))
        rows.append(
            {
                "frequency": row[1],
                "label": _frequency_label(str(row[1])),
                "start": "" if math.isnan(row[2]) else int(row[2]),
                "end": "" if math.isnan(row[3]) else int(row[3]),
                "lower": lower,
                "slope": slope,
                "upper": upper,
                "valid": valid,
                "significant": valid and (lower > 0 or upper < 0),
                "per": _("per month") if row[1] == "monthly" else _("per year"),
            }
        )
    return rows


def _frequency_label(value: str) -> str:
    labels = {
        "annual": _("Yearly"),
        "monthly": _("Monthly"),
        "DJF": _("December to February"),
        "MAM": _("March to May"),
        "JJA": _("June to August"),
        "SON": _("September to November"),
    }
    return labels.get(value, value)


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


def anomaly_series(source: RunSource, name: str) -> dict | None:
    """The standardised anomalies of a table that has them (R's ``standardised values
    (using all years)`` column), as labels and values for a bar chart; None otherwise."""
    from climpact.io.climpact_csv import read_climpact_csv

    path = source.index_source.table_path(name)
    if not path.is_file():
        return None
    table = read_climpact_csv(path).data
    column = next((c for c in table.columns if c.startswith("standardised")), None)
    if column is None:
        return None
    step = "day" if name.endswith("_DAY") else "month" if name.endswith("_MON") else "year"
    if step == "day":
        labels = [str(i + 1) for i in range(len(table))]
    else:
        labels = [str(t if isinstance(t, str) else int(t)) for t in table["time"]]
    return {"labels": labels, "values": list(table[column]), "step": step}

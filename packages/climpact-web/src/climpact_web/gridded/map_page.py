"""A gridded run's Map tab (#295, the GridMap board): the index rail, the map and the cell
pane, as the station Indices' three columns.

The page's state is its query string, so every view of it is an address and works
without JavaScript: ``index`` (a rail entry's key: ``txx``, ``rx3day``, ``hwn_tx90``),
``freq`` (``ANN``, ``MON``, ``DAY``), ``year`` and ``month`` (``day`` for a day-of-year
file), ``scale`` (SPI and SPEI: 3, 6 or 12 months), ``cell`` (the file's ``y,x``; or
``cell_y`` and ``cell_x`` from the form without JavaScript, or ``goto``, "lat, lon"),
``view`` and ``q`` (the rail's Find). Defaults: TXx (else the first index), annual, the
last year with a value, the 12-month scale, the cell with a value nearest the middle.

The views: :data:`VIEWS` lists Year, Base mean, Anomaly and Trend; only Year is built
(#295), the others are shown unavailable until #296 builds them from ``trends.nc``. The
pane's "Mean over the grid" waits for #296 too.

The cell's statistics are computed here for its series on request, with the station's
trend (:func:`climpact.trends.plot_trend`): for an annual series the same numbers as the
run's ``trends.nc`` (#290), which computes each cell's trend with the same function.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, pgettext

from climpact_web.core import numbers
from climpact_web.gridded import maps, netcdf
from climpact_web.gridded.maps import OutputFile

VIEWS = (
    ("year", gettext_lazy("Year"), True),
    ("base", gettext_lazy("Base mean"), False),  # #296
    ("anomaly", gettext_lazy("Anomaly"), False),  # #296
    ("trend", gettext_lazy("Trend"), False),  # #296
)
FREQUENCIES = (("ANN", gettext_lazy("Annual")), ("MON", gettext_lazy("Monthly")))
FREQ_CODES = {"ANN": "ANN", "MON": "MON", "DAY": "DAY"}
# The heatwave files hold several indices, one a variable: hwn_tx90 is TX90-HWN.
HEATWAVE_VARIABLE = re.compile(r"^hw([madnf])_(tx90|tn90)$")
HEATWAVE_FILES = ("hw", "hwEHF")
GUIDE_SUFFIX = re.compile(r",? see user guide for definition\.?$", re.I)
LOW_RECORDS = ("tnn", "txn", "spi", "spei")
STATIONS_SHOWN = 3


# ---- The rail ----------------------------------------------------------------------------------


@dataclass
class Entry:
    """A row of the rail: one index, with its files by frequency."""

    key: str  # the query string's index: "txx", "rx3day", "hwn_tx90"
    code: str  # "TXx", "Rx3day", "TX90-HWN"
    name: str  # the short name, "Hottest day"
    theme: str  # the rail's group: heat, cold, rain, drought, other
    short: str  # the catalogue's short name ("rxdday"), or the key
    variable: str | None = None  # the variable, for a file of several
    definition: str = ""
    files: dict[str, OutputFile] = field(default_factory=dict)

    @property
    def freqs(self) -> list[str]:
        return [f for f in ("ANN", "MON", "DAY") if f in self.files]

    @property
    def search(self) -> str:
        return f"{self.key} {self.code} {self.name} {self.short}".lower()

    @property
    def station_key(self) -> str:
        """The index's key on a station's pages (``stations:result``)."""
        return self.code if self.variable else self.key


def _variables(path) -> list[tuple[str, str]]:

    with netcdf.dataset(path) as nc:
        return [(v["name"], v["long_name"]) for v in maps.index_variables(nc)]


def entries(job) -> list[Entry]:
    """The rail's entries: every index the run calculated, a heatwave file's variables
    each an entry of their own, in the catalogue's order within each theme."""
    from climpact_web.help.indices import index_for_output
    from climpact_web.stations import themes
    from climpact_web.stations.results import display_name, short_name

    found: dict[str, Entry] = {}
    for f in maps.output_files(job):
        if not f.index:
            continue
        info = index_for_output(f.index)
        theme = themes.chip_of(themes.theme_of(f.index, info)) if info else "other"
        if f.index in HEATWAVE_FILES:
            try:
                variables = _variables(job.output_dir / f.path)
            except (OSError, ValueError):
                continue
            for name, long_name in variables:
                m = HEATWAVE_VARIABLE.match(name)
                code = f"{m[2].upper()}-HW{m[1].upper()}" if m else name
                entry = found.setdefault(
                    name,
                    Entry(
                        key=name,
                        code=code,
                        name=short_name(code, info),
                        theme=theme,
                        short=info.short if info else f.index,
                        variable=name,
                        definition=numbers.in_text(GUIDE_SUFFIX.sub(".", long_name)),
                    ),
                )
                entry.files[f.freq] = f
            continue
        entry = found.setdefault(
            f.index,
            Entry(
                key=f.index,
                code=display_name(f.index, info),
                name=short_name(f.index, info) if info else f.index,
                theme=theme,
                short=info.short if info else f.index,
                definition=numbers.in_text(_(info.definition)) if info else "",
            ),
        )
        entry.files[f.freq] = f
    return list(found.values())


def rail_groups(items: list[Entry], current: str, link) -> list[dict]:
    """The entries by theme, in the Files tab's order (Heat, Cold, Rain, Drought, Other)."""
    from climpact_web.gridded.runs import THEME_GROUPS
    from climpact_web.stations.themes import hue_of

    out = []
    for key, label in THEME_GROUPS:
        members = [e for e in items if e.theme == key]
        if members:
            out.append(
                {
                    "key": key,
                    "label": str(label),
                    "hue": hue_of(key),
                    "entries": [
                        {
                            "entry": e,
                            "url": link(e),
                            "current": e.key == current,
                            "freqs": " ".join(e.freqs),
                        }
                        for e in members
                    ],
                }
            )
    return out


# ---- The state ---------------------------------------------------------------------------------


@dataclass
class State:
    entry: Entry
    freq: str
    file: OutputFile
    layer: maps.Layer
    t: int
    scale: int
    cell: tuple[int, int]
    q: str = ""
    goto_error: str = ""
    goto: str = ""

    @property
    def month(self) -> int | None:
        return self.layer.months[self.t] if self.layer.months else None

    @property
    def year(self) -> int | None:
        return self.layer.years[self.t] if self.layer.years else None

    def query(self, **changes) -> dict:
        """The query string of this state, with ``changes`` (None leaves a key out)."""
        out: dict = {"index": self.entry.key, "freq": self.freq}
        if self.layer.freq == "DAY":
            out["day"] = self.layer.times[self.t] if self.layer.times else None
        else:
            out["year"] = self.year
            if self.layer.months:
                out["month"] = self.month
        if self.layer.scales:
            out["scale"] = self.layer.scales[self.scale]
        out["cell"] = f"{self.cell[0]},{self.cell[1]}"
        if self.q:
            out["q"] = self.q
        out.update(changes)
        return {k: v for k, v in out.items() if v not in (None, "")}


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cell(value, ny: int, nx: int) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        y, x = (int(v) for v in str(value).split(","))
    except ValueError:
        return None
    return (y, x) if 0 <= y < ny and 0 <= x < nx else None


GOTO = re.compile(
    r"^\s*([+\-−]?\d+(?:[.,]\d+)?)\s*°?\s*([NS])?\s*[,;\s]\s*"
    r"([+\-−]?\d+(?:[.,]\d+)?)\s*°?\s*([EW])?\s*$",
    re.I,
)


def parse_goto(text: str) -> tuple[float, float] | None:
    """``-33.86, 151.21``, ``−33.86 151.21`` or ``33.86 S, 151.21 E`` as (lat, lon)."""
    m = GOTO.match(text or "")
    if not m:
        return None

    def number(s: str) -> float:
        return float(s.replace("−", "-").replace(",", "."))

    lat, lon = number(m[1]), number(m[3])
    if m[2] and m[2].upper() == "S":
        lat = -abs(lat)
    if m[4] and m[4].upper() == "W":
        lon = -abs(lon)
    if not (-90 <= lat <= 90 and -360 <= lon <= 360):
        return None
    return lat, lon


def resolve(request, job) -> State | None:
    """The page's state from the query string (see the module's docstring); None when
    the run wrote no index file."""
    items = entries(job)
    if not items:
        return None
    q = request.GET
    by_key = {e.key: e for e in items}
    entry = by_key.get(q.get("index"))
    if entry is None and q.get("file"):  # the old explorer's addresses
        entry = next((e for e in items if any(f.path == q["file"] for f in e.files.values())), None)
    if entry is None:
        entry = by_key.get("txx") or next((e for e in items if "ANN" in e.files), items[0])
    freq = q.get("freq") if q.get("freq") in entry.files else None
    if freq is None and q.get("file"):
        freq = next((k for k, f in entry.files.items() if f.path == q["file"]), None)
    freq = freq or ("ANN" if "ANN" in entry.files else entry.freqs[0])
    chosen = entry.files[freq]
    path = job.output_dir / chosen.path
    layer = maps.open_layer(path, chosen.path, entry.variable)
    scale = 0
    if layer.scales:
        wanted = q.get("scale") or ("12" if "12" in layer.scales else layer.scales[0])
        scale = layer.scales.index(wanted) if wanted in layer.scales else 0
    t = None
    if layer.freq == "DAY":
        day = q.get("day")
        t = layer.times.index(day) if day in layer.times else None
    else:
        t = layer.step_of(_int(q.get("year")), _int(q.get("month")))
    if t is None and q.get("t") is not None:  # the old explorer's time step
        n = _int(q.get("t"))
        t = n if n is not None and 0 <= n < len(layer.times) else None
    if t is None:
        month = (_int(q.get("month")) or 12) if layer.months else None
        t = maps.last_step_with_values(path, layer, scale, month)
    ny, nx = len(layer.lat), len(layer.lon)
    goto, goto_error = q.get("goto", "").strip(), ""
    cell = _cell(q.get("cell"), ny, nx)
    if goto:
        point = parse_goto(goto)
        found = maps.nearest_cell(layer, *point) if point else None
        if point is None:
            goto_error = _("Write a latitude and a longitude, such as −33.86, 151.21.")
        elif found is None:
            goto_error = _("That point is outside the grid.")
        else:
            cell = found
    if cell is None and q.get("cell_y") is not None:
        cell = _cell(f"{q.get('cell_y')},{q.get('cell_x')}", ny, nx)
    if cell is None:  # the cell with a value nearest the middle
        values = maps.grid_values(path, layer, t, scale)
        finite = np.argwhere(np.isfinite(values))
        if finite.size:
            mid = np.array([ny / 2, nx / 2])
            y, x = finite[np.argmin(((finite - mid) ** 2).sum(axis=1))]
            cell = (int(y), int(x))
        else:
            cell = (ny // 2, nx // 2)
    return State(entry, freq, chosen, layer, t, scale, cell, q.get("q", "")[:100],
                 goto_error, goto if goto_error else "")  # fmt: skip


# ---- The page ----------------------------------------------------------------------------------


def time_label(layer: maps.Layer, t: int) -> str:
    """ "2019", "Dec 2019", "day 182"."""
    if layer.freq == "DAY":
        return _("day %(n)s") % {"n": layer.times[t]}
    if layer.months:
        from django.utils.dates import MONTHS_3

        return f"{str(MONTHS_3[layer.months[t]]).title()} {layer.years[t]}"
    return layer.times[t] if layer.times else ""


def month_name(month: int) -> str:
    from django.utils.dates import MONTHS

    return str(MONTHS[month])


def _units(layer: maps.Layer) -> str:
    return maps.units_of(layer.units)


def cell_title(layer: maps.Layer, cell: tuple[int, int]) -> str:
    y, x = cell
    if layer.geographic:
        lon = (layer.lon[x] + 180) % 360 - 180
        return numbers.coordinates(layer.lat[y], lon)
    return f"{numbers.number(layer.lat[y])}, {numbers.number(layer.lon[x])}"


def context(request, run, job) -> dict:
    """Everything the Map tab draws (gridded/_map.html), or {} without index files."""
    s = resolve(request, job)
    if s is None:
        return {}
    layer, entry = s.layer, s.entry
    path = job.output_dir / s.file.path
    base_url = reverse("gridded:run", args=[run.pk])

    def page(**changes) -> str:
        return f"{base_url}?{urlencode(s.query(**changes))}"

    def endpoint(name: str, **changes) -> str:
        return f"{reverse(name, args=[run.pk])}?{urlencode(s.query(**changes))}"

    values = maps.grid_values(path, layer, s.t, s.scale)
    units = _units(layer)
    kind = maps.kind_of(entry.short, layer.units, entry.theme)
    edges = maps.edges_for(path, layer, kind, s.scale, s.month)
    f = maps.frame(layer)
    finite = values[np.isfinite(values)]

    def entry_link(e: Entry) -> str:
        keep = {"index": e.key, "freq": s.freq if s.freq in e.files else None, "scale": None}
        if s.freq not in e.files:
            keep["month"] = None
        return page(**keep)

    # Time: the stepper's previous and next steps (of the same month for a monthly file:
    # months step by month), the label.
    def step_link(t: int) -> str | None:
        if not 0 <= t < len(layer.times):
            return None
        if layer.freq == "DAY":
            return page(day=layer.times[t])
        changes = {"year": layer.years[t]}
        if layer.months:
            changes["month"] = layer.months[t]
        return page(**changes)

    label = time_label(layer, s.t)
    freq_links = []
    for code, name in FREQUENCIES:
        available = code in entry.files
        freq_links.append(
            {
                "label": str(name),
                "current": s.freq == code,
                "url": page(freq=code, month=12 if code == "MON" else None) if available else "",
            }
        )
    views = [
        {
            "key": key,
            "label": str(name),
            "current": key == "year",
            "available": available,
            "url": page() if available else "",
        }
        for key, name, available in VIEWS
    ]
    scales = [
        {"label": _("%(months)s months") % {"months": m}, "current": i == s.scale,
         "url": page(scale=m)}
        for i, m in enumerate(layer.scales)
    ]  # fmt: skip
    if layer.freq == "DAY":
        hint = _("The threshold on %(when)s.") % {"when": label}
    elif layer.scales:
        hint = _("The %(months)s-month index in %(when)s.") % {
            "months": layer.scales[s.scale],
            "when": label,
        }
    else:
        hint = _("The value in %(when)s.") % {"when": label}

    unit_label = numbers.unit_label(units)
    legend_title = f"{entry.code}, {label}" + (f" ({unit_label})" if unit_label else "")
    shown = (
        _("Cells with a value: %(low)s to %(high)s")
        % {"low": numbers.number(float(finite.min())), "high": numbers.number(float(finite.max()))}
        if finite.size
        else _("No cell has a value in %(when)s.") % {"when": label}
    )
    legend = {
        "kind": kind,
        "title": legend_title,
        "range": shown,
        "bins": list(range(len(edges) - 1)) if edges else [],
        "ticks": maps.legend_ticks(edges) if edges else [],
        "has_missing": bool(np.isnan(values).any()),
    }
    map_label = _("Map of %(code)s, %(when)s: %(count)s cells.") % {
        "code": entry.code,
        "when": label,
        "count": numbers.grouped(values.size),
    }
    if finite.size:
        map_label += " " + shown + (f" {unit_label}." if unit_label else ".")
    rect = f.cell_rect(*s.cell)
    grid = {
        "nx": f.nx,
        "ny": f.ny,
        "left": f.left,
        "top": f.top,
        "w": f.plot_w,
        "h": f.plot_h,
        "rows": f.rows,
        "cols": f.cols,
        "lat": [cell_title_part(v, "N", layer.geographic) for v in layer.lat],
        "lon": [cell_title_part(v, "E", layer.geographic) for v in layer.lon],
        "cell": list(s.cell),
        "values": endpoint("gridded:map_values", cell=None, q=None),
        "page": page(cell=None),
        "code": entry.code,
        "units": unit_label,
        "noValue": _("no value"),
        "roledescription": _("map"),
        "selected": _("Selected: %(where)s"),
    }
    return {
        "map_state": s,
        "rail": rail_groups(
            [e for e in entries(job) if not s.q or s.q.lower() in e.search] or [entry],
            entry.key,
            entry_link,
        ),
        "rail_action": base_url,
        "rail_hidden": s.query(q=None),
        "entry": entry,
        "layer": layer,
        "file": s.file,
        "views": views,
        "freq_links": freq_links,
        "scales": scales,
        "time": {"label": label, "prev": step_link(s.t - 1), "next": step_link(s.t + 1)},
        "hint": hint,
        "downloads": {
            "png": endpoint("gridded:map_png", download="1", cell=None, q=None),
            "csv": endpoint("gridded:map_csv", cell=None, q=None),
            "nc": reverse("gridded:file", args=[run.pk, s.file.path]),
        },
        "frame": f,
        "raster": {
            "light": endpoint("gridded:map_png", theme="light", cell=None, q=None),
            "dark": endpoint("gridded:map_png", theme="dark", cell=None, q=None),
        },
        "selected_rect": rect,
        "legend": legend,
        "map_label": map_label,
        "grid_data": grid,
        "lat_options": [
            {"value": y, "label": cell_title_part(v, "N", layer.geographic)}
            for y, v in enumerate(layer.lat)
        ],
        "lon_options": [
            {"value": x, "label": cell_title_part(v, "E", layer.geographic)}
            for x, v in enumerate(layer.lon)
        ],
        "form_hidden": s.query(cell=None, q=None),
        "pane": pane(request, run, s, path, units, page, endpoint),
    }


def cell_title_part(value: float, positive: str, geographic: bool) -> str:
    if not geographic:
        return numbers.number(value)
    if positive == "E":
        value = (value + 180) % 360 - 180
    return numbers.coordinate(value, positive)


# ---- The cell pane -----------------------------------------------------------------------------


def _series(path, s: State) -> tuple[np.ndarray, np.ndarray, str]:
    """The pane's series: the cell's values by year (of the chosen month for a monthly
    file; by day of the year for a day-of-year file), their x and step."""
    layer = s.layer
    values = maps.cell_series(path, layer, s.cell[0], s.cell[1], s.scale)
    if layer.freq == "DAY":
        return values, np.array([float(v) for v in layer.times]), "day"
    if layer.months:
        picked = [t for t, m in enumerate(layer.months) if m == s.month]
        return values[picked], np.array([float(layer.years[t]) for t in picked]), "year"
    return values, np.array([float(y) for y in layer.years]), "year"


def base_period(run) -> tuple[int, int] | None:
    o = run.options
    try:
        return int(o["base_start"]), int(o["base_end"])
    except (KeyError, TypeError, ValueError):
        return None


def pane(request, run, s: State, path, units: str, page, endpoint) -> dict:
    """The cell pane: the cell's centre, index and bounds, its series as a chart, the
    statistics in the station pane's order, the values by year and the stations of the
    browser's workspaces in the cell."""
    from climpact.plots import IndexPlot
    from climpact.trends import plot_trend
    from climpact_web.stations import index_page
    from climpact_web.stations.results import trend_summary
    from climpact_web.stations.themes import hue_of

    layer, entry = s.layer, s.entry
    values, x, step = _series(path, s)
    bars = layer.freq == "MON" and bool(layer.scales)
    has_values = bool(np.isfinite(values).any())
    trend = plot_trend(values) if step == "year" and has_values else None
    plot = IndexPlot(
        name=entry.code,
        description="",
        units=units,
        x=x,
        values=values,
        step=step,
        bars=bars,
        trend=trend,
    )
    summary = trend_summary(plot) if trend is not None else None
    base = base_period(run) if step == "year" else None
    card = SimpleNamespace(code=entry.code, units=units, key=entry.short, trend=summary)
    when = time_label(layer, s.t)
    series_word = (
        month_name(s.month) if layer.months else pgettext("series", "annual")
        if step == "year" else _("by day of the year")
    )  # fmt: skip
    y, xi = s.cell
    south, north, west, east = maps.cell_bounds(layer, y, xi)
    out: dict = {
        "title": cell_title(layer, s.cell),
        "sub": _(
            "Cell %(row)s, %(col)s of %(rows)s × %(cols)s · %(south)s to %(north)s lat, "
            "%(west)s to %(east)s lon"
        )
        % {
            "row": y + 1,
            "col": xi + 1,
            "rows": len(layer.lat),
            "cols": len(layer.lon),
            "south": numbers.number(south, 3),
            "north": numbers.number(north, 3),
            "west": numbers.number(west, 3),
            "east": numbers.number(east, 3),
        },  # fmt: skip
        "caption": _("%(code)s, %(series)s, %(first)s–%(last)s")
        % {
            "code": entry.code,
            "series": series_word,
            "first": numbers.number(x[0], 0) if len(x) else "",
            "last": numbers.number(x[-1], 0) if len(x) else "",
        },
        "caption_tail": _(", %(series)s, %(first)s–%(last)s")
        % {
            "series": series_word,
            "first": numbers.number(x[0], 0) if len(x) else "",
            "last": numbers.number(x[-1], 0) if len(x) else "",
        },
        "unit_label": numbers.unit_label(units),
        "has_values": has_values,
        "when": when,
        "csv": endpoint("gridded:series_csv", q=None),
        "goto_error": s.goto_error,
        "goto": s.goto,
        "stations": stations_in_cell(request, layer, s, entry),
        "trend_word": step == "year",
        "hue": hue_of(entry.theme),
    }
    if not has_values:
        return out
    present = [(float(v), i) for i, v in enumerate(values) if math.isfinite(v)]
    mean = None
    if base:
        chosen = [v for v, i in present if base[0] <= x[i] <= base[1]]
        mean = sum(chosen) / len(chosen) if chosen else None
    at = None
    if step == "year" and s.year is not None and float(s.year) in list(x):
        at = list(x).index(float(s.year))
    payload = index_page.payload(card, plot, base, [], name=entry.code)
    payload["summary"] = series_summary(entry, plot, out["title"], series_word, summary)
    payload["csv"] = out["csv"]
    out["chart_data"] = payload
    out["chart_at"] = str(s.year) if at is not None else ""
    out["chart_label"] = payload["summary"]
    from climpact_web.stations import index_detail

    out["chart"] = index_detail.chart(plot, base)
    stats = []
    if summary is not None:
        valid = summary.get("valid")
        significant = (
            _("Yes: the interval excludes zero") if summary.get("significant") else _("No")
        )
        stats += [
            {
                "label": _("Sen's slope"),
                "value": summary["per_decade_text"] if valid else _("Too few values"),
                "mono": valid,
            },
            {
                "label": _("95% interval"),
                "value": summary["interval_text"] if valid else "–",
                "mono": True,
            },
            {"label": _("Significant"), "value": significant if valid else "–"},
        ]
    if mean is not None:
        stats.append(
            {
                "label": _("Base mean"),
                "value": numbers.with_unit(numbers.number(mean), units),
                "note": f"{base[0]}–{base[1]}",
                "mono": True,
            }
        )
    if at is not None and math.isfinite(values[at]):
        text = numbers.with_unit(numbers.number(float(values[at])), units)
        if mean is not None:
            text += " " + _("(anomaly %(value)s)") % {
                "value": numbers.anomaly(float(values[at]) - mean)
            }
        stats.append({"label": when, "value": text, "mono": True})
    elif at is not None:
        stats.append({"label": when, "value": _("No value"), "mono": False})
    if present and step == "year":
        low = entry.short in LOW_RECORDS
        value, i = (min if low else max)(present, key=lambda p: (p[0], -p[1]))
        record = (
            _("%(value)s in %(year)s (lowest)") if low else _("%(value)s in %(year)s (highest)")
        )
        stats.append(
            {
                "label": _("Record"),
                "value": record % {
                    "value": numbers.with_unit(numbers.number(value), units),
                    "year": int(x[i]),
                },
                "mono": True,
            }
        )  # fmt: skip
    out["stats"] = stats
    out["rows"] = [
        {
            "when": _when(step, x[i]),
            "value": numbers.number(float(v)) if math.isfinite(v) else "–",
            "anomaly": numbers.anomaly(float(v) - mean)
            if mean is not None and math.isfinite(v)
            else "–",
            "current": i == at,
        }
        for i, v in enumerate(values)
    ]
    out["has_anomaly"] = mean is not None
    return out


def _when(step: str, x: float) -> str:
    """A value's year, or its day of the year."""
    return str(int(x)) if step == "year" else _("day %(n)s") % {"n": int(x)}


def series_summary(entry: Entry, plot, where: str, series_word: str, summary) -> str:
    """The chart's text alternative: the series, its years, its lowest and highest values
    and its trend."""
    present = [(float(v), i) for i, v in enumerate(plot.values) if v == v]
    if not present:
        return ""
    (high, hi), (low, lo) = max(present), min(present)
    text = _(
        "%(code)s, %(series)s, at %(where)s from %(first)s to %(last)s. Lowest %(low)s in "
        "%(low_when)s, highest %(high)s in %(high_when)s."
    ) % {
        "code": entry.code,
        "series": series_word,
        "where": where,
        "first": _when(plot.step, plot.x[0]),
        "last": _when(plot.step, plot.x[-1]),
        "low": numbers.with_unit(numbers.number(low), plot.units),
        "low_when": _when(plot.step, plot.x[lo]),
        "high": numbers.with_unit(numbers.number(high), plot.units),
        "high_when": _when(plot.step, plot.x[hi]),
    }
    if summary and summary.get("valid"):
        text += " " + _("Sen's slope %(slope)s, 95%% interval %(interval)s.") % {
            "slope": summary["per_decade_text"],
            "interval": summary["interval_text"],
        }
    return text


def stations_in_cell(request, layer: maps.Layer, s: State, entry: Entry) -> list[dict]:
    """The stations of the browser's workspaces whose coordinates are in the cell, each
    with its index page for this index."""
    from climpact_web.jobs.views import OWNER_KEY
    from climpact_web.stations.models import Station

    owner = request.session.get(OWNER_KEY)
    if not owner or not layer.geographic:
        return []
    south, north, west, east = maps.cell_bounds(layer, *s.cell)
    out = []
    candidates = Station.objects.filter(
        owner=owner, latitude__gte=south, latitude__lte=north, longitude__isnull=False
    ).select_related("workspace")
    for station in candidates.order_by("-updated_at"):
        lon = station.longitude
        if not any(west <= lon + shift <= east for shift in (0.0, 360.0, -360.0)):
            continue
        workspace = station.workspace.display_name
        out.append(
            {
                "name": str(station),
                "workspace": workspace if workspace != str(station) else "",
                "url": station.url("result", entry.station_key),
                "code": entry.code,
            }
        )
        if len(out) == STATIONS_SHOWN:
            break
    return out

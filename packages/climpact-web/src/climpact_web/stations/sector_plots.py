"""Step 5's results (#90): a finished sector job's files read back, and its charts drawn on
the server as inline SVG, each with a table of the same numbers.

The core writes R's files to ``<station>/corr/``: the four scatter tables (``year``, a
temperature summary, the sector series) and the table of correlations (``indice``,
``cor``, ``category``), with their PNGs. The page reads the CSV files the user downloads,
so what it shows is what is in them, and draws:

- the correlation of the sector series with each index as horizontal bars (R draws
  vertical bars with the values halfway along them), temperature and precipitation
  indices in their chart colours, each value written at the end of its bar;
- each scatter plot with its least-squares line, and R's equation and R² (rounded to 2
  decimals, from the job's result, the numbers the PNG prints).

Inline SVG rather than the uPlot charts of #75: neither chart is a time series, the page
then loads no chart code, and it works without JavaScript; the tables are the keyboard and
screen-reader view, and the CSV and PNG files are linked under each chart.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe
from django.utils.translation import gettext as _

from climpact_web.stations.qc_plots import _fmt, _nice

TOKENS = {"temperature": "--chart-tmax", "precipitation": "--chart-prcp"}


def category_label(category: str) -> str:
    return {"temperature": _("Temperature"), "precipitation": _("Precipitation")}.get(
        category, category
    )


def x_label(name: str) -> str:
    """R's x-axis labels, with units."""
    return {
        "tmin": _("Average minimum temperature (°C)"),
        "tmax": _("Average maximum temperature (°C)"),
        "t": _("Average temperature (°C)"),
        "above30": _("Days above 30 °C"),
    }.get(name, name)


def _float(text: str) -> float | None:
    text = text.strip()
    if text in ("", "NA", "NaN"):
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _read(path: Path) -> list[list[str]]:
    with path.open(newline="") as f:
        return list(csv.reader(f))


def number(value: float | None) -> str:
    """A value as the files show it (shortest form), or "NA"."""
    if value is None:
        return "NA"
    text = repr(round(value, 10))
    return text[:-2] if text.endswith(".0") else text


# ---- the model ---------------------------------------------------------------------------


@dataclass
class Bar:
    index: str  # the file name's index, e.g. "txx"
    name: str  # display name, e.g. "TXx"
    cor: float | None
    category: str

    @property
    def cor_text(self) -> str:
        return number(self.cor)

    @property
    def category_text(self) -> str:
        return category_label(self.category)


@dataclass
class Scatter:
    name: str  # "tmin", "tmax", "t" or "above30"
    label: str  # the x axis, with units
    file: str  # the CSV, relative to the job's output/
    png: str | None
    rows: list[tuple[int, float | None, float | None]]
    slope: float | None
    intercept: float | None
    r_squared: float | None
    svg: SafeString = field(default_factory=lambda: mark_safe(""))

    @property
    def equation(self) -> str:
        if self.slope is None or self.intercept is None:
            return ""
        sign = "+" if self.intercept >= 0 else "−"
        return f"y = {number(self.slope)} x {sign} {number(abs(self.intercept))}"

    @property
    def r_squared_text(self) -> str:
        return number(self.r_squared)

    @property
    def table(self) -> list[tuple[int, str, str]]:
        return [(year, number(x), number(y)) for year, x, y in self.rows]


@dataclass
class SectorResults:
    station: str
    column: str  # the series correlated, as in the files (Detrended.Wheat.yield..t.ha.)
    detrended: bool
    title: str
    y_label: str
    bars: list[Bar]
    scatters: list[Scatter]
    correlation_file: str
    correlation_png: str | None
    zip: str | None
    years: tuple[int, int] | None  # first and last year in common

    @property
    def missing(self) -> list[Bar]:
        return [b for b in self.bars if b.cor is None]

    @property
    def missing_names(self) -> str:
        return ", ".join(b.name for b in self.missing)

    def ordered(self, order: str) -> list[Bar]:
        if order != "strength":
            return self.bars
        return sorted(self.bars, key=lambda b: (b.cor is None, -abs(b.cor or 0)))


def load(job) -> SectorResults | None:
    """The results of a finished sector job, or None when its files are gone."""
    from climpact_web.help import indices as catalogue
    from climpact_web.stations.results import display_name

    result, out = job.result or {}, job.output_dir
    if not result.get("correlation"):
        return None
    corr = out / result["correlation"]
    if not corr.is_file():
        return None
    rows = _read(corr)[1:]
    bars = []
    for row in rows:
        if len(row) < 3:
            continue
        index = row[0]
        bars.append(
            Bar(
                index,
                display_name(index, catalogue.index_for_output(index)),
                _float(row[1]),
                row[2],
            )
        )
    scatters = []
    years: set[int] = set()
    for item in result.get("scatters", []):
        path = out / item["file"]
        if not path.is_file():
            return None
        table = []
        for row in _read(path)[1:]:
            if len(row) >= 3 and _float(row[0]) is not None:
                table.append((int(float(row[0])), _float(row[1]), _float(row[2])))
        years.update(y for y, _x, _v in table)
        png = path.with_suffix(".png")
        scatter = Scatter(
            item["name"],
            x_label(item["name"]),
            item["file"],
            png.relative_to(out).as_posix() if png.is_file() else None,
            table,
            item.get("slope"),
            item.get("intercept"),
            item.get("r_squared"),
        )
        scatters.append(scatter)
    params = job.params or {}
    y_label = params.get("y_label") or ""
    for scatter in scatters:
        scatter.svg = scatter_svg(scatter, y_label)
    corr_png = corr.with_suffix(".png")
    return SectorResults(
        station=result.get("station", ""),
        column=result.get("sector_column", ""),
        detrended=bool(result.get("detrended")),
        title=params.get("title") or "",
        y_label=y_label,
        bars=bars,
        scatters=scatters,
        correlation_file=result["correlation"],
        correlation_png=corr_png.relative_to(out).as_posix() if corr_png.is_file() else None,
        zip=result.get("zip"),
        years=(min(years), max(years)) if years else None,
    )


# ---- drawing ------------------------------------------------------------------------------


def _symmetric_ticks(values: list[float]) -> list[float]:
    """Ticks from -m to m, m the largest absolute value rounded up (at least 0.2, at most
    1): correlations on both sides of zero, read against the same scale."""
    top = max([abs(v) for v in values] + [0.2])
    top = min(1.0, math.ceil(top * 10 - 1e-9) / 10)
    step = 0.1 if top <= 0.4 else 0.2 if top <= 0.8 else 0.25
    n = math.ceil(top / step - 1e-9)
    top = n * step
    return [round(-top + i * step, 10) for i in range(2 * n + 1)]


def bar_svg(bars: list[Bar], label: str) -> SafeString:
    """Horizontal bars from zero, one per index in the given order; the value at the end
    of each bar; NA written at zero."""
    if not bars:
        return mark_safe("")
    row, top, bottom, left, right, width = 18, 6, 26, 92, 44, 640
    height = top + row * len(bars) + bottom
    ticks = _symmetric_ticks([b.cor for b in bars if b.cor is not None])
    low, high = ticks[0], ticks[-1]
    plot_w = width - left - right

    def x(v):
        return left + (v - low) / (high - low) * plot_w

    zero = x(0)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" class="sector-plot" role="img" '
        f'aria-label="{escape(label)}" focusable="false">'
    ]
    for t in ticks:
        xx = x(t)
        parts.append(
            f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="{top}" y2="{height - bottom}" '
            'class="sector-plot__grid"/>'
            f'<text x="{xx:.1f}" y="{height - bottom + 16}" class="sector-plot__tick" '
            f'text-anchor="middle">{escape(_fmt(t))}</text>'
        )
    for i, bar in enumerate(bars):
        y = top + i * row
        mid = y + row / 2
        tip = f"{bar.name}: {bar.cor_text} ({bar.category_text})"
        parts.append(f"<g><title>{escape(tip)}</title>")
        parts.append(
            f'<text x="{left - 8}" y="{mid:.1f}" class="sector-plot__label" text-anchor="end" '
            f'dominant-baseline="middle">{escape(bar.name)}</text>'
        )
        if bar.cor is None:
            parts.append(
                f'<text x="{zero + 6:.1f}" y="{mid:.1f}" class="sector-plot__value '
                f'sector-plot__value--na" dominant-baseline="middle">NA</text>'
            )
        else:
            end = x(bar.cor)
            x0, w = min(zero, end), abs(end - zero)
            token = TOKENS.get(bar.category, "--chart-7")
            parts.append(
                f'<rect x="{x0:.1f}" y="{y + 3}" width="{max(w, 1):.1f}" height="{row - 6}" '
                f'class="sector-plot__bar" style="fill: var({token})"/>'
            )
            anchor, tx = ("start", end + 4) if bar.cor >= 0 else ("end", end - 4)
            parts.append(
                f'<text x="{tx:.1f}" y="{mid:.1f}" class="sector-plot__value" '
                f'text-anchor="{anchor}" dominant-baseline="middle">{escape(bar.cor_text)}</text>'
            )
        parts.append("</g>")
    parts.append(
        f'<line x1="{zero:.1f}" x2="{zero:.1f}" y1="{top}" y2="{height - bottom}" '
        'class="sector-plot__zero"/></svg>'
    )
    return mark_safe("".join(parts))


def fit(rows) -> tuple[float, float] | None:
    """The least-squares line (slope, intercept) through the complete rows, unrounded, so
    the line drawn is exact; the equation printed is R's rounded one."""
    pts = [(x, y) for _year, x, y in rows if x is not None and y is not None]
    if len(pts) < 2:
        return None
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    if sxx == 0:
        return None
    slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx
    return slope, my - slope * mx


def scatter_svg(scatter: Scatter, y_label: str) -> SafeString:
    """The points (year in each point's tooltip) and the regression line across the range
    of x."""
    pts = [(year, x, y) for year, x, y in scatter.rows if x is not None and y is not None]
    if not pts:
        return mark_safe("")
    width, height, left, right, top, bottom = 480, 300, 56, 14, 12, 44
    xs, ys = [p[1] for p in pts], [p[2] for p in pts]
    line = fit(scatter.rows)
    if line is not None:  # keep the line's ends inside the plot
        ys = ys + [line[0] * min(xs) + line[1], line[0] * max(xs) + line[1]]
    xt, yt = _nice(min(xs), max(xs)), _nice(min(ys), max(ys))
    x0, x1 = min([min(xs), *xt]), max([max(xs), *xt])
    y0, y1 = min([min(ys), *yt]), max([max(ys), *yt])
    x1, y1 = (x1 if x1 > x0 else x0 + 1), (y1 if y1 > y0 else y0 + 1)
    pw, ph = width - left - right, height - top - bottom

    def px(v):
        return left + (v - x0) / (x1 - x0) * pw

    def py(v):
        return top + (y1 - v) / (y1 - y0) * ph

    label = _("%(y)s against %(x)s") % {"y": y_label or _("Sector data"), "x": scatter.label}
    parts = [
        f'<svg viewBox="0 0 {width} {height}" class="sector-plot sector-plot--scatter" '
        f'role="img" aria-label="{escape(label)}" focusable="false">'
    ]
    for t in yt:
        yy = py(t)
        parts.append(
            f'<line x1="{left}" x2="{width - right}" y1="{yy:.1f}" y2="{yy:.1f}" '
            'class="sector-plot__grid"/>'
            f'<text x="{left - 6}" y="{yy:.1f}" class="sector-plot__tick" text-anchor="end" '
            f'dominant-baseline="middle">{escape(_fmt(t))}</text>'
        )
    for t in xt:
        xx = px(t)
        parts.append(
            f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="{top}" y2="{height - bottom}" '
            'class="sector-plot__grid"/>'
            f'<text x="{xx:.1f}" y="{height - bottom + 16}" class="sector-plot__tick" '
            f'text-anchor="middle">{escape(_fmt(t))}</text>'
        )
    parts.append(
        f'<text x="{left + pw / 2:.0f}" y="{height - 6}" class="sector-plot__tick" '
        f'text-anchor="middle">{escape(scatter.label)}</text>'
        f'<text transform="translate(14 {top + ph / 2:.0f}) rotate(-90)" '
        f'class="sector-plot__tick" text-anchor="middle">{escape(y_label)}</text>'
    )
    if line is not None:
        slope, intercept = line
        parts.append(
            f'<line x1="{px(min(xs)):.1f}" y1="{py(slope * min(xs) + intercept):.1f}" '
            f'x2="{px(max(xs)):.1f}" y2="{py(slope * max(xs) + intercept):.1f}" '
            'class="sector-plot__fit"/>'
        )
    for year, x, y in pts:
        tip = f"{year}: {number(x)}, {number(y)}"
        parts.append(
            f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="3.5" class="sector-plot__point">'
            f"<title>{escape(tip)}</title></circle>"
        )
    parts.append("</svg>")
    return mark_safe("".join(parts))

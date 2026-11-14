"""The distribution plots of the quality-control review (#77), drawn on the server as
inline SVG, each with a table of the same numbers.

They replace the plots of R's quality-control step (``services/check/``), which the R app
writes as PNG and PDF files:

- ``fourboxes`` (``*_boxes``): monthly box plots of non-zero precipitation, TX, TN and
  DTR, whiskers at the outlier thresholds (``iqr_prec``, ``iqr_temp``), so the values
  beyond them are those in ``qc/outliers``;
- ``boxseries``: box plots by year, whiskers at 4 IQR (precipitation) and 3 IQR
  (temperatures), as R draws them whatever the thresholds;
- ``roundcheck``: how often each tenth (.0 to .9) occurs, for non-zero precipitation,
  TX and TN;
- the precipitation histogram of R's ``plotToFile``: days of 1 mm or more in 2 mm bins
  up to 40 mm, and one bin above.

R's daily series plots (``pplotts``) are the interactive charts of the screen. The boxes
use the core's ``boxplot_stats`` (R's ``boxplot.stats``) on the rows the checks see.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe
from django.utils.translation import gettext as _

WIDTH, HEIGHT = 640, 240
LEFT, RIGHT, TOP, BOTTOM = 48, 8, 10, 30
TOKENS = {
    "prcp": "--chart-prcp",
    "tmax": "--chart-tmax",
    "tmin": "--chart-tmin",
    "dtr": "--chart-7",
}


@dataclass
class Box:
    label: str
    stats: tuple[float, float, float, float, float] | None  # whisker, hinge, median, hinge, whisker
    outliers: list[float]
    n: int


def _arrays(rows):
    import numpy as np

    arrays = {
        k: np.array([np.nan if v is None else v for v in rows.values[k]], dtype=float)
        for k in ("prcp", "tmax", "tmin")
    }
    arrays["dtr"] = arrays["tmax"] - arrays["tmin"]
    return arrays


def _boxes(x, groups, labels, coef) -> list[Box]:
    import numpy as np

    from climpact import qc

    boxes = []
    for key, label in zip(groups, labels, strict=True):
        values = x[key]
        values = values[~np.isnan(values)]
        if not len(values):
            boxes.append(Box(label, None, [], 0))
            continue
        stats = qc.boxplot_stats(values, coef)
        outside = values[(values < stats[0]) | (values > stats[4])]
        boxes.append(
            Box(label, tuple(float(s) for s in stats), [float(v) for v in outside], len(values))
        )
    return boxes


def _nice(low: float, high: float, count: int = 5) -> list[float]:
    if not math.isfinite(low) or not math.isfinite(high):
        return []
    if high <= low:
        high = low + 1
    raw = (high - low) / count
    step = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * step:
            step *= m
            break
    first = math.ceil(low / step) * step
    ticks = []
    v = first
    while v <= high + step * 1e-9:
        ticks.append(round(v, 10))
        v += step
    return ticks


def _fmt(v: float) -> str:
    text = f"{v:.4g}"
    return "0" if text == "-0" else text


def _axes(parts, low, high, y, ticks, unit):
    for t in ticks:
        yy = y(t)
        parts.append(
            f'<line x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{yy:.1f}" y2="{yy:.1f}" '
            'class="qc-plot__grid"/>'
            f'<text x="{LEFT - 6}" y="{yy:.1f}" class="qc-plot__tick" text-anchor="end" '
            f'dominant-baseline="middle">{escape(_fmt(t))}</text>'
        )
    parts.append(
        f'<text transform="translate(12 {TOP + (HEIGHT - TOP - BOTTOM) / 2:.0f}) rotate(-90)" '
        f'class="qc-plot__tick" text-anchor="middle">{escape(unit)}</text>'
    )


def box_svg(boxes: list[Box], variable: str, unit: str, label: str, every: int = 1) -> SafeString:
    """Box plots side by side: box from hinge to hinge, median line, whiskers, values
    beyond the whiskers as rings."""
    present = [b for b in boxes if b.stats]
    if not present:
        return mark_safe("")
    low = min(min(b.stats[0], *b.outliers) if b.outliers else b.stats[0] for b in present)
    high = max(max(b.stats[4], *b.outliers) if b.outliers else b.stats[4] for b in present)
    ticks = _nice(low, high)
    low, high = min([low, *ticks]), max([high, *ticks])
    span = (high - low) or 1
    plot_h = HEIGHT - TOP - BOTTOM

    def y(v):
        return TOP + (high - v) / span * plot_h

    step = (WIDTH - LEFT - RIGHT) / len(boxes)
    half = max(1.0, min(14.0, step * 0.32))
    token = TOKENS[variable]
    parts = [
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" class="qc-plot" role="img" '
        f'aria-label="{escape(label)}" focusable="false" style="--plot-colour: var({token})">'
    ]
    _axes(parts, low, high, y, ticks, unit)
    for i, b in enumerate(boxes):
        cx = LEFT + step * (i + 0.5)
        if i % every == 0:
            parts.append(
                f'<text x="{cx:.1f}" y="{HEIGHT - 10}" class="qc-plot__tick" '
                f'text-anchor="middle">{escape(b.label)}</text>'
            )
        if not b.stats:
            continue
        w0, h0, med, h1, w1 = (y(v) for v in b.stats)
        parts.append(
            f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{w1:.1f}" y2="{h1:.1f}" '
            'class="qc-plot__whisker"/>'
            f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{h0:.1f}" y2="{w0:.1f}" '
            'class="qc-plot__whisker"/>'
            f'<rect x="{cx - half:.1f}" y="{h1:.1f}" width="{2 * half:.1f}" '
            f'height="{max(0.5, h0 - h1):.1f}" class="qc-plot__box"/>'
            f'<line x1="{cx - half:.1f}" x2="{cx + half:.1f}" y1="{med:.1f}" y2="{med:.1f}" '
            'class="qc-plot__median"/>'
        )
        for v in b.outliers:
            parts.append(f'<circle cx="{cx:.1f}" cy="{y(v):.1f}" r="2.5" class="qc-plot__out"/>')
    parts.append("</svg>")
    return mark_safe("".join(parts))


def bar_svg(
    labels: list[str], counts: list[int], variable: str, label: str, unit: str
) -> SafeString:
    if not counts or not any(counts):
        return mark_safe("")
    high = max(counts)
    ticks = _nice(0, high)
    high = max([high, *ticks])
    plot_h = HEIGHT - TOP - BOTTOM

    def y(v):
        return TOP + (high - v) / high * plot_h

    step = (WIDTH - LEFT - RIGHT) / len(counts)
    parts = [
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" class="qc-plot" role="img" '
        f'aria-label="{escape(label)}" focusable="false" '
        f'style="--plot-colour: var({TOKENS[variable]})">'
    ]
    _axes(parts, 0, high, y, ticks, unit)
    every = max(1, math.ceil(len(counts) / 12))
    for i, (text, c) in enumerate(zip(labels, counts, strict=True)):
        x0 = LEFT + step * i + step * 0.1
        top = y(c)
        parts.append(
            f'<rect x="{x0:.1f}" y="{top:.1f}" width="{step * 0.8:.1f}" '
            f'height="{TOP + plot_h - top:.1f}" class="qc-plot__bar"/>'
        )
        if i % every == 0:
            parts.append(
                f'<text x="{x0 + step * 0.4:.1f}" y="{HEIGHT - 10}" class="qc-plot__tick" '
                f'text-anchor="middle">{escape(text)}</text>'
            )
    parts.append("</svg>")
    return mark_safe("".join(parts))


def _variables():
    return (
        ("prcp", _("Precipitation, days with rain"), _("mm")),
        ("tmax", _("Maximum temperature (TX)"), "°C"),
        ("tmin", _("Minimum temperature (TN)"), "°C"),
        ("dtr", _("Diurnal temperature range (DTR)"), "°C"),
    )


def monthly_boxes(rows, params) -> list[dict]:
    """``fourboxes``: one box per calendar month and variable."""
    import numpy as np

    x = _arrays(rows)
    months = np.array([int(d[5:7]) for d in rows.dates])
    names = [_("Jan"), _("Feb"), _("Mar"), _("Apr"), _("May"), _("Jun"),
             _("Jul"), _("Aug"), _("Sep"), _("Oct"), _("Nov"), _("Dec")]  # fmt: skip
    out = []
    for variable, label, unit in _variables():
        values = x[variable]
        with np.errstate(invalid="ignore"):
            use = values > 0 if variable == "prcp" else ~np.isnan(values)
        groups = {m: values[use & (months == m)] for m in range(1, 13)}
        coef = params.iqr_prec if variable == "prcp" else params.iqr_temp
        boxes = _boxes(groups, list(range(1, 13)), names, coef)
        if variable == "prcp":
            # fourboxes lists only precipitation above the upper whisker.
            for b in boxes:
                if b.stats:
                    b.outliers = [v for v in b.outliers if v > b.stats[4]]
        title = _("%(variable)s by month") % {"variable": label}
        out.append(_plot(variable, title, unit, boxes, box_svg(boxes, variable, unit, title)))
    return out


def annual_boxes(rows) -> list[dict]:
    """``boxseries``: one box per year and variable (whiskers at 4 and 3 IQR, as R)."""
    import numpy as np

    x = _arrays(rows)
    years = np.array([int(d[:4]) for d in rows.dates])
    labels = list(range(int(years.min()), int(years.max()) + 1)) if len(years) else []
    every = max(1, math.ceil(len(labels) / 10))
    out = []
    for variable, label, unit in _variables():
        values = x[variable]
        with np.errstate(invalid="ignore"):
            use = values > 0 if variable == "prcp" else ~np.isnan(values)
        groups = {yr: values[use & (years == yr)] for yr in labels}
        boxes = _boxes(groups, labels, [str(v) for v in labels], 4 if variable == "prcp" else 3)
        title = _("%(variable)s by year") % {"variable": label}
        out.append(
            _plot(variable, title, unit, boxes, box_svg(boxes, variable, unit, title, every))
        )
    return out


def _plot(variable, title, unit, boxes, svg) -> dict:
    return {
        "key": variable,
        "title": title,
        "unit": unit,
        "svg": svg,
        "rows": [
            {
                "label": b.label,
                "n": b.n,
                "stats": [_fmt(v) for v in b.stats] if b.stats else None,
                "outliers": len(b.outliers),
            }
            for b in boxes
        ],
    }


def decimals(rows) -> list[dict]:
    """``roundcheck``: how often each tenth occurs (non-zero precipitation, TX, TN)."""
    import numpy as np

    x = _arrays(rows)
    out = []
    for variable, label, _unit in _variables()[:3]:
        values = x[variable]
        with np.errstate(invalid="ignore"):
            values = values[values > 0] if variable == "prcp" else values[~np.isnan(values)]
        tenths = np.mod(np.round(np.mod(values, 1) * 10), 10).astype(int)
        counts = [int((tenths == d).sum()) for d in range(10)]
        total = sum(counts)
        title = _("Decimals of %(variable)s") % {"variable": label}
        labels = [f".{d}" for d in range(10)]
        out.append(
            {
                "key": variable,
                "title": title,
                "svg": bar_svg(labels, counts, variable, title, _("days")),
                "rows": [
                    {"label": lab, "count": c, "percent": round(100 * c / total, 1) if total else 0}
                    for lab, c in zip(labels, counts, strict=True)
                ],
                "total": total,
            }
        )
    return out


def precipitation_histogram(rows) -> dict:
    """Days with 1 mm or more, in 2 mm bins ``(0, 2]`` ... ``(38, 40]`` and above 40."""
    import numpy as np

    values = _arrays(rows)["prcp"]
    with np.errstate(invalid="ignore"):
        wet = values[values >= 1]
    edges = list(range(0, 42, 2))
    counts = [int(((wet > a) & (wet <= b)).sum()) for a, b in zip(edges, edges[1:], strict=False)]
    labels = [f"{b}" for b in edges[1:]]
    above = int((wet > 40).sum())
    if above:
        counts.append(above)
        labels.append(_("40+"))
    title = _("Days by amount of precipitation (1 mm or more)")
    table = [
        {
            "label": (_("%(low)s to %(high)s") % {"low": a, "high": b}) if i < 20 else _("over 40"),
            "count": c,
        }
        for i, (a, b, c) in enumerate(zip(edges, [*edges[1:], None], counts, strict=False))
    ]
    return {
        "title": title,
        "svg": bar_svg(labels, counts, "prcp", title, _("days")),
        "rows": table,
        "total": int(len(wet)),
    }

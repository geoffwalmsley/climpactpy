"""The static data preview of step 1: monthly means of the daily series drawn as a small
inline SVG, server-side, with no JavaScript.

This is the placeholder until the interactive chart layer (#75) is available: the step 1
template marks the place (``CHART HOOK``) where its chart include replaces this figure,
fed by the daily series at ``stations:series`` (CSV).
"""

from __future__ import annotations

from dataclasses import dataclass

WIDTH, HEIGHT = 960, 170
PAD_X, PAD_TOP, PAD_BOTTOM = 44, 10, 24


@dataclass
class Panel:
    key: str
    paths: list[dict]  # {"d": svg path, "token": --chart-* name}
    y_labels: list[dict]  # {"y": px, "text": str}
    x_labels: list[dict]  # {"x": px, "text": str}
    height: int = HEIGHT
    width: int = WIDTH


def _scale(lo: float, hi: float, a: float, b: float):
    span = (hi - lo) or 1.0
    return lambda v: a + (v - lo) * (b - a) / span


def _path(values: list[float | None], x, y) -> str:
    """An SVG path through the values, broken at gaps (None)."""
    parts, pen_down = [], False
    for i, value in enumerate(values):
        if value is None:
            pen_down = False
            continue
        parts.append(f"{'L' if pen_down else 'M'}{x(i):.1f} {y(value):.1f}")
        pen_down = True
    return "".join(parts)


def _nice_ticks(lo: float, hi: float) -> list[float]:
    import math

    rough = max((hi - lo) / 3, 1e-9)
    magnitude = 10 ** math.floor(math.log10(rough))
    step = next(m * magnitude for m in (1, 2, 5, 10) if m * magnitude >= rough)
    start = math.floor(lo / step) * step
    ticks, value = [], start
    while value <= hi + 1e-9:
        if value >= lo - 1e-9:
            ticks.append(value)
        value += step
    return ticks


def _x_labels(start: str, months: int, x) -> list[dict]:
    first_year, first_month = (int(p) for p in start.split("-"))
    years = (months + first_month - 2) // 12 + 1
    every = max(1, round(years / 8 / 5) * 5) if years > 10 else 1
    labels = []
    for k in range(years + 1):
        year = first_year + k
        index = (year - first_year) * 12 - (first_month - 1)
        if 0 <= index < months and year % every == 0:
            labels.append({"x": round(x(index), 1), "text": str(year)})
    return labels


def panels(preview: dict) -> list[Panel]:
    """Temperature (monthly mean maximum and minimum) and precipitation (monthly total)."""
    out = []
    months = len(preview.get("tmax") or [])
    if months < 2:
        return out
    x = _scale(0, months - 1, PAD_X, WIDTH - 4)
    x_labels = _x_labels(preview["start"], months, x)
    for key, series in (("temperature", ("tmax", "tmin")), ("prcp", ("prcp",))):
        values = [v for s in series for v in preview[s] if v is not None]
        if not values:
            continue
        lo, hi = min(values), max(values)
        if key == "prcp":
            lo = 0.0
        ticks = _nice_ticks(lo, hi)
        lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
        y = _scale(lo, hi, HEIGHT - PAD_BOTTOM, PAD_TOP)
        out.append(
            Panel(
                key=key,
                paths=[{"d": _path(preview[s], x, y), "token": f"--chart-{s}"} for s in series],
                y_labels=[{"y": round(y(t), 1), "text": f"{t:g}"} for t in ticks],
                x_labels=x_labels,
            )
        )
    return out

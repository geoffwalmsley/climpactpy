"""Where a gridded map is (#295): the coastline and a few places, from a bundled outline.

``data/outline.npz`` holds Natural Earth's 1:50m coastline and populated places (public
domain; built by ``scripts/build-map-outline.py``, which says where the files come from).
No map tiles or other network services are used, so the map works offline.

- :func:`coastline` gives the coastline's lines that cross a box of longitude and
  latitude, thinned to the map's resolution. Grids in 0–360° longitude are matched by
  shifting the outline a turn east or west.
- :func:`places` picks three to five places in the box to label: the most prominent first
  (Natural Earth's scale rank, then population), none too close to another or to the edge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

OUTLINE = Path(__file__).resolve().parent / "data" / "outline.npz"
SCALE = 1000.0  # the file's units: thousandths of a degree


@dataclass(frozen=True)
class Box:
    """A box of longitude and latitude in degrees, in the grid's own longitudes (which
    may run past 180°)."""

    west: float
    east: float
    south: float
    north: float


@dataclass(frozen=True)
class Place:
    name: str
    lon: float
    lat: float
    rank: int
    population: int


@lru_cache(maxsize=1)
def _outline():
    with np.load(OUTLINE) as data:
        starts = data["coast_starts"]
        points = np.cumsum(data["coast_deltas"].astype(np.int64), axis=0)
        # Each line's first point is stored whole; the cumulative sum carries the earlier
        # lines' ends into it, so take them back off.
        offsets = np.zeros_like(points)
        for i in range(1, len(starts) - 1):
            offsets[starts[i] : starts[i + 1]] = points[starts[i] - 1]
        coast = (points - offsets) / SCALE
        lines = [coast[starts[i] : starts[i + 1]] for i in range(len(starts) - 1)]
        places = [
            Place(str(n), float(p[0]) / SCALE, float(p[1]) / SCALE, int(r), int(pop))
            for n, p, r, pop in zip(
                data["place_names"],
                data["place_points"],
                data["place_rank"],
                data["place_population"],
                strict=True,
            )
        ]
    return lines, places


def _shifts(box: Box) -> list[float]:
    """The turns to add to the outline's longitudes (−180 to 180) to cover the box."""
    return [s for s in (-360.0, 0.0, 360.0) if box.west - 1 < 180 + s and box.east + 1 > -180 + s]


def coastline(box: Box, tolerance: float = 0.0) -> list[np.ndarray]:
    """The coastline's lines, as ``(n, 2)`` arrays of longitude and latitude, that cross
    ``box``: each run of points inside it, with the point before and after so the line
    reaches the edge (the map clips it there). With a ``tolerance`` in degrees (about a
    pixel of the map), points in the same ``tolerance`` square as the point before them
    are left out, and so are islands smaller than two of them."""
    lines, _places = _outline()
    margin = max(tolerance, 0.01)
    w, e = box.west - margin, box.east + margin
    s, n = box.south - margin, box.north + margin
    out = []
    for shift in _shifts(box):
        for line in lines:
            lon = line[:, 0] + shift
            lat = line[:, 1]
            inside = (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)
            if not inside.any():
                continue
            keep = inside.copy()
            keep[1:] |= inside[:-1]
            keep[:-1] |= inside[1:]
            # Runs of kept points, each a line of its own.
            edges = np.flatnonzero(np.diff(np.concatenate([[0], keep.astype(np.int8), [0]])))
            for a, b in zip(edges[::2], edges[1::2], strict=True):
                part = np.column_stack([lon[a:b], lat[a:b]])
                if tolerance > 0 and len(part) > 2:
                    cells = np.floor(part / tolerance)
                    moved = np.any(cells[1:] != cells[:-1], axis=1)
                    mask = np.concatenate([[True], moved])
                    mask[-1] = True
                    part = part[mask]
                span = np.ptp(part, axis=0) if len(part) >= 2 else np.zeros(2)
                if len(part) >= 2 and span.max() >= 2 * tolerance:  # not a speck at this scale
                    out.append(part)
    return out


def places(box: Box, count: int = 5, spacing: float = 0.18, edge: float = 0.04) -> list[Place]:
    """Up to ``count`` places in ``box`` to label, the most prominent first: none within
    ``edge`` (a share of the box's width and height) of its edge, nor within ``spacing``
    of the box's width of a place already chosen (their labels would overlap)."""
    _lines, every = _outline()
    width, height = box.east - box.west, box.north - box.south
    if width <= 0 or height <= 0:
        return []
    found = []
    for shift in _shifts(box):
        for p in every:
            lon = p.lon + shift
            if (
                box.west + edge * width <= lon <= box.east - edge * width
                and box.south + edge * height <= p.lat <= box.north - edge * height
            ):
                found.append(Place(p.name, lon, p.lat, p.rank, p.population))
    found.sort(key=lambda p: (p.rank, -p.population, p.name))
    chosen: list[Place] = []
    for p in found:
        if all(
            math.hypot((p.lon - q.lon) / width, (p.lat - q.lat) / height) >= spacing for q in chosen
        ):
            chosen.append(p)
        if len(chosen) == count:
            break
    return chosen

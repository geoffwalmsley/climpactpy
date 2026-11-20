r"""Build the gridded map's outline (#295) from Natural Earth's 1:50m data.

Natural Earth (https://www.naturalearthdata.com) is in the public domain: "No permission
is needed to use Natural Earth. Crediting the authors is unnecessary." The two GeoJSON
files come from the project's repository at a fixed release::

    NE=https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson
    curl -LO $NE/ne_50m_coastline.geojson
    curl -LO $NE/ne_50m_populated_places_simple.geojson
    uv run python scripts/build-map-outline.py ne_50m_coastline.geojson \
        ne_50m_populated_places_simple.geojson

It writes ``packages/climpact-web/src/climpact_web/gridded/data/outline.npz``, read by
``climpact_web.gridded.outline``: the coastline's lines (longitude and latitude in
thousandths of a degree, each line's points as differences from the one before) and the
populated places (name, position, population and Natural Earth's scale rank).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

OUT = (
    Path(__file__).resolve().parents[1]
    / "packages/climpact-web/src/climpact_web/gridded/data/outline.npz"
)
SCALE = 1000  # thousandths of a degree: about 110 m, finer than the 1:50m outline


def lines(geojson: dict) -> list[np.ndarray]:
    out = []
    for feature in geojson["features"]:
        geometry = feature["geometry"]
        parts = (
            [geometry["coordinates"]]
            if geometry["type"] == "LineString"
            else geometry["coordinates"]
        )
        for part in parts:
            points = np.rint(np.asarray(part, dtype=float)[:, :2] * SCALE).astype(np.int32)
            if len(points) >= 2:
                out.append(points)
    return out


def main(coastline: str, places: str) -> None:
    coast = lines(json.loads(Path(coastline).read_text()))
    starts = np.cumsum([0] + [len(p) for p in coast]).astype(np.int32)
    deltas = np.concatenate([np.diff(p, axis=0, prepend=np.zeros((1, 2), np.int32)) for p in coast])
    features = json.loads(Path(places).read_text())["features"]
    props = [f["properties"] for f in features]
    np.savez_compressed(
        OUT,
        coast_starts=starts,
        coast_deltas=deltas.astype(np.int32),
        place_names=np.array([p["name"] for p in props]),
        place_points=np.rint(
            np.array([[p["longitude"], p["latitude"]] for p in props]) * SCALE
        ).astype(np.int32),
        place_population=np.array([max(p["pop_max"] or 0, 0) for p in props], dtype=np.int64),
        place_rank=np.array([p["scalerank"] for p in props], dtype=np.int16),
        source=np.array(
            "Natural Earth 1:50m coastline and populated places (simple), v5.1.2; public domain"
        ),
    )
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {len(coast)} lines, {len(props)} places)")


if __name__ == "__main__":
    main(*sys.argv[1:3])

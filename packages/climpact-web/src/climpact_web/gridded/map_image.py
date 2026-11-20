"""The gridded map's images (#295).

- :func:`raster_png`: the field as a PNG with one pixel per cell, north up and west left,
  each pixel its bin's colour from a palette and a cell with no value transparent (the
  page shows the sunken surface through it). Written here with zlib: an indexed PNG of a
  700 x 900 grid takes a few tens of milliseconds and no imaging library.
- :func:`figure_png`: "Map as PNG" in Download: the same cells drawn with matplotlib,
  with the coastline, the places, the axes, a title and the legend, to put in a report.
"""

from __future__ import annotations

import io
import struct
import zlib

import numpy as np

from climpact_web.gridded import outline
from climpact_web.gridded.maps import Frame


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _rgb(colour: str) -> bytes:
    value = colour.lstrip("#")
    return bytes(int(value[i : i + 2], 16) for i in (0, 2, 4))


def raster_png(bins: np.ndarray, colours: list[str]) -> bytes:
    """An indexed PNG of ``bins`` (``(rows, columns)``, each a bin's number, 255 for no
    value): one pixel per cell in the bin's colour, transparent where there is no value."""
    rows, cols = bins.shape
    transparent = len(colours)
    pixels = np.where(bins == 255, transparent, bins).astype(np.uint8)
    raw = np.hstack([np.zeros((rows, 1), np.uint8), pixels]).tobytes()  # filter 0 per row
    palette = b"".join(_rgb(c) for c in colours) + b"\0\0\0"
    alpha = b"\xff" * len(colours) + b"\0"
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", struct.pack(">IIBBBBB", cols, rows, 8, 3, 0, 0, 0)),
            _chunk(b"PLTE", palette),
            _chunk(b"tRNS", alpha),
            _chunk(b"IDAT", zlib.compress(raw, 6)),
            _chunk(b"IEND", b""),
        ]
    )


def figure_png(
    bins: np.ndarray,
    colours: list[str],
    ticks: list[str],
    f: Frame,
    title: str,
    legend_title: str,
    no_value: str,
    sunken: str,
    text: str,
) -> bytes:
    """The map drawn for a report: the cells (``bins`` in the frame's order), the
    coastline and places, the axes in degrees, ``title`` above and the legend under it:
    the bins with their breaks (``ticks``) and the colour of no value."""
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.colors import ListedColormap
    from matplotlib.figure import Figure

    box = f.box
    width = 7.2
    height = width * f.plot_h / f.plot_w
    fig = Figure(figsize=(width + 1.0, height + 1.6), dpi=150)
    ax = fig.add_axes((0.11, 0.2, 0.85, 0.72))
    ax.set_facecolor(sunken)
    masked = np.ma.masked_equal(bins.astype(int), 255)
    cmap = ListedColormap(colours)
    ax.imshow(
        masked,
        cmap=cmap,
        vmin=-0.5,
        vmax=len(colours) - 0.5,
        extent=(box.west, box.east, box.south, box.north),
        interpolation="nearest",
        aspect=f.plot_h / f.plot_w * (box.east - box.west) / (box.north - box.south),
    )
    if f.geographic:
        for line in outline.coastline(box, tolerance=(box.east - box.west) / 1500):
            ax.plot(line[:, 0], line[:, 1], color=text, linewidth=0.6)
        for p in outline.places(box):
            ax.plot(p.lon, p.lat, "o", color=text, markersize=2.5)
            ax.annotate(p.name, (p.lon, p.lat), xytext=(4, 3), textcoords="offset points",
                        fontsize=7, color=text)  # fmt: skip
    ax.set_xlim(box.west, box.east)
    ax.set_ylim(box.south, box.north)
    ax.set_xticks([t["value"] for t in f.x_ticks])
    ax.set_xticklabels([t["text"] for t in f.x_ticks], fontsize=7)
    ax.set_yticks([t["value"] for t in f.y_ticks])
    ax.set_yticklabels([t["text"] for t in f.y_ticks], fontsize=7)
    ax.set_title(title, fontsize=9, loc="left")
    key = fig.add_axes((0.11, 0.07, 0.6, 0.035))
    key.imshow(np.arange(len(colours))[None, :], cmap=cmap, aspect="auto",
               extent=(0, len(colours), 0, 1))  # fmt: skip
    key.set_yticks([])
    key.set_xticks(range(len(ticks)))
    key.set_xticklabels(ticks, fontsize=6)
    key.set_title(legend_title, fontsize=7, loc="left")
    none = fig.add_axes((0.76, 0.07, 0.03, 0.035))
    none.set_facecolor(sunken)
    none.set_xticks([])
    none.set_yticks([])
    fig.text(0.8, 0.075, no_value, fontsize=7)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    return buffer.getvalue()

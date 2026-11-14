"""Shared by the forms that name a station (the single-station steps, #76)."""

import re

# The station name becomes a folder and file names (the core writes <out>/<name>/...).
STATION_NAME = r"^[\w()\-][\w .()\-]*$"


def safe_station_name(text: str) -> str:
    """A station name from a file name: characters other than letters, digits, spaces and
    ``.()-_`` become ``_``."""
    name = re.sub(r"[^\w .()\-]", "_", text).strip().lstrip(".")
    return name[:100] or "station"

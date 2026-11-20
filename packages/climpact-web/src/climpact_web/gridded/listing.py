"""New gridded run's file chooser (#292, the GridNew board): a folder's listing, each
netCDF file with the daily variables and dates read from its header, and what the files
chosen so far hold.

A file's header is read with :func:`climpact_web.gridded.inspection.inspect_file`
(metadata and coordinates only) and kept while the file's size and modification time
stay the same, so moving between folders, or ticking a file, reads nothing again.
Paths on the server's disk are only listed in local mode (the views see to it). The
set-up page's Browse buttons (#320) list folders the same way, to choose a thresholds
file or a folder to copy the results to (:func:`picking`).
"""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from pathlib import Path

from django.utils.translation import gettext as _

from climpact_web.gridded import inspection, netcdf

NETCDF_SUFFIXES = (".nc", ".nc4", ".netcdf")
CACHE_SIZE = 4096  # headers kept, by path, size and modification time


@dataclass
class Listed:
    """One netCDF file of a folder listing, as its header describes it."""

    path: str
    name: str
    size: int
    variables: list[str] = field(default_factory=list)
    dates: str = ""  # "1961–2020", or the base period of a thresholds file
    note: str = ""  # why it cannot be chosen: "no time axis", "thresholds file", ...
    thresholds: bool = False  # a thresholds file, written by a thresholds run

    @property
    def usable(self) -> bool:
        return not self.note


_cache: OrderedDict[tuple, Listed] = OrderedDict()


def _years(first: str, last: str) -> str:
    if not first or not last:
        return ""
    a, b = first[:4].lstrip("0") or "0", last[:4].lstrip("0") or "0"
    return a if a == b else f"{a}–{b}"


def _global_attr(path: str, name: str) -> str:

    try:
        with netcdf.dataset(path) as nc:
            return str(getattr(nc, name, "")).strip()
    except (OSError, ValueError):
        return ""


def _has_time_axis(path: str) -> bool:

    try:
        with netcdf.dataset(path) as nc:
            return any(inspection._axis(nc, dim) == "T" for dim in nc.dimensions)
    except (OSError, ValueError):
        return False


def _describe(path: str) -> Listed:
    from climpact.gridded.indices import THRESHOLD_FILE_VARIABLES

    info = inspection.inspect_file(path)
    listed = Listed(path=path, name=info.name, size=info.size)
    names = [v.name for v in info.variables]
    if any(name in THRESHOLD_FILE_VARIABLES for name in names):
        listed.note = _("thresholds file")
        listed.thresholds = True
        listed.dates = _global_attr(path, "base_period").replace("-", "–")
        return listed
    listed.variables = names
    listed.dates = _years(info.first, info.last)
    if info.ok:
        return listed
    if not info.format:
        listed.note = _("cannot be opened")
    elif not names:
        listed.note = _("no time axis") if not _has_time_axis(path) else _("no daily grid")
    elif info.calendar and info.calendar.lower() not in inspection.SUPPORTED_CALENDARS:
        listed.note = _("%(calendar)s calendar") % {"calendar": info.calendar}
    else:
        listed.note = _("dates cannot be read")
    return listed


def describe(path: str | Path) -> Listed | None:
    """The file at ``path`` as the listing shows it, from its header (cached), or None
    when it is gone."""
    path = str(path)
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (path, stat.st_size, stat.st_mtime_ns)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    listed = _describe(path)
    _cache[key] = listed
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return listed


def crumbs(folder: Path) -> list[dict]:
    """The folder's path as links, from the top folder down: ``[{"name", "path"}]``."""
    parts = [folder, *folder.parents]
    return [{"name": p.name or str(p), "path": str(p)} for p in reversed(parts)]


def listing(folder: str | Path, chosen: list[str] | None = None, with_files: bool = True) -> dict:
    """A folder's subfolders and netCDF files (each described from its header), for the
    chooser. ``chosen`` are the paths ticked so far, in any folder; ``files=False`` lists
    the subfolders alone."""
    path = Path(folder).resolve()
    chosen = list(chosen or [])
    folders, files, error = [], [], ""
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
    except OSError:
        entries, error = [], _("This folder cannot be read.")
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_dir():
                folders.append({"name": entry.name, "path": entry.path})
            elif with_files and entry.is_file() and entry.name.lower().endswith(NETCDF_SUFFIXES):
                listed = describe(entry.path)
                if listed is not None:
                    files.append(listed)
        except OSError:
            continue
    here = {f.path for f in files}
    return {
        "folder": str(path),
        "crumbs": crumbs(path),
        "folders": folders,
        "files": files,
        "chosen": [p for p in chosen if p in here],
        "elsewhere": [p for p in chosen if p not in here],
        "error": error,
    }


def summary(paths: list[str]) -> dict:
    """What the files chosen so far hold: how many, their daily variables (in the order
    they first appear) and their total size."""
    variables: list[str] = []
    size = 0
    count = 0
    for path in paths:
        listed = describe(path)
        if listed is None:
            continue
        count += 1
        size += listed.size
        variables += [v for v in listed.variables if v not in variables]
    return {"count": count, "variables": variables, "size": size}


def picking(folder: str | Path, pick: str) -> dict:
    """The set-up page's Browse (#320): a folder's listing for choosing one thresholds file
    (``pick="file"``: every netCDF file is listed, but only thresholds files can be
    chosen) or a folder (``pick="folder"``: the subfolders alone)."""
    out = listing(folder, with_files=pick == "file")
    other = _("not a thresholds file")
    # Copies: the descriptions are cached for New run's listing too.
    out["files"] = [f if f.thresholds or f.note else replace(f, note=other) for f in out["files"]]
    return out

"""Inspecting netCDF files before a gridded run (#85): what each file holds (variables,
units, calendar, grid, time range), a guess at which variables are TX, TN and
precipitation, and the checks the run would otherwise fail on, in plain language.

Only the files' metadata and coordinates are read (netCDF4 and cftime, no data arrays),
so inspecting a large file is quick. The final check before a run opens the files with
the core's own reader (:func:`preflight`), so what passes here is what the run accepts.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from django.utils.translation import gettext as _

# The core's names for the three variables, and R's names for them in the web form.
ROLES = ("tasmax", "tasmin", "pr")
# Names tried, in order, when guessing each variable (R's app defaults first: tmax, tmin,
# precip; then CMIP and other common names).
GUESSES = {
    "tasmax": ("tmax", "tasmax", "tx", "tmx", "max_temp", "tasmaxadjust", "maximum_temperature"),
    "tasmin": ("tmin", "tasmin", "tn", "tmn", "min_temp", "tasminadjust", "minimum_temperature"),
    "pr": ("precip", "pr", "prcp", "precipitation", "rain", "rr", "tp", "pradjust"),
}
NETCDF_SIGNATURES = (b"CDF\x01", b"CDF\x02", b"CDF\x05", b"\x89HDF\r\n\x1a\n")
SUPPORTED_CALENDARS = {
    "standard",
    "gregorian",
    "proleptic_gregorian",
    "noleap",
    "365_day",
    "360_day",
}


@dataclass
class Variable:
    name: str
    dims: list[str]
    shape: list[int]
    dtype: str
    units: str = ""
    long_name: str = ""
    standard_name: str = ""


@dataclass
class FileInfo:
    """One input file: what it holds, or why it cannot be read."""

    path: str
    name: str
    size: int = 0
    format: str = ""
    variables: list[Variable] = field(default_factory=list)  # (time, y, x) variables only
    time_units: str = ""
    calendar: str = ""
    first: str = ""  # first and last day, ISO
    last: str = ""
    days: int = 0
    ny: int = 0
    nx: int = 0
    y_range: list[float] = field(default_factory=list)
    x_range: list[float] = field(default_factory=list)
    problem: str = ""

    @property
    def ok(self) -> bool:
        return not self.problem

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> FileInfo:
        data = dict(data)
        data["variables"] = [Variable(**v) for v in data.get("variables", [])]
        return cls(**data)


def is_netcdf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            head = f.read(8)
    except OSError:
        return False
    return head.startswith(NETCDF_SIGNATURES)


def _attr(var, name: str) -> str:
    try:
        value = var.getncattr(name)
    except AttributeError:
        return ""
    return str(value).strip()


def _axis(nc, dim: str) -> str:
    """T, Y or X for a dimension, as the core's reader decides (``gridded.io._axis``)."""
    from climpact.gridded.io import _AXIS_NAMES, _AXIS_STANDARD_NAMES

    var = nc.variables.get(dim)
    if var is not None:
        axis = _attr(var, "axis").upper()
        if axis in ("T", "Y", "X"):
            return axis
        standard = _attr(var, "standard_name")
        for key, names in _AXIS_STANDARD_NAMES.items():
            if standard in names:
                return key
    for key, names in _AXIS_NAMES.items():
        if dim.lower() in names:
            return key
    return ""


def _range(nc, dim: str) -> list[float]:
    var = nc.variables.get(dim)
    if var is None or var.ndim != 1 or var.size == 0:
        return []
    import numpy as np

    values = np.asarray(var[:], dtype=float)
    finite = values[np.isfinite(values)]
    if not finite.size:
        return []
    return [round(float(finite.min()), 4), round(float(finite.max()), 4)]


def inspect_file(path: str | Path) -> FileInfo:
    """What ``path`` holds, read from its metadata and coordinates only."""
    import cftime
    import netCDF4

    path = Path(path)
    info = FileInfo(path=str(path), name=path.name)
    try:
        info.size = path.stat().st_size
    except OSError:
        info.problem = _("The file was not found.")
        return info
    if not path.is_file():
        info.problem = _("This is a folder, not a file.")
        return info
    if not is_netcdf(path):
        info.problem = _("This is not a netCDF file.")
        return info
    try:
        nc = netCDF4.Dataset(path)
    except OSError as exc:
        info.problem = _("The file could not be opened: %(error)s") % {"error": exc}
        return info
    with nc:
        info.format = nc.data_model
        for name, var in nc.variables.items():
            if var.ndim != 3:
                continue
            axes = [_axis(nc, d) for d in var.dimensions]
            if sorted(axes) != ["T", "X", "Y"]:
                continue
            info.variables.append(
                Variable(
                    name=name,
                    dims=list(var.dimensions),
                    shape=[int(s) for s in var.shape],
                    dtype=str(var.dtype),
                    units=_attr(var, "units"),
                    long_name=_attr(var, "long_name"),
                    standard_name=_attr(var, "standard_name"),
                )
            )
        if not info.variables:
            info.problem = _(
                "No variable with time, latitude and longitude dimensions was found, so "
                "this file holds no daily grid."
            )
            return info
        dims = info.variables[0].dims
        axes = {_axis(nc, d): d for d in dims}
        info.ny = len(nc.dimensions[axes["Y"]])
        info.nx = len(nc.dimensions[axes["X"]])
        info.y_range = _range(nc, axes["Y"])
        info.x_range = _range(nc, axes["X"])
        time = nc.variables.get(axes["T"])
        info.days = len(nc.dimensions[axes["T"]])
        if time is None:
            info.problem = _("The time dimension has no time variable, so its dates are unknown.")
            return info
        info.time_units = _attr(time, "units")
        info.calendar = _attr(time, "calendar") or "standard"
        if info.calendar.lower() not in SUPPORTED_CALENDARS:
            info.problem = _(
                "The %(calendar)s calendar is not supported. Climpact reads the standard, "
                "noleap (365_day) and 360_day calendars."
            ) % {"calendar": info.calendar}
            return info
        if info.days:
            try:
                ends = cftime.num2date(
                    [float(time[0]), float(time[-1])], info.time_units, info.calendar
                )
            except (ValueError, TypeError) as exc:
                info.problem = _("The time axis could not be read: %(error)s") % {"error": exc}
                return info
            info.first, info.last = (f"{d.year:04d}-{d.month:02d}-{d.day:02d}" for d in ends)
    return info


def guess_names(files: list[FileInfo]) -> dict[str, str]:
    """Which variable is TX, TN and precipitation: by name first (R's defaults, then
    common names), then by units and standard name. Empty where nothing fits."""
    variables = [v for f in files if f.ok for v in f.variables]
    names = {v.name for v in variables}
    lower = {v.name.lower(): v.name for v in variables}
    out = {}
    for role in ROLES:
        found = next((lower[g] for g in GUESSES[role] if g in lower), "")
        out[role] = found
    taken = {v for v in out.values() if v}
    # By attributes: precipitation units or standard name; temperatures by "max"/"min".
    for v in variables:
        if v.name in taken:
            continue
        text = f"{v.name} {v.long_name} {v.standard_name}".lower()
        if not out["pr"] and ("precip" in text or v.units.lower().startswith(("kg m-2", "mm"))):
            out["pr"] = v.name
        elif not out["tasmax"] and "max" in text and "temp" in text:
            out["tasmax"] = v.name
        elif not out["tasmin"] and "min" in text and "temp" in text:
            out["tasmin"] = v.name
        taken = {x for x in out.values() if x}
    return {role: (name if name in names else "") for role, name in out.items()}


def variable_choices(files: list[FileInfo]) -> list[tuple[str, str]]:
    """``(name, label)`` of every daily-grid variable, with its file and units."""
    out = []
    for f in files:
        if not f.ok:
            continue
        for v in f.variables:
            label = v.name
            details = [x for x in (v.long_name, v.units) if x]
            if details:
                label += f" ({', '.join(details)})"
            if len(files) > 1:
                label += f" · {f.name}"
            out.append((v.name, label))
    return out


def units_problem(role: str, units: str) -> str:
    """The core's unit check (``gridded.io.unit_conversion``) as a message, or ''."""
    from climpact.gridded.io import unit_conversion

    try:
        unit_conversion(role, units or None)
    except ValueError:
        if not units:
            return _("It has no units attribute, so Climpact cannot tell what its values mean.")
        if role == "pr":
            return _(
                "Its units, %(units)s, are not a precipitation rate Climpact reads "
                "(kg m-2 d-1, kg m-2 s-1 or mm/day)."
            ) % {"units": units}
        return _("Its units, %(units)s, are not a temperature Climpact reads (K or degrees_C).") % {
            "units": units
        }
    return ""


def find_variable(files: list[FileInfo], name: str) -> tuple[FileInfo, Variable] | None:
    for f in files:
        for v in f.variables:
            if v.name == name:
                return f, v
    return None


@dataclass
class Summary:
    """What the chosen variables make together: the grid, the period and the calendar."""

    ny: int = 0
    nx: int = 0
    first: str = ""
    last: str = ""
    days: int = 0
    calendar: str = ""
    y_range: list[float] = field(default_factory=list)
    x_range: list[float] = field(default_factory=list)

    @property
    def cells(self) -> int:
        return self.ny * self.nx

    @property
    def first_year(self) -> int | None:
        return int(self.first[:4]) if self.first else None

    @property
    def last_year(self) -> int | None:
        return int(self.last[:4]) if self.last else None


def check_names(files: list[FileInfo], names: dict[str, str]) -> tuple[dict[str, str], Summary]:
    """Problems with the chosen variables, by role (``{role: message}``), and what they
    make together. The rules are the core reader's (``open_grid``): each variable in one
    file, the same grid and the same time axis, units Climpact reads."""
    problems: dict[str, str] = {}
    summary = Summary()
    chosen = {}
    counts: dict[str, int] = {}
    for f in files:
        for v in f.variables:
            counts[v.name] = counts.get(v.name, 0) + 1
    for role in ROLES:
        name = names.get(role, "")
        if not name:
            problems[role] = _("Choose the variable.")
            continue
        found = find_variable(files, name)
        if found is None:
            problems[role] = _("No file has a daily grid variable named %(name)s.") % {"name": name}
            continue
        if counts.get(name, 0) > 1:
            problems[role] = _(
                "%(name)s is in more than one file; each variable must be in one."
            ) % {"name": name}
            continue
        message = units_problem(role, found[1].units)
        if message:
            problems[role] = message
            continue
        chosen[role] = found
    used = [names.get(r) for r in ROLES if names.get(r)]
    if len(set(used)) < len(used):
        for role in ROLES:
            if used.count(names.get(role)) > 1 and role not in problems:
                problems[role] = _("The same variable is chosen twice.")
    if not chosen:
        return problems, summary
    first_file, first_var = next(iter(chosen.values()))
    for role, (f, v) in chosen.items():
        if role in problems:
            continue
        if (f.ny, f.nx) != (first_file.ny, first_file.nx) or v.shape != first_var.shape:
            problems[role] = _("Its grid or number of days differs from %(name)s's.") % {
                "name": first_var.name
            }
        elif (f.first, f.last, f.calendar.lower()) != (
            first_file.first,
            first_file.last,
            first_file.calendar.lower(),
        ):
            problems[role] = _(
                "Its dates differ from %(name)s's; the files must share their time axis."
            ) % {"name": first_var.name}
    summary = Summary(
        ny=first_file.ny,
        nx=first_file.nx,
        first=first_file.first,
        last=first_file.last,
        days=first_file.days,
        calendar=first_file.calendar,
        y_range=first_file.y_range,
        x_range=first_file.x_range,
    )
    return problems, summary


def preflight(paths: list[str], names: dict[str, str], max_values: int) -> dict:
    """Open the files with the core's reader, as the run will: raises ``ValueError`` or
    ``NotImplementedError`` with the core's message when it would fail. Returns what the
    run needs to know: the number of blocks, whether the input will be rechunked to a
    temporary file and that file's size."""
    from climpact.gridded import open_grid

    inp = open_grid(paths, names=names, max_values=max_values)
    try:
        blocks = len(list(inp.blocks()))
        rechunk = inp.will_rechunk()
        size = inp.rechunk_bytes() if rechunk else 0
    finally:
        inp.data.close()
    return {"blocks": blocks, "rechunk": bool(rechunk), "rechunk_bytes": int(size)}


def free_bytes(folder: Path) -> int:
    try:
        stat = os.statvfs(folder)
    except (OSError, AttributeError):
        return 0
    return stat.f_bavail * stat.f_frsize


def human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size} B"  # pragma: no cover


def is_finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False

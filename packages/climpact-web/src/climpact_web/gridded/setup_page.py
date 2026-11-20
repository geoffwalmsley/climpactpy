"""What the set-up page shows besides the form (#293, the GridSetup board): the Variables
table (each variable's units and how Climpact reads them, a unit it cannot read with how
to convert it), the line of what the files make together, the base period's timeline and
coverage, the indices by the variable they need, the estimates (files, size, disk, time)
and the summary panel, which is the check: htmx swaps it in as the form changes, and the
page draws the same one without JavaScript.

Nothing here reads data: only the files' headers, coordinates and chunking, which
:func:`reading` keeps for the files as they are.
"""

from __future__ import annotations

import datetime as dt
import functools
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from climpact_web.core import numbers
from climpact_web.gridded import inspection, netcdf
from climpact_web.gridded.runs import short_duration, spacing

MINUS = "−"

ROLE_LABELS = {
    "tasmax": gettext_lazy("Maximum temperature (TX)"),
    "tasmin": gettext_lazy("Minimum temperature (TN)"),
    "pr": gettext_lazy("Precipitation"),
}
ROLE_SHORT = {
    "tasmax": gettext_lazy("TX"),
    "tasmin": gettext_lazy("TN"),
    "pr": gettext_lazy("Precipitation"),
}
# The variable groups of the Indices section, in the core's order (_BY_VARIABLE).
GROUP_LABELS = {
    "tmax": gettext_lazy("Max temperature"),
    "tmin": gettext_lazy("Min temperature"),
    "prec": gettext_lazy("Precipitation"),
    "tavg": gettext_lazy("Both temperatures"),
}
# The numbered indices' parameters, as the board names them: (field, code, unit).
PARAMS = (
    ("wsdi_days", "WSDId", gettext_lazy("days")),
    ("csdi_days", "CSDId", gettext_lazy("days")),
    ("rx_days", "Rxdday", gettext_lazy("days")),
    ("txtn_days", "TXdTNd", gettext_lazy("days")),
    ("rnnmm", "Rnnmm", "mm"),
    ("hdd_base", "HDDheatn", "°C"),
    ("cdd_base", "CDDcoldn", "°C"),
    ("gdd_base", "GDDgrown", "°C"),
)


# ---- Variables -----------------------------------------------------------------------------


def read_as(role: str, units: str) -> str:
    """How Climpact reads a variable in ``units`` (``gridded.io.unit_conversion``), as the
    Variables table writes it: ``°C (K − 273.15)``, ``mm/day (× 86400)``, or ``°C`` and
    ``mm/day`` when the values are read as they are; "" when it cannot read them."""
    from climpact.gridded.io import unit_conversion

    try:
        scale, offset = unit_conversion(role, units or None)
    except ValueError:
        return ""
    if role in ("tasmax", "tasmin"):
        return f"°C (K {MINUS} 273.15)" if offset else "°C"
    if scale != 1:
        return f"mm/day (× {int(scale)})"
    return "mm/day"


# Precipitation units Climpact does not read but CDO can convert, with the factor that
# makes them mm/day: ERA5's tp (the day's total in metres) and an hourly rate.
_METRES = {"m", "metre", "metres", "meter", "meters", "m of water equivalent"}
_PER_HOUR = {
    "mm/h",
    "mm/hr",
    "mm h-1",
    "mm hr-1",
    "mm/hour",
    "kg m-2 h-1",
    "kg m-2 hr-1",
    "kg m^-2 h^-1",
    "kg/m2/h",
    "kg/m2/hr",
}


@dataclass
class UnitsHelp:
    """How to convert a variable Climpact cannot read: the explanation and, for the common
    cases, a CDO command."""

    lead: str
    text: str
    command: str = ""
    output: str = ""
    files: int = 1  # the files the command reads


def _inputs(files: list[inspection.FileInfo]) -> str:
    """The input of the CDO command: the file, or the files of a variable split across
    several joined with ``-mergetime`` (a quoted pattern of their common start)."""
    names = [f.name for f in files]
    if len(names) == 1:
        return shlex.quote(names[0])
    prefix = os.path.commonprefix(names)
    pattern = f"{prefix}*.nc" if prefix else "*.nc"
    return f"-mergetime {shlex.quote(pattern)}"


def units_help(role: str, variable: str, units: str, files) -> UnitsHelp:
    """What Climpact reads for ``role`` and how to convert ``variable`` (in ``units``,
    held by ``files``) to it."""
    unit = " ".join((units or "").split()).lower()
    if role == "pr":
        lead = (
            _("Precipitation: the variable %(name)s has no units attribute.") % {"name": variable}
            if not units
            else _("Precipitation: Climpact cannot read the units %(units)s.") % {"units": units}
        )
        reads = _("It reads a daily rate: kg m-2 d-1, kg m-2 s-1 or mm/day.")
        output = "pr_mm.nc"
        factor = ""
        if unit in _METRES:
            factor = "1000"
            why = _(
                "In metres, as ERA5's tp, the values are the day's total in metres of water, "
                "so multiply by 1000 and call it mm/day. With CDO:"
            )
        elif unit in _PER_HOUR:
            factor = "24"
            why = _(
                "An hourly rate is a twenty-fourth of the day's total, so multiply by 24 "
                "and call it mm/day. With CDO:"
            )
        if factor:
            command = (
                f"cdo -setattribute,{variable}@units=mm/day -mulc,{factor} "
                f"{_inputs(files)} {output}"
            )
            return UnitsHelp(lead, f"{reads} {why}", command, output, len(files))
        return UnitsHelp(
            lead,
            f"{reads} "
            + _(
                "Convert the values to one of these and set the variable's units attribute "
                "to match, with CDO or NCO, then choose the new file."
            ),
        )
    label = ROLE_LABELS[role]
    lead = (
        _("%(role)s: the variable %(name)s has no units attribute.")
        % {"role": label, "name": variable}
        if not units
        else _("%(role)s: Climpact cannot read the units %(units)s.")
        % {"role": label, "units": units}
    )
    return UnitsHelp(
        lead,
        _(
            "It reads K or degrees_C. Convert the values to one of these and set the "
            "variable's units attribute to match, with CDO or NCO, then choose the new file."
        ),
    )


@dataclass
class VariableRow:
    role: str
    label: str
    name: str  # the variable chosen
    units: str
    read_as: str
    ok: bool
    check: str  # the Check column's word
    problem: str = ""  # the message, when not ok
    help: UnitsHelp | None = None  # how to convert, for a unit Climpact cannot read
    field: object = None  # the form's select


def variable_rows(infos, names: dict, problems: dict) -> list[VariableRow]:
    """A row of the Variables table for each of TX, TN and precipitation."""
    rows = []
    for role in inspection.ROLES:
        name = names.get(role, "")
        found = inspection.holders(infos, name) if name else []
        units = found[0][1].units if found else ""
        problem = problems.get(role, "")
        help_ = None
        if not problem:
            check = _("Readable")
        elif found and inspection.units_problem(role, units):
            check = _("Units")
            help_ = units_help(role, name, units, [f for f, _v in found])
        elif not name:
            check = _("Not chosen")
        else:
            check = _("Not usable")
        rows.append(
            VariableRow(
                role=role,
                label=str(ROLE_LABELS[role]),
                name=name,
                units=units,
                read_as=read_as(role, units) if found else "",
                ok=not problem,
                check=check,
                problem=problem,
                help=help_,
            )
        )
    return rows


def _latitude(value: float) -> str:
    return numbers.coordinate(value, "N")


def _longitude(value: float) -> str:
    return numbers.coordinate(value, "E")


def together(summary: inspection.Summary, rows: list[VariableRow]) -> list[str]:
    """The Variables section's last line: the grid, its bounds, the period and days, the
    calendar, and that every file has the same grid and time axis."""
    if not summary.ny:
        return []
    grid = _("Together: %(ny)s × %(nx)s cells") % {"ny": summary.ny, "nx": summary.nx}
    if len(summary.y_range) == 2 and len(summary.x_range) == 2:
        grid += ", " + _("%(south)s to %(north)s, %(west)s to %(east)s") % {
            "south": _latitude(summary.y_range[0]),
            "north": _latitude(summary.y_range[1]),
            "west": _longitude(summary.x_range[0]),
            "east": _longitude(summary.x_range[1]),
        }
    parts = [
        grid,
        _("%(first)s to %(last)s, %(days)s days")
        % {"first": summary.first, "last": summary.last, "days": numbers.grouped(summary.days)},
        _("%(calendar)s calendar") % {"calendar": summary.calendar},
    ]
    if all(r.ok for r in rows):
        parts.append(_("same grid and time axis in every file ✓"))
    return parts


# ---- Base period ---------------------------------------------------------------------------


def period_days(calendar: str, start: int, end: int) -> int:
    """The days of the years ``start`` to ``end`` in ``calendar``."""
    if start > end:
        return 0
    calendar = (calendar or "standard").lower()
    if calendar == "360_day":
        return 360 * (end - start + 1)
    if calendar in ("noleap", "365_day"):
        return 365 * (end - start + 1)
    return (dt.date(end, 12, 31) - dt.date(start, 1, 1)).days + 1


@dataclass
class Timeline:
    """The data's years with the base period marked (an SVG drawn with percentages, so it
    needs no style attribute)."""

    first: int
    last: int
    start: int
    end: int

    def _at(self, year: float) -> float:
        span = self.last + 1 - self.first
        return round(100 * min(max(year - self.first, 0), span) / span, 2)

    @property
    def x(self) -> float:
        return self._at(self.start)

    @property
    def width(self) -> float:
        return max(0.0, round(self._at(self.end + 1) - self._at(self.start), 2))

    @property
    def start_mid(self) -> float:
        return self._at(self.start + 0.5)

    @property
    def end_mid(self) -> float:
        return self._at(self.end + 0.5)

    @property
    def inside(self) -> bool:
        return self.width > 0


def timeline(summary: inspection.Summary, start, end) -> Timeline | None:
    if summary.first_year is None or start is None or end is None or start > end:
        return None
    return Timeline(summary.first_year, summary.last_year, start, end)


@dataclass
class Coverage:
    days: int  # of the base period in the data
    total: int  # days in the base period
    minimum: int
    start: int
    end: int
    from_file: bool = False

    @property
    def enough(self) -> bool:
        return self.from_file or self.days >= self.minimum

    @property
    def all(self) -> bool:
        return self.days >= self.total

    @property
    def reference(self) -> bool:
        return (self.start, self.end) == (1971, 2000)


def coverage(summary, start, end, minimum: int, from_file: bool) -> Coverage | None:
    from climpact_web.gridded.views import base_days

    if not summary.first or start is None or end is None or start > end:
        return None
    return Coverage(
        days=base_days(summary, start, end),
        total=period_days(summary.calendar, start, end),
        minimum=minimum,
        start=start,
        end=end,
        from_file=from_file,
    )


# ---- Indices -------------------------------------------------------------------------------


def index_groups(form) -> list[dict]:
    """The indices in four columns by the variable they need, each a checkbox with the
    code and the short name; "slow" on the heatwaves, SPI and SPEI."""
    from climpact.gridded.indices import _BY_VARIABLE
    from climpact_web.gridded.forms import SLOW_INDICES
    from climpact_web.help.indices import index_for_output
    from climpact_web.stations.results import display_name, short_name

    chosen = set(form["indices"].value() or [])
    groups = []
    for var, (_label, items) in zip(_BY_VARIABLE, form.fields["indices"].choices, strict=True):
        rows = []
        for value, text in items:
            info = index_for_output(value)
            code = display_name(value, info)
            if " " in code:  # "EHF heatwaves": the code as the board writes it
                code = value.upper()
            rows.append(
                {
                    "value": value,
                    "code": code,
                    "name": short_name(value, info) if info else text,
                    "checked": value in chosen,
                    "slow": value in SLOW_INDICES,
                }
            )
        groups.append({"key": var, "label": str(GROUP_LABELS.get(var, _label)), "items": rows})
    return groups


# ---- Estimates -----------------------------------------------------------------------------

# Seconds per cell and year of data on one core, measured on a tiled sample grid (#293):
# every index, about 0.3 s a cell for 20 years; without the heatwaves, SPI and SPEI about
# 15% less; a thresholds file, 0.01 s a cell for 20 years.
INDICES_SECONDS = 0.015
THRESHOLDS_SECONDS = 0.0005
FAST_SHARE = 0.85
FILE_OVERHEAD = 32 * 1024  # an index file's coordinates, time axis and attributes
TRENDS_VALUES = 8  # values per cell and annual index in trends.nc


@dataclass
class Estimate:
    index_files: int = 0
    indices: int = 0
    index_bytes: int = 0
    thresholds_bytes: int = 0
    seconds: float = 0.0
    rechunk_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        return self.index_bytes + self.thresholds_bytes


def _steps(summary: inspection.Summary) -> tuple[int, int]:
    """Years and months of the data."""
    if summary.first_year is None:
        return 0, 0
    years = summary.last_year - summary.first_year + 1
    return years, 12 * years


def estimate(form_data: dict, summary: inspection.Summary, specs, workers: int) -> Estimate:
    """Files, size (as written, before compression) and time of the run, from the
    indices chosen, the grid and the time steps."""
    from climpact_web.gridded.forms import SLOW_INDICES

    task = form_data.get("task") or "indices"
    cells = summary.cells
    years, months = _steps(summary)
    out = Estimate()
    if task in ("indices", "both") and specs:
        out.index_files = len(specs)
        out.indices = len({s.index for s in specs})
        size = 0
        for s in specs:
            steps = years if s.freq == "ANN" else months if s.freq == "MON" else summary.days
            per_value = len(s.variables) * (3 if s.scaled else 1) + (1 if s.dated else 0)
            size += cells * steps * 4 * per_value + FILE_OVERHEAD
        annual = sum(1 for s in specs if s.freq == "ANN")
        size += cells * annual * TRENDS_VALUES * 4 + FILE_OVERHEAD
        out.index_bytes = size
        share = 1.0 if any(s.index in SLOW_INDICES for s in specs) else FAST_SHARE
        out.seconds += INDICES_SECONDS * cells * years * share
    if task in ("thresholds", "both"):
        start, end = form_data.get("base_start"), form_data.get("base_end")
        base = 0
        if isinstance(start, int) and isinstance(end, int) and start <= end:
            from climpact_web.gridded.views import base_days

            base = base_days(summary, start, end)
        out.thresholds_bytes = (13 * 365 + 5 + 3 * base) * cells * 8 + FILE_OVERHEAD
        out.seconds += THRESHOLDS_SECONDS * cells * years
    out.seconds /= max(1, workers)
    return out


def size_text(size: float) -> str:
    """``1.3 GB``, ``40 MB``: one decimal under 10, none above."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            if unit == "B":
                return numbers.with_unit(numbers.grouped(int(size)), unit)
            decimals = 1 if size < 10 else 0
            return numbers.with_unit(numbers.fixed(size, decimals), unit)
        size /= 1000
    return ""  # pragma: no cover


@functools.lru_cache(maxsize=32)
def _reading(paths: tuple, names: tuple, stamps: tuple) -> tuple[float, int] | None:
    from climpact.gridded import open_grid

    with netcdf.LOCK:  # the core's reader opens the files on this request's thread
        try:
            inp = open_grid(list(paths), names=dict(names))
        except (ValueError, NotImplementedError, OSError, KeyError):
            return None
        try:
            return float(inp.read_amplification()), int(inp.rechunk_bytes())
        except (ValueError, NotImplementedError, OSError, KeyError):
            return None
        finally:
            inp.data.close()


def reading(paths: list[str], names: dict) -> tuple[float, int] | None:
    """How many times over reading the blocks straight from the files decompresses them
    (``GriddedInput.read_amplification``) and the size of a cell-first copy, from the
    core's reader; ``None`` when it cannot open them. Kept while the files are the same."""
    stamps = []
    for path in paths:
        try:
            stat = Path(path).stat()
        except OSError:
            return None
        stamps.append((stat.st_size, stat.st_mtime_ns))
    return _reading(tuple(paths), tuple(sorted(names.items())), tuple(stamps))


def will_rechunk(choice: str, amplification: float | None) -> bool:
    from climpact.gridded.io import RECHUNK_AMPLIFICATION

    if choice == "yes":
        return True
    if choice == "no" or amplification is None:
        return False
    return amplification >= RECHUNK_AMPLIFICATION


# ---- The summary panel ---------------------------------------------------------------------


@dataclass
class Item:
    mark: str  # "ok", "bad", "info", "about", "note"
    title: str
    text: str
    href: str = ""  # a problem's field


@dataclass
class Panel:
    title: str
    items: list[Item] = field(default_factory=list)
    problems: list[Item] = field(default_factory=list)
    button: str = ""
    foot: str = ""
    error: str = ""  # the final check's message, or why a new start failed

    @property
    def problem_links(self) -> str:
        """The problems as links to their fields, "a, b" (safe HTML)."""
        from django.utils.html import format_html_join

        return format_html_join(
            _(", "), '<a href="{}">{}</a>', ((p["href"], p["label"]) for p in self.problems)
        )


def grid_item(summary: inspection.Summary, file_count: int) -> Item:
    step = spacing(summary)
    if step:
        text = ngettext(
            "%(ny)s × %(nx)s cells at %(step)s, in %(count)s file.",
            "%(ny)s × %(nx)s cells at %(step)s, the same in all %(count)s files.",
            file_count,
        )
    else:
        text = ngettext(
            "%(ny)s × %(nx)s cells, in %(count)s file.",
            "%(ny)s × %(nx)s cells, the same in all %(count)s files.",
            file_count,
        )
    return Item(
        "ok",
        _("Grid"),
        text % {"ny": summary.ny, "nx": summary.nx, "step": step, "count": file_count},
    )


def variables_item(rows: list[VariableRow]) -> Item:
    bad = [r for r in rows if not r.ok]
    if bad:
        first = bad[0]
        if first.help is not None:
            text = _("%(role)s’s units, %(units)s, cannot be read.") % {
                "role": ROLE_SHORT[first.role],
                "units": first.units or _("none"),
            }
        else:
            text = f"{ROLE_SHORT[first.role]}: {first.problem}"
        return Item("bad", _("Variables"), text, f"#id_{first.role}")
    temps = {r.units for r in rows if r.role != "pr"}
    pr = next(r for r in rows if r.role == "pr")
    if len(temps) == 1:
        text = _("TX and TN in %(t)s, precipitation in %(p)s; converted as shown.") % {
            "t": temps.pop() or "–",
            "p": pr.units,
        }
    else:
        tx, tn = rows[0].units, rows[1].units
        text = _("TX in %(tx)s, TN in %(tn)s, precipitation in %(p)s; converted as shown.") % {
            "tx": tx,
            "tn": tn,
            "p": pr.units,
        }
    return Item("ok", _("Variables"), text)


def base_item(cov: Coverage | None, form) -> Item:
    if cov is None:
        return Item("bad", _("Base period"), _("Enter the first and last year."), "#id_base_start")
    years = f"{cov.start}–{cov.end}"
    if cov.from_file:
        return Item(
            "ok",
            _("Base period"),
            _("%(years)s: the thresholds are read from the file.") % {"years": years},
        )
    if not cov.enough:
        return Item(
            "bad",
            _("Base period"),
            _("%(years)s: %(days)s days in the data; at least %(min)s are needed.")
            % {"years": years, "days": numbers.grouped(cov.days), "min": cov.minimum},
            "#id_base_start",
        )
    if cov.all:
        text = _("%(years)s: all %(days)s days in the data.") % {
            "years": years,
            "days": numbers.grouped(cov.total),
        }
    else:
        text = _("%(years)s: %(days)s of its %(total)s days in the data.") % {
            "years": years,
            "days": numbers.grouped(cov.days),
            "total": numbers.grouped(cov.total),
        }
    return Item("ok", _("Base period"), text)


def writes_item(task: str, est: Estimate) -> Item:
    thresholds = size_text(est.thresholds_bytes)
    indices = size_text(est.index_bytes)
    files = ngettext("%(count)s file", "%(count)s files", est.index_files) % {
        "count": est.index_files
    }
    count = ngettext("%(count)s index", "%(count)s indices", est.indices) % {"count": est.indices}
    if task == "thresholds":
        text = _("1 thresholds file, up to about %(size)s.") % {"size": thresholds}
    elif task == "both":
        text = _(
            "A thresholds file (up to about %(tsize)s), then %(files)s for %(count)s and "
            "trends.nc (up to about %(size)s)."
        ) % {"tsize": thresholds, "files": files, "count": count, "size": indices}
    else:
        text = _("%(files)s for %(count)s and trends.nc, up to about %(size)s.") % {
            "files": files,
            "count": count,
            "size": indices,
        }
    if task != "thresholds" and not est.index_files:
        return Item("bad", _("Writes"), _("No index is chosen."), "#indices-title")
    return Item("ok", _("Writes"), text)


def disk_item(est: Estimate, rechunk: bool, folder: Path) -> Item | None:
    while not folder.exists() and folder.parent != folder:  # not made until a run writes
        folder = folder.parent
    free = inspection.free_bytes(folder)
    if not free:
        return None
    need = est.total_bytes + (est.rechunk_bytes if rechunk else 0)
    if rechunk:
        text = _("Needs up to about %(need)s with the temporary copy; %(free)s free.")
    else:
        text = _("Needs up to about %(need)s; %(free)s free.")
    text %= {"need": size_text(need), "free": size_text(free)}
    return Item("ok" if need < 0.9 * free else "bad", _("Disk"), text)


def rechunk_item(est: Estimate) -> Item:
    return Item(
        "info",
        _("Cell-first copy"),
        _(
            "The files are chunked by time step, so they are copied cell first before the "
            "run (%(size)s, deleted after)."
        )
        % {"size": size_text(est.rechunk_bytes)},
    )


def time_item(est: Estimate, workers: int) -> Item:
    if est.seconds < 60:
        text = ngettext(
            "Under a minute on %(count)s core.", "Under a minute on %(count)s cores.", workers
        ) % {"count": workers}
    else:
        text = ngettext(
            "About %(time)s on %(count)s core.", "About %(time)s on %(count)s cores.", workers
        ) % {"time": short_duration(dt.timedelta(seconds=est.seconds)), "count": workers}
    return Item("about", _("Time"), text)


# ---- A file's header -----------------------------------------------------------------------

_CDL_TYPES = {
    "f8": "double",
    "f4": "float",
    "i8": "int64",
    "i4": "int",
    "i2": "short",
    "i1": "byte",
    "u8": "uint64",
    "u4": "uint",
    "u2": "ushort",
    "u1": "ubyte",
    "S1": "char",
}
_CDL_SUFFIX = {"f4": "f", "i2": "s", "i1": "b", "i8": "L", "u1": "UB", "u2": "US", "u4": "U"}


def _cdl_type(dtype) -> str:
    if dtype is str:
        return "string"
    key = f"{dtype.kind}{dtype.itemsize}"
    return _CDL_TYPES.get(key, str(dtype))


def _cdl_value(value) -> str:
    import numpy as np

    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    array = np.atleast_1d(np.asarray(value))
    if array.dtype.kind in "SU":
        return ", ".join(_cdl_value(str(v)) for v in array)
    suffix = _CDL_SUFFIX.get(f"{array.dtype.kind}{array.dtype.itemsize}", "")
    if array.dtype.kind == "f":
        items = [f"{float(v):g}" for v in array]
    else:
        items = [str(int(v)) for v in array]
    return ", ".join(f"{item}{suffix}" for item in items)


def header_text(path: str | Path) -> str:
    """The file's header as ``ncdump -h`` prints it: dimensions, variables and their
    attributes, the global attributes."""
    path = Path(path)
    lines = [f"netcdf {path.stem} {{", "dimensions:"]
    with netcdf.dataset(path) as nc:
        for name, dim in nc.dimensions.items():
            if dim.isunlimited():
                lines.append(f"\t{name} = UNLIMITED ; // ({len(dim)} currently)")
            else:
                lines.append(f"\t{name} = {len(dim)} ;")
        lines.append("variables:")
        for name, var in nc.variables.items():
            dims = ", ".join(var.dimensions)
            lines.append(f"\t{_cdl_type(var.dtype)} {name}({dims}) ;")
            for attr in var.ncattrs():
                lines.append(f"\t\t{name}:{attr} = {_cdl_value(var.getncattr(attr))} ;")
        attrs = nc.ncattrs()
        if attrs:
            lines.extend(["", "// global attributes:"])
            for attr in attrs:
                lines.append(f"\t\t:{attr} = {_cdl_value(nc.getncattr(attr))} ;")
        if nc.groups:
            lines.extend(["", "// groups: " + ", ".join(nc.groups)])
    lines.append("}")
    return "\n".join(lines) + "\n"


# ---- The page ------------------------------------------------------------------------------

SECTIONS = (
    (("tasmax", "tasmin", "pr"), gettext_lazy("Variables")),
    (
        ("task", "thresholds_source", "thresholds_path", "thresholds_upload"),
        gettext_lazy("What to calculate"),
    ),
    (("base_start", "base_end"), gettext_lazy("Base period")),
    (("indices", *(name for name, _c, _u in PARAMS)), gettext_lazy("Indices")),
    (
        ("template", "thresholds_name", "institution", "institution_id", "copy_to"),
        gettext_lazy("Output files"),
    ),
    (("workers", "max_values", "rechunk", "tmp_dir"), gettext_lazy("Computing")),
)


def value(form, name: str):
    """A field's value as the page shows it: cleaned when valid, else as typed."""
    data = getattr(form, "cleaned_data", None)
    if data is not None and name in data:
        return data[name]
    if name not in form.fields:
        return None
    raw = form[name].value()
    if name in ("base_start", "base_end", "workers"):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return raw


def changed(form, run) -> list[str]:
    """The sections whose settings differ from those of the results shown."""
    if not form.is_bound or not run.options:
        return []
    saved = {**run.options, **run.names}
    out = []
    for names, label in SECTIONS:
        for name in names:
            if name not in form.fields or name == "thresholds_upload":
                continue
            now, then = value(form, name), saved.get(name)
            if name == "indices":
                now, then = sorted(now or []), sorted(then or [])
            elif isinstance(then, (int, float)) and not isinstance(then, bool):
                try:
                    now = type(then)(now)
                except (TypeError, ValueError):
                    pass
            if (now or "") != (then or ""):
                out.append(str(label))
                break
    return out


def computing_line(form, will_copy: bool, cores: int | None) -> list[str]:
    """The closed Computing disclosure's summary: cores, values at once, cell-first copy."""
    parts = []
    workers = value(form, "workers")
    if cores and workers:
        parts.append(_("%(n)s of %(cores)s cores") % {"n": workers, "cores": cores})
    max_values = value(form, "max_values")
    if max_values not in (None, ""):
        try:
            parts.append(_("%(n)s M values at once") % {"n": numbers.number(float(max_values))})
        except (TypeError, ValueError):
            pass
    choice = value(form, "rechunk") or "auto"
    words = {"auto": _("automatic"), "yes": _("always"), "no": _("never")}
    parts.append(_("cell-first copy: %(choice)s") % {"choice": words.get(choice, choice)})
    return parts


def _finished(run):
    jobs = run.jobs
    started = min((j.started_at for j in jobs if j.started_at), default=None)
    finished = max((j.finished_at for j in jobs if j.finished_at), default=None)
    return started, finished


def _when(value_: dt.datetime) -> str:
    from django.utils import dateformat, timezone

    return dateformat.format(timezone.localtime(value_), "j M Y, H:i")


def done_items(run) -> list[Item]:
    """What the results shown are: when they were calculated, and what was written."""
    from climpact_web.gridded import runs

    items = []
    started, finished = _finished(run)
    workers = run.options.get("workers") or 1
    if finished:
        took = short_duration(finished - started) if started else ""
        cores = ngettext("%(count)s core", "%(count)s cores", workers) % {"count": workers}
        text = (
            _("%(when)s, in %(took)s on %(cores)s.")
            % {"when": _when(finished), "took": took, "cores": cores}
            if took
            else _("%(when)s.") % {"when": _when(finished)}
        )
        items.append(Item("ok", _("Calculated"), text))
    files = runs.index_files(run)
    size = size_text(runs.total_size(run))
    if files:
        indices = len({f.index for f in files})
        text = ngettext("%(count)s file", "%(count)s files", len(files)) % {"count": len(files)}
        text = _("%(files)s for %(count)s, %(size)s.") % {
            "files": text,
            "count": ngettext("%(count)s index", "%(count)s indices", indices) % {"count": indices},
            "size": size,
        }
    else:
        text = _("A thresholds file, %(size)s.") % {"size": size}
    items.append(Item("ok", _("Wrote"), text))
    items.append(
        Item(
            "note",
            _("Settings"),
            _("Saved with the run as run.json, and in every file’s attributes."),
        )
    )
    return items


def _kept_date() -> str:
    from django.conf import settings
    from django.utils import dateformat, timezone

    later = timezone.now() + dt.timedelta(days=settings.JOB_RETENTION_DAYS)
    return dateformat.format(timezone.localtime(later), "j M Y")


def problem_links(rows: list[VariableRow], items: list[Item], form) -> list[dict]:
    """What stops the run, each linked to its field: the variables, then the checks that
    failed, then the form's other errors."""
    links = []
    for row in rows:
        if row.ok:
            continue
        if row.help is not None:
            role = ROLE_LABELS["pr"] if row.role == "pr" else ROLE_SHORT[row.role]
            label = _("%(role)s units") % {"role": role}
        else:
            label = str(ROLE_LABELS[row.role])
        links.append({"label": label, "href": f"#id_{row.role}"})
    links += [
        {"label": i.title, "href": i.href or "#"}
        for i in items
        if i.mark == "bad" and i.title != _("Variables")
    ]
    covered = {*inspection.ROLES, "base_start", "base_end", "indices"}
    if form.is_bound:
        for name in form.errors:
            if name not in covered and name in form.fields:
                label = str(form.fields[name].label)
                links.append({"label": label, "href": f"#id_{name}"})
    return links


def _job_error(jobs) -> str:
    failed = next((j for j in jobs if j.status in ("failed", "cancelled")), None)
    if failed is None:
        return ""
    if failed.status == "cancelled":
        return _("It was cancelled.")
    return failed.error or _("It failed.")


def panel_for(run, form, items: list[Item], links: list[dict]) -> Panel:
    """The summary panel: the checks before a run (or after one that failed); what the
    results are after one, with what has changed since; or the state while one runs."""
    from climpact_web.gridded import runs

    if run.restarting:
        _started, finished = _finished(run)
        return Panel(
            _("Calculating again"),
            items=[
                Item("about", _("State"), runs.state(run, run.next_jobs).text + "."),
                Item(
                    "note",
                    _("Results"),
                    _(
                        "Map and Files show the run of %(when)s until this one has finished, "
                        "then its results."
                    )
                    % {"when": _when(finished) if finished else "–"},
                ),
            ],
        )
    state = runs.state(run)
    if state.active:
        return Panel(_("Calculating"), items=[Item("about", _("State"), state.text + ".")])
    if runs.all_done(run):
        items_done = done_items(run)
        what = changed(form, run)
        if what:
            items_done.append(Item("note", _("Changed:"), ", ".join(what) + "."))
        else:
            items_done.append(
                Item("note", _("Nothing changed yet."), _("Change a setting above to start again."))
            )
        error = _job_error(run.next_jobs)
        if error:
            error = _(
                "The last start did not finish. %(error)s Map and Files still show the run "
                "before it."
            ) % {"error": error}
        return Panel(
            _("This run"),
            items=items_done + [i for i in items if i.mark == "bad"],
            problems=links,
            button=_("Start again with changes"),
            foot=_(
                "The results on Map and Files stay until the new run finishes, then are "
                "replaced. To keep both, download these first or start a new run."
            ),
            error=error,
        )
    error = _job_error(run.jobs)
    if error:
        error = _("The last run did not finish. %(error)s") % {"error": error}
    if links:
        foot = _("Start checks again and stops at the problem.")
    else:
        foot = _(
            "It runs in the background: you can close this page. The run is listed on "
            "Gridded until %(date)s."
        ) % {"date": _kept_date()}
    return Panel(
        _("Before you start") if links else _("Ready to start"),
        items=items,
        problems=links,
        button=_("Start again") if run.jobs else _("Start the calculation"),
        foot=foot,
        error=error,
    )


def build(
    run,
    form,
    infos,
    problems,
    summary,
    outputs,
    *,
    local: bool,
    folder: Path,
    cores: int | None,
    preflight_error: str = "",
) -> dict:
    """Everything the set-up page draws from the form: the Variables rows, the Together
    line, the base period's timeline and coverage, the indices, the Computing line and the
    summary panel."""
    from climpact_web.gridded import runs
    from climpact_web.gridded.forms import MIN_BASE_DAYS

    rows = variable_rows(infos, {r: value(form, r) or "" for r in inspection.ROLES}, problems)
    for row in rows:
        row.field = form[row.role]
    ready = all(r.ok for r in rows)
    task = value(form, "task") or "indices"
    from_file = task == "indices" and value(form, "thresholds_source") == "file"
    start, end = value(form, "base_start"), value(form, "base_end")
    cov = coverage(summary, start, end, MIN_BASE_DAYS + 1, from_file)
    workers = (value(form, "workers") if "workers" in form.fields else 1) or 1
    est = estimate(
        {"task": task, "base_start": start, "base_end": end},
        summary,
        outputs.get("specs") or [],
        workers,
    )
    found = reading(run.paths, {r.role: r.name for r in rows}) if ready else None
    copy = will_rechunk(value(form, "rechunk") or "auto", found[0] if found else None)
    if found and copy:
        est.rechunk_bytes = found[1]

    # The checks, in the board's order.
    items: list[Item] = []
    if summary.ny:
        items.append(grid_item(summary, len(infos)))
        period = _("%(years)s, %(days)s days, %(calendar)s calendar.") % {
            "years": runs.period_text(summary),
            "days": numbers.grouped(summary.days),
            "calendar": summary.calendar,
        }
        items.append(Item("ok", _("Period"), period))
    items.append(variables_item(rows))
    items.append(base_item(cov, form))
    items.append(writes_item(task, est))
    if local and (disk := disk_item(est, copy, folder)) is not None:
        items.append(disk)
    if copy and est.rechunk_bytes:
        items.append(rechunk_item(est))
    items.append(time_item(est, workers))

    panel = panel_for(run, form, items, problem_links(rows, items, form))
    if preflight_error:
        panel.error = preflight_error
    choices = form.fields["indices"].choices
    return {
        "variable_rows": rows,
        "units_helps": [r for r in rows if r.help is not None],
        "together": together(summary, rows),
        "timeline": timeline(summary, start, end),
        "coverage": cov,
        "index_groups": index_groups(form),
        "index_total": sum(len(items) for _label, items in choices),
        "index_chosen": len(value(form, "indices") or []),
        "params": [
            {"field": form[name], "code": code, "unit": unit}
            for name, code, unit in PARAMS
            if name in form.fields
        ],
        "estimate": est,
        "computing": computing_line(form, copy, cores),
        "panel": panel,
        "task": task,
    }

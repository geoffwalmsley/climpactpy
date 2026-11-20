"""A gridded run as a place of its own (#289, the GridList and GridFiles boards): its
default name, the row it has on Gridded, its context bar's provenance line, its Files tab
(the index files grouped by theme, variable needed or frequency) and its record
(``run.json`` and the log).

Everything here reads what the run already holds (the files' inspection, the options,
the jobs and their output folders); only :func:`cells_with_data` and :func:`checksums`
read data, once, and keep what they found in the run's options.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.utils import dateformat, timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from climpact_web.core import numbers
from climpact_web.gridded import inspection, maps, netcdf
from climpact_web.gridded.models import GriddedRun, Source
from climpact_web.jobs.models import Status

DASH = "–"
# Words dropped from a file name when a run is named after it: the variables (the guessed
# names, ERA5's and the run's chosen ones), the frequency and the dates say nothing about
# which grid it is.
NAME_NOISE = {"day", "daily", "nc", "netcdf", "tas", "mx2t", "mn2t", "t2m"} | {
    name for names in inspection.GUESSES.values() for name in names
}
DATES = re.compile(r"^\d{4,8}(-\d{4,8})?$")


# ---- The grid ------------------------------------------------------------------------------


def grid_summary(run: GriddedRun) -> inspection.Summary:
    """The grid and period of the run's chosen variables, or of its first readable file."""
    infos = run.file_infos()
    _problems, summary = inspection.check_names(infos, run.names)
    if not summary.ny:
        first = next((f for f in infos if f.ok), None)
        if first is not None:
            summary = inspection.Summary(
                ny=first.ny,
                nx=first.nx,
                first=first.first,
                last=first.last,
                days=first.days,
                calendar=first.calendar,
                y_range=first.y_range,
                x_range=first.x_range,
            )
    return summary


def _step(values: list[float], count: int) -> float | None:
    if len(values) != 2 or count < 2:
        return None
    return abs(values[1] - values[0]) / (count - 1)


def _degrees(step: float) -> str:
    return f"{numbers.number(round(step, 3), 3)}°"


def spacing(summary: inspection.Summary) -> str:
    """The grid's spacing, ``0.25°`` (or ``1.25° × 1.875°`` when latitude and longitude
    differ), from the coordinates' range; "" when it cannot be told."""
    dy, dx = _step(summary.y_range, summary.ny), _step(summary.x_range, summary.nx)
    if not dy or not dx:
        return ""
    if abs(dy - dx) <= 0.001 * max(dy, dx):
        return _degrees(dy)
    return f"{_degrees(dy)} × {_degrees(dx)}"


def period_text(summary: inspection.Summary) -> str:
    if summary.first_year is None:
        return DASH
    return f"{summary.first_year}–{summary.last_year}"


def grid_text(summary: inspection.Summary) -> str:
    """The Grid column: ``47 × 55, 0.25°`` (rows by columns, and the spacing)."""
    if not summary.ny:
        return DASH
    text = f"{summary.ny} × {summary.nx}"
    step = spacing(summary)
    return f"{text}, {step}" if step else text


def default_name(run: GriddedRun) -> str:
    """A run's name until it is given one (#289): what its files are called, without
    the variable names and dates, then the spacing and the period
    (``era5 SEA 0.25°, 1961–2020``); the sample grid is "Sample grid"."""
    summary = grid_summary(run)
    if run.source == Source.SAMPLE:
        label = _("Sample grid")
    else:
        stems = [Path(f["name"]).stem for f in run.files] or [str(run.pk)[:8]]
        noise = NAME_NOISE | {name.lower() for name in (run.names or {}).values() if name}
        words = []
        for word in re.split(r"[_\s]+", stems[0]):
            parts = [p for p in word.split(".") if p]
            parts = [p for p in parts if p.lower() not in noise and not DATES.match(p)]
            if parts:
                words.append(".".join(parts))
        label = " ".join(words) or stems[0]
    step = spacing(summary)
    name = f"{label} {step}" if step and run.source != Source.SAMPLE else label
    if summary.first_year is not None:
        name = f"{name}, {period_text(summary)}"
    return name[:200]


# ---- State ---------------------------------------------------------------------------------


def short_duration(value: dt.timedelta | None) -> str:
    """A run's length as the list gives it: ``45 s``, ``21 min``, ``2 h 5 min``."""
    if value is None:
        return ""
    seconds = max(0, int(round(value.total_seconds())))
    if seconds < 60:
        return _("%(s)d s") % {"s": seconds}
    minutes = seconds // 60
    if minutes < 60:
        return _("%(m)d min") % {"m": minutes}
    return _("%(h)d h %(m)d min") % {"h": minutes // 60, "m": minutes % 60}


def short_date(value: dt.datetime) -> str:
    """``18 Nov``, or ``18 Nov 2025`` in another year."""
    local = timezone.localtime(value)
    fmt = "j M" if local.year == timezone.localtime().year else "j M Y"
    return dateformat.format(local, fmt)


ROLE_WORDS = {
    "tasmax": gettext_lazy("maximum temperature"),
    "tasmin": gettext_lazy("minimum temperature"),
    "pr": gettext_lazy("precipitation"),
}


def setup_problem(run: GriddedRun) -> str:
    """What stops a run that has not started, in a few words ("precipitation units"), or
    ""."""
    infos = run.file_infos()
    if any(not f.ok for f in infos):
        return _("a file cannot be read")
    problems, _summary = inspection.check_names(infos, run.names)
    for role in inspection.ROLES:
        if role not in problems:
            continue
        found = inspection.find_variable(infos, run.names.get(role, ""))
        word = str(ROLE_WORDS[role])
        if found is not None and inspection.units_problem(role, found[1].units):
            return _("%(variable)s units") % {"variable": word}
        return word
    return ""


@dataclass
class RunState:
    key: str  # "new", "problem", "queued", "running", "failed", "cancelled", "done"
    text: str
    percent: int | None = None  # while running, when the job has counted its steps

    @property
    def active(self) -> bool:
        return self.key in ("queued", "running")


def state(run: GriddedRun, jobs: list | None = None) -> RunState:
    """The run's state, from its jobs (or ``jobs``: those of a new start, #293)."""
    jobs = run.jobs if jobs is None else jobs
    if not jobs:
        problem = setup_problem(run)
        if problem:
            return RunState("problem", _("Not started: %(problem)s") % {"problem": problem})
        return RunState("new", _("Not started"))
    running = next((j for j in jobs if j.status == Status.RUNNING), None)
    if running is not None:
        if running.total:
            text = _("Calculating · %(percent)s%%") % {"percent": running.percent}
            return RunState("running", text, running.percent)
        return RunState("running", _("Calculating"))
    if any(j.status == Status.QUEUED for j in jobs):
        return RunState("queued", _("Waiting to start"))
    if any(j.status == Status.FAILED for j in jobs):
        return RunState("failed", _("Failed"))
    if any(j.status == Status.CANCELLED for j in jobs):
        return RunState("cancelled", _("Cancelled"))
    finished = max((j.finished_at for j in jobs if j.finished_at), default=None)
    if finished is None:
        return RunState("done", _("Finished"))
    started = min((j.started_at for j in jobs if j.started_at), default=None)
    took = short_duration(finished - started) if started else ""
    when = short_date(finished)
    text = (
        _("Finished %(when)s, %(took)s") % {"when": when, "took": took}
        if took
        else _("Finished %(when)s") % {"when": when}
    )
    return RunState("done", text)


def all_done(run: GriddedRun) -> bool:
    return bool(run.jobs) and all(j.status == Status.SUCCEEDED for j in run.jobs)


def kept_until(run: GriddedRun) -> str:
    """The date the run is deleted, ``25 Nov 2026``; "" while a job is queued or running
    (retention never deletes those)."""
    if run.job_active:
        return ""
    return dateformat.format(timezone.localtime(run.expires_at), "j M Y")


# ---- The list's columns --------------------------------------------------------------------


def chosen_indices(run: GriddedRun) -> list[str]:
    from climpact_web.gridded.forms import all_indices

    return list(run.options.get("indices") or all_indices())


def calculates_text(run: GriddedRun) -> str:
    task = run.options.get("task")
    if not task:
        return DASH
    if task == "thresholds":
        return _("Thresholds file only")
    count = len(chosen_indices(run))
    return ngettext("%(count)s index", "%(count)s indices", count) % {"count": count}


def thresholds_file(run: GriddedRun) -> Path | None:
    """The thresholds file this run wrote, when it kept one."""
    job = run.thresholds_job
    if job is None or job.status != Status.SUCCEEDED:
        return None
    files = job.result.get("files") or []
    return job.output_dir / files[0] if files else None


def thresholds_text(run: GriddedRun, sources: dict[str, GriddedRun] | None = None) -> str:
    """The Thresholds column: the base period (``1971–2000``), with ``file kept`` when the
    run wrote a thresholds file; ``From <run>`` when it read the thresholds file of
    another of the browser's runs (``sources``: the thresholds files by path), or ``From
    <file name>``."""
    o = run.options
    if not o.get("task"):
        return DASH
    base = f"{o.get('base_start')}–{o.get('base_end')}"
    if o["task"] in ("thresholds", "both"):
        return _("%(base)s, file kept") % {"base": base}
    if o.get("thresholds_source") == "file" and o.get("thresholds_file"):
        path = str(o["thresholds_file"])
        source = (sources or {}).get(_resolved(path))
        name = source.display_name if source is not None else Path(path).name
        return _("From %(source)s") % {"source": name}
    return base


def _resolved(path: str | Path) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path)


def threshold_sources(runs) -> dict[str, GriddedRun]:
    """The thresholds files ``runs`` wrote, by resolved path."""
    out = {}
    for run in runs:
        path = thresholds_file(run)
        if path is not None:
            out[_resolved(path)] = run
    return out


def entries(owner: str) -> list[dict]:
    """Gridded's table (the GridList board): every run of ``owner``, most recently
    changed first."""
    runs = list(
        GriddedRun.objects.filter(owner=owner).select_related(
            "thresholds_job", "indices_job", "next_thresholds_job", "next_indices_job"
        )
    )
    for run in runs:
        run.settle()
    sources = threshold_sources(runs)
    rows = []
    for run in runs:
        summary = grid_summary(run)
        rows.append(
            {
                "run": run,
                "name": run.display_name,
                "url": run.get_absolute_url(),
                "grid": grid_text(summary),
                "period": period_text(summary),
                "thresholds": thresholds_text(run, sources),
                "calculates": calculates_text(run),
                # A new start under way shows its progress (#293).
                "state": state(run, run.next_jobs) if run.restarting else state(run),
                "kept": kept_until(run) or DASH,
            }
        )
    return rows


# ---- The context bar -----------------------------------------------------------------------


def index_files(run: GriddedRun) -> list[maps.OutputFile]:
    job = run.indices_job
    if job is None or job.status != Status.SUCCEEDED:
        return []
    return [f for f in maps.output_files(job) if f.index]


def output_files(run: GriddedRun) -> list[tuple[object, maps.OutputFile]]:
    """Every file the run's finished jobs wrote, with its job."""
    out = []
    for job in run.jobs:
        if job.status == Status.SUCCEEDED:
            out += [(job, f) for f in maps.output_files(job)]
    return out


def total_size(run: GriddedRun) -> int:
    return sum(f.size for _job, f in output_files(run))


COUNT_VALUES = 20_000_000  # values read at once by count_cells: 80 MB as float32


def cells_with_data(run: GriddedRun) -> int | None:
    """How many of the grid's cells have a value in the run's index files: those with a
    value at any time in its first annual file (read once, a time step at a time, and
    kept in the run's options)."""
    files = index_files(run)
    if not files:
        return None
    job = run.indices_job
    cached = run.options.get("cells_with_data") or {}
    if cached.get("job") == str(job.pk):
        return cached.get("count")
    chosen = next((f for f in files if f.freq == "ANN"), files[0])
    path = job.output_dir / chosen.path
    try:
        count = count_cells(path)
    except (OSError, ValueError, KeyError, IndexError):
        return None
    run.options = {**run.options, "cells_with_data": {"job": str(job.pk), "count": count}}
    GriddedRun.objects.filter(pk=run.pk).update(options=run.options)
    return count


def count_cells(path: Path) -> int:
    """The cells with a value at any time in the file's first index variable. Read in
    stripes of rows, all times at once: the core's files hold each cell's series in one
    chunk, so reading a time step at a time would decompress the file once a step (#295)."""
    import numpy as np

    with netcdf.dataset(path) as nc:
        variables = maps.index_variables(nc)
        if not variables:
            return 0
        var = nc.variables[variables[0]["name"]]
        var.set_auto_mask(True)
        ny, nx = var.shape[-2:]
        rows = max(1, COUNT_VALUES // max(1, int(np.prod(var.shape)) // ny))
        count = 0
        for y in range(0, ny, rows):
            values = np.ma.filled(
                np.ma.asarray(var[..., y : y + rows, :], dtype=np.float32), np.nan
            )
            finite = np.isfinite(values) & (np.abs(values) < 1e19)
            count += int(finite.any(axis=tuple(range(finite.ndim - 2))).sum())
        return count


def provenance(run: GriddedRun) -> list[dict]:
    """The run's provenance line (the GridFiles board): the grid and its cells with data,
    the period and calendar, the base period, the indices and files (or "calculating"),
    the climpact version and the date it is deleted. Each part is ``{"text", "phone"}``,
    as the context bar takes it; on a phone the period shows."""
    from climpact_web.stations.workspace import core_version

    summary = grid_summary(run)
    parts = []
    if summary.ny:
        cells = ngettext("%(ny)s × %(nx)s cell", "%(ny)s × %(nx)s cells", summary.cells) % {
            "ny": summary.ny,
            "nx": summary.nx,
        }
        count = cells_with_data(run) if all_done(run) else None
        if count is not None:
            cells = _("%(cells)s, %(count)s with data") % {
                "cells": cells,
                "count": numbers.grouped(count),
            }
        parts.append({"text": cells, "phone": False})
    if summary.first_year is not None:
        period = period_text(summary)
        if summary.calendar:
            period = f"{period}, {summary.calendar}"
        parts.append({"text": period, "phone": True})
    o = run.options
    if o.get("base_start"):
        base = _("base %(start)s–%(end)s") % {"start": o["base_start"], "end": o["base_end"]}
        parts.append({"text": base, "phone": False})
    current = state(run)
    if current.active:
        parts.append({"text": _("calculating"), "phone": False})
    elif all_done(run):
        files = index_files(run)
        if files:
            indices = len({f.index for f in files})
            text = ngettext("%(count)s index", "%(count)s indices", indices) % {"count": indices}
            text += ", " + ngettext("%(count)s file", "%(count)s files", len(files)) % {
                "count": len(files)
            }
        else:
            text = _("thresholds file")
        parts.append({"text": text, "phone": False})
    if found := core_version():
        parts.append({"text": f"climpact {found}", "phone": False})
    kept = kept_until(run)
    if kept:
        parts.append({"text": _("kept until %(date)s") % {"date": kept}, "phone": False})
    return parts


# ---- The Files tab -------------------------------------------------------------------------

GROUPINGS = (
    ("theme", gettext_lazy("Theme")),
    ("variable", gettext_lazy("Variable needed")),
    ("frequency", gettext_lazy("Frequency")),
)
THEME_GROUPS = (
    ("heat", gettext_lazy("Heat")),
    ("cold", gettext_lazy("Cold")),
    ("rain", gettext_lazy("Rain")),
    ("drought", gettext_lazy("Drought")),
    ("other", gettext_lazy("Other")),
)
VARIABLE_GROUPS = (
    ("tmax", gettext_lazy("Maximum temperature")),
    ("tmin", gettext_lazy("Minimum temperature")),
    ("prec", gettext_lazy("Precipitation")),
    ("tavg", gettext_lazy("Both temperatures")),
)
FREQUENCY_GROUPS = (
    ("ANN", gettext_lazy("Annual")),
    ("MON", gettext_lazy("Monthly")),
    ("DAY", gettext_lazy("Daily")),
)
GROUPS = {"theme": THEME_GROUPS, "variable": VARIABLE_GROUPS, "frequency": FREQUENCY_GROUPS}
VARIABLES_SHOWN = 3  # more than this: the first two, then "… (10)"


@dataclass
class FileRow:
    file: maps.OutputFile
    code: str
    name: str
    theme: str  # a THEME_GROUPS key
    variable: str  # a VARIABLE_GROUPS key
    variables: str  # the netCDF variables in it, "txx, day_of_txx"


@dataclass
class FileGroup:
    key: str
    label: str
    hue: str  # the theme's hue class, "" when grouped otherwise
    rows: list[FileRow] = field(default_factory=list)

    @property
    def size(self) -> int:
        return sum(r.file.size for r in self.rows)


@lru_cache(maxsize=1024)
def _file_variables(path: str, mtime: float) -> tuple[str, ...]:

    with netcdf.dataset(path) as nc:
        return tuple(maps.data_variables(nc))


def variables_text(path: Path) -> str:
    try:
        names = _file_variables(str(path), path.stat().st_mtime)
    except (OSError, ValueError):
        return ""
    if len(names) <= VARIABLES_SHOWN:
        return ", ".join(names)
    return _("%(first)s … (%(count)s)") % {"first": ", ".join(names[:2]), "count": len(names)}


def file_rows(run: GriddedRun) -> list[FileRow]:
    from climpact.gridded.indices import _BY_VARIABLE
    from climpact_web.help.indices import index_for_output
    from climpact_web.stations import themes
    from climpact_web.stations.results import display_name, short_name

    by_variable = {short: var for var, shorts in _BY_VARIABLE.items() for short in shorts}
    rows = []
    job = run.indices_job
    for f in index_files(run):
        info = index_for_output(f.index)
        theme = themes.chip_of(themes.theme_of(f.index, info)) if info else "other"
        rows.append(
            FileRow(
                file=f,
                code=display_name(f.index, info),
                name=short_name(f.index, info) if info else "",
                theme=theme,
                variable=by_variable.get(info.short if info else "", "tavg"),
                variables=variables_text(job.output_dir / f.path),
            )
        )
    return rows


def group_key(row: FileRow, by: str) -> str:
    if by == "variable":
        return row.variable
    if by == "frequency":
        return row.file.freq
    return row.theme


def file_groups(run: GriddedRun, by: str = "theme", rows: list[FileRow] | None = None):
    """The index files in groups (the File group pattern), in the order of ``GROUPS``;
    empty groups left out."""
    from climpact_web.stations.themes import hue_of

    rows = file_rows(run) if rows is None else rows
    groups = []
    for key, label in GROUPS.get(by, THEME_GROUPS):
        members = [r for r in rows if group_key(r, by) == key]
        if members:
            hue = hue_of(key) if by == "theme" else ""
            groups.append(FileGroup(key, str(label), hue, members))
    return groups


# ---- The run's record ----------------------------------------------------------------------

CHUNK = 1 << 20


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def checksums(run: GriddedRun) -> dict[str, str]:
    """The SHA-256 of each input file, by path: worked out the first time they are asked
    for (a large file takes a while) and kept in the run's options while the file's size
    and modification time stay the same."""
    cached = dict(run.options.get("checksums") or {})
    out, changed = {}, False
    for path in run.paths:
        p = Path(path)
        try:
            stat = p.stat()
        except OSError:
            continue
        key = [stat.st_size, stat.st_mtime_ns]
        entry = cached.get(path)
        if entry and entry[:2] == key:
            out[path] = entry[2]
            continue
        try:
            digest = sha256(p)
        except OSError:
            continue
        cached[path] = [*key, digest]
        out[path] = digest
        changed = True
    if changed:
        run.options = {**run.options, "checksums": cached}
        GriddedRun.objects.filter(pk=run.pk).update(options=run.options)
    return out


INTERNAL_OPTIONS = {"checked", "checksums", "cells_with_data", "thresholds_uploaded"}
LOCAL_OPTIONS = {"tmp_dir", "copy_to"}


def _versions() -> dict[str, str]:
    import platform
    from importlib.metadata import PackageNotFoundError, version

    out = {}
    for package in ("climpact", "climpact-web", "numpy", "xarray", "dask", "netCDF4", "cftime"):
        try:
            out[package] = version(package)
        except PackageNotFoundError:
            continue
    out["python"] = platform.python_version()
    return out


def _when(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(run: GriddedRun) -> dict:
    """``run.json``: what made the run's files, to cite them or to run them again: the
    software and versions, the inputs with their checksums, the grid, the settings and
    the jobs."""
    from climpact.io.output_files import CLIMPACT_VERSION

    hosted = settings.IS_HOSTED
    sums = checksums(run)
    summary = grid_summary(run)
    inputs = []
    for info in run.file_infos():
        item = {"file": info.name}
        if not hosted and run.source == Source.PATH:
            item["path"] = info.path
        item["size"] = info.size
        item["sha256"] = sums.get(info.path)
        item["variables"] = [v.name for v in info.variables]
        inputs.append(item)
    options = {}
    for key, value in run.options.items():
        if key in INTERNAL_OPTIONS or (hosted and key in LOCAL_OPTIONS):
            continue
        if key == "thresholds_file" and value and hosted:
            value = Path(str(value)).name
        options[key] = value
    jobs = []
    for kind, job in (("thresholds", run.thresholds_job), ("indices", run.indices_job)):
        if job is None:
            continue
        item = {
            "kind": kind,
            "status": job.status,
            "started": _when(job.started_at),
            "finished": _when(job.finished_at),
            "files": list(job.result.get("files") or []),
        }
        if job.result.get("copied_to") and not hosted:
            item["copied_to"] = job.result["copied_to"]
        jobs.append(item)
    versions = _versions()
    return {
        "software": f"climpact {versions.get('climpact', '')} "
        f"(Python port of Climpact {CLIMPACT_VERSION})",
        "created": _when(timezone.now()),
        "run": run.display_name,
        "id": str(run.pk),
        "inputs": inputs,
        "variables": run.names,
        "grid": {
            "cells": [summary.ny, summary.nx],
            "latitude": summary.y_range,
            "longitude": summary.x_range,
            "first_day": summary.first,
            "last_day": summary.last,
            "calendar": summary.calendar,
        },
        "settings": options,
        "jobs": jobs,
        "versions": versions,
    }


def record_text(run: GriddedRun) -> str:
    return json.dumps(record(run), indent=2, ensure_ascii=False, default=str) + "\n"


def log_text(run: GriddedRun) -> str:
    """``climpact.log``: the jobs' logs (when each attempt started and finished, and
    why one failed), thresholds first. Hosted, only the timestamped lines: a traceback's
    lines name the server's folders."""
    out = []
    for kind, job in (("thresholds", run.thresholds_job), ("indices", run.indices_job)):
        if job is None:
            continue
        out.append(f"# {kind}: {job.title or job.kind} ({job.status})\n")
        lines = job.log.splitlines()
        if settings.IS_HOSTED:
            lines = [line for line in lines if line.startswith("[")]
        out.extend(f"{line}\n" for line in lines)
        if job.error:
            out.append(f"error: {job.error}\n")
        out.append("\n")
    return "".join(out) or "\n"

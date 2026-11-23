"""The workspace's Files (#239, the Files board): the files that span its stations, and
the record of how they were made.

- **Everything** (zip): each station's folder in Climpact for R's layout (``<station>/``
  with ``indices/``, ``plots/``, ``trend/``, ``thres/`` and ``qc/``, as R's batch zip), a
  station that failed as R's ``<station>.errors.txt``, and the workspace files below. A
  station's ``homogeneity/`` files (#365: the break tests its checks ran) come from the
  checks it shows, as in its own zip.
- **Trends, all stations** (CSV): one row per station and index, the trend the Indices
  show (Sen's slope per decade of the index's main series, its 95% interval, whether the
  interval excludes zero, the years with a value, its units and whether the station's
  results are out of date).
- **Indices, all stations** (CSV, long format): every yearly and monthly value of every
  station's index tables (the daily tables, EHF and ECF, and TX95t's day of the year are
  left out: they have no year and month).
- **climpact_run.json**, the provenance file, in every zip: the software, when the files
  were made, the base period, the settings, the trend method and each station's file,
  its SHA-256 and coordinates. "Copy methods text" is a sentence made from it.
- Each station's folder as a zip of its own, R's station zip with ``climpact_run.json``
  added, for the by-station table (and the station's own Files and Indices).

The files are made from the results each station shows, the first time they are asked for,
and kept under the workspace's folder (``<MEDIA_ROOT>/stations/<workspace>/files/``) until
something they are made from changes: a run, a setting, a station's name or coordinates
(:func:`fingerprint`). Nothing is made while a station is still being
calculated. The files are deleted with the workspace.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from climpact_web.stations import breaks, overview, workspace
from climpact_web.stations.models import Station, Workspace, stations_dir

PROVENANCE_FILE = "climpact_run.json"
TRENDS_FILE = "trends_all_stations.csv"
INDICES_FILE = "indices_all_stations.csv"
EVERYTHING_FILE = "everything.zip"
TREND_METHOD = "Sen's slope per decade, 95% interval (zyp); significant when it excludes zero"
TRENDS_COLUMNS = ("station", "index", "slope", "lower", "upper", "significant", "years_used")
TRENDS_UNITS = "units"  # after the board's columns: what the slope is in, "°C/decade"
TRENDS_OUT_OF_DATE = "out_of_date"  # yes: the station's results are from before a change
INDICES_COLUMNS = ("station", "index", "year", "month", "value")
# The station's R files, the columns of the by-station table, in the board's order.
COLUMNS = ("folder", "report", "all_plots", "trends", "thresholds", "missing", "quality")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


# ---- the stations ------------------------------------------------------------------------


@dataclass
class Entry:
    """One station of the workspace, as Files sees it: its row of the overview (states),
    the results it shows (``source``, None without results) and why it has none."""

    station: Station
    row: overview.Row
    job: object = None
    source: object = None  # results.RunSource
    out_of_date: bool = False
    folder: str = ""  # its folder's name in Everything (R's station name)

    @property
    def name(self) -> str:
        return self.row.name

    @property
    def failed(self) -> bool:
        """Whether the station's last run failed (its results, if any, are an earlier run's)."""
        return self.row.indices.state == overview.FAILED

    @property
    def why(self) -> str:
        """Why the station has no results, in the board's words: "not run", "checking"..."""
        if self.source is not None:
            return ""
        state = self.row.indices.state
        if self.row.quality.state == "checking":
            return _("checking")
        if state == overview.NOT_RUN:
            return _("not run")
        if state == overview.FAILED:
            return _("failed")
        if state in (overview.CALCULATING, overview.DONE):  # done: its job still finishing
            return _("calculating")
        if state == overview.WAITING:
            return _("waiting")
        return _("not calculated")


def entries(space: Workspace, owner: str, table: list | None = None) -> list[Entry]:
    """Every station of the workspace, in the overview's order, with the results it
    shows (the Indices' :func:`~climpact_web.stations.views_indices.current_source`).
    ``table`` is the overview's rows when the caller has them already."""
    from climpact_web.stations import results as results_model

    out, taken = [], set()
    for row in table if table is not None else overview.rows(space, owner):
        station = row.station
        entry = Entry(station, row)
        job = workspace.shown_run(station)
        if job is not None and row.indices.state not in overview.RUNNING:
            name = (station.origin or {}).get("station") if job.kind == "batch" else None
            entry.job, entry.source = job, results_model.run_source(job, name)
        if entry.source is not None:
            entry.out_of_date = bool(workspace.run_changes(station, job))
            folder = entry.source.station
            if folder in taken:  # two stations from files of the same name
                folder = f"{folder}_{station.slug}"
            taken.add(folder)
            entry.folder = folder
        out.append(entry)
    return out


def busy(items: list[Entry]) -> bool:
    """Whether a station is still being calculated: the files wait for it. A station is
    also while its run says done but its job has not finished (a batch makes its zip
    after the last station), so it shows no results yet. (Checks that run again do not
    change the files of the results shown.)"""
    return any(
        e.row.indices.state in overview.RUNNING
        or (e.row.indices.state == overview.DONE and e.source is None)
        for e in items
    )


# ---- the workspace files -----------------------------------------------------------------


def _number(value: float) -> str:
    """A value as R writes it (15 significant digits); "" for a missing one."""
    if value is None or value != value:
        return ""
    return f"{value:.15g}"


def _results(entry: Entry):
    from climpact_web.stations import results as results_model

    space = entry.station.workspace
    return results_model.results_for(
        entry.source, entry.station.summary, (space.base_start, space.base_end)
    )


def _years_used(plot) -> int:
    """The years with a value in a series (monthly: the years with any month)."""
    return len({math.floor(x) for x, v in zip(plot.x, plot.values, strict=False) if v == v})


def trends_csv(items: list[Entry]) -> str:
    """The trend of every station's every index, as the Indices show it: per decade."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow((*TRENDS_COLUMNS, TRENDS_UNITS, TRENDS_OUT_OF_DATE))
    for entry in items:
        if entry.source is None:
            continue
        run = _results(entry)
        out_of_date = "yes" if entry.out_of_date else "no"
        for card in run.cards:
            trend, plot = card.trend, run.plots.get(card.main)
            if trend is None or plot is None:
                continue  # no trend: TX95t's day of the year, the daily tables
            if trend.get("valid"):
                values = (
                    _number(trend["slope"]),
                    _number(trend["lower"]),
                    _number(trend["upper"]),
                    "yes" if trend["significant"] else "no",
                )
            else:  # too few values for a trend (R's min_trend_data)
                values = ("", "", "", "")
            units = f"{card.trend_units}/decade" if card.trend_units else "per decade"
            row = (entry.name, card.code, *values, _years_used(plot), units, out_of_date)
            writer.writerow(row)
    return out.getvalue()


def indices_csv(items: list[Entry]) -> str:
    """Every yearly and monthly value of every station's indices, one per row."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(INDICES_COLUMNS)
    for entry in items:
        if entry.source is None:
            continue
        run = _results(entry)
        for card in run.cards:
            for series in card.series:
                plot = run.plots.get(series.name)
                if plot is None or series.name.startswith("day_of_"):
                    continue
                if plot.step not in ("year", "month"):
                    continue
                for x, value in zip(plot.x, plot.values, strict=False):
                    year = math.floor(x)
                    month = round((x - year) * 12 + 0.5) if plot.step == "month" else ""
                    writer.writerow((entry.name, card.code, year, month, _number(value)))
    return out.getvalue()


def settings_text(space: Workspace) -> str:
    from climpact_web.stations.views_workspace import settings_text as text

    return text(space)


def provenance(space: Workspace, items: list[Entry], created: dt.datetime) -> dict:
    """``climpact_run.json``: what made the files, to cite them or to run them again."""
    from climpact.io.output_files import CLIMPACT_VERSION
    from climpact_web.stations.forms import QCParamsForm

    version = workspace.core_version()
    stations = []
    for entry in items:
        record = {"name": entry.name, **_made_from(entry)}
        if entry.source is not None:
            record["folder"] = entry.folder
            if entry.out_of_date:
                record["results"] = _out_of_date(entry)
        else:
            record["results"] = f"none ({entry.why})"
        stations.append(record)
    settings = workspace.workspace_settings(space)
    return {
        "software": f"climpact {version} (Python port of Climpact {CLIMPACT_VERSION})",
        "created": created.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "workspace": space.display_name,
        "base_period": [space.base_start, space.base_end],
        "index_settings": settings_text(space),
        "settings": {
            "quality_thresholds": QCParamsForm.initial_for(space.qc_params),
            "indices": settings["params"],
            "break_detection": breaks.provenance(space),
        },
        "trend": TREND_METHOD,
        "stations": stations,
    }


# What changed since out-of-date results were made (``workspace.run_changes``), in the
# provenance file's words.
_CHANGES = {
    "file": "the file",
    "name": "the station's name",
    "location": "the coordinates",
    "base_period": "the base period",
    "qc": "the quality thresholds",
    "settings": "the index settings",
}


def _made_from(entry: Entry) -> dict:
    """A station's file (name, SHA-256 and years) and coordinates in the provenance file:
    the station's current ones, or, while its results are out of date, those the shown run
    read (#307, ``workspace.recorded_inputs``), so after "Replace file" or new coordinates
    the old results in the zip are not described by the new file. What the run did not
    record is the current one: the file of a job from before #269, which has no ``data``,
    and the coordinates of one from before #179."""
    station = entry.station
    summary = station.summary or {}
    made = {
        "file": station.file_name,
        "sha256": station.file_hash,
        "lat": station.latitude,
        "lon": station.longitude,
        "years": [summary.get("first_year"), summary.get("last_year")],
    }
    if not entry.out_of_date:
        return made
    recorded = workspace.recorded_inputs(station, entry.job)
    if data := recorded.get("data"):  # the name, hash and years of one file, never mixed
        made["file"] = data.get("name") or made["file"]
        made["sha256"] = recorded.get("file") or made["sha256"]
        made["years"] = [data.get("first_year"), data.get("last_year")]
    if meta := recorded.get("metadata"):
        made["lat"], made["lon"] = meta.get("latitude"), meta.get("longitude")
    return made


def _out_of_date(entry: Entry) -> str:
    """Why a station's results are out of date: "out of date: made before a change to the
    file and the coordinates"."""
    names = workspace.run_changes(entry.station, entry.job)
    words = [_CHANGES[n] for n in names if n in _CHANGES] or ["its inputs"]
    changed = words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"
    return f"out of date: made before a change to {changed}"


def provenance_text(record: dict) -> str:
    return json.dumps(record, indent=2, ensure_ascii=False, default=str) + "\n"


def methods_text(record: dict) -> str:
    """ "Copy methods text": the provenance file in a sentence, for a paper's methods."""
    from climpact.io.output_files import CLIMPACT_VERSION

    count = len([s for s in record["stations"] if "folder" in s])
    start, end = record["base_period"]
    version = record["software"].split(" ", 2)[1]
    settings = record["index_settings"]
    if settings == _("ET-SCI defaults"):
        settings_part = _("the ET-SCI default settings")
    else:
        settings_part = _("%(settings)s (otherwise the ET-SCI defaults)") % {"settings": settings}
    first = ngettext(
        "Climate indices for %(count)s station were calculated with climpact %(version)s, "
        "a Python port of Climpact %(r)s, using the base period %(start)s–%(end)s and "
        "%(settings)s.",
        "Climate indices for %(count)s stations were calculated with climpact %(version)s, "
        "a Python port of Climpact %(r)s, using the base period %(start)s–%(end)s and "
        "%(settings)s.",
        count,
    ) % {
        "count": count,
        "version": version,
        "r": CLIMPACT_VERSION,
        "start": start,
        "end": end,
        "settings": settings_part,
    }
    second = _(
        "Trends are Sen's slopes with 95%% confidence intervals (zyp); a trend is "
        "significant when its interval excludes zero."
    )
    return f"{first} {second}"


# ---- making and keeping them -------------------------------------------------------------


def files_dir(space: Workspace) -> Path:
    """Where the workspace's files are kept: ``<MEDIA_ROOT>/stations/<workspace>/files``."""
    return stations_dir() / str(space.pk) / "files"


def fingerprint(space: Workspace, items: list[Entry]) -> str:
    """What the files are made from: when it changes, they are made again."""
    parts = [
        str(space.pk),
        space.display_name,
        str((space.base_start, space.base_end)),
        json.dumps(space.qc_params, sort_keys=True, default=str),
        json.dumps(space.index_settings, sort_keys=True, default=str),
        json.dumps(space.break_detection, sort_keys=True, default=str),
        workspace.core_version(),
    ]
    for e in items:
        s = e.station
        job = e.job
        checks = workspace.shown_qc(s)  # the breaks in its zip are its checks' (#365)
        parts.append(
            "|".join(
                str(p)
                for p in (
                    s.pk,
                    e.name,
                    s.file_name,
                    s.file_hash,
                    s.latitude,
                    s.longitude,
                    getattr(job, "pk", ""),
                    getattr(job, "finished_at", ""),
                    getattr(checks, "pk", ""),
                    e.folder,
                    e.out_of_date,
                    e.why,
                )
            )
        )
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:24]


def _entries_of(folder: Path):
    """The files of a station folder for a zip: (path, name in the zip), sorted, no zips."""
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix != ".zip":
            yield path, path.relative_to(folder).as_posix()


def _write(archive: zipfile.ZipFile, path: Path, name: str) -> None:
    # PNG and PDF files are compressed already: stored, as the core's zip_folder does.
    stored = path.suffix in (".png", ".pdf")
    archive.write(path, name, zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)


def _break_files(entry: Entry, taken: set[str]) -> list[tuple[Path, str]]:
    """The ``homogeneity/`` files of the checks the station shows (#365), not ``taken``
    (names already in the zip: a run that looked for breaks itself)."""
    return [
        (p, n) for p, n in breaks.job_files(workspace.shown_qc(entry.station)) if n not in taken
    ]


def _station_zip(entry: Entry, target: Path, record: dict) -> None:
    """R's station zip (the run's own, or the folder zipped as R does) with the
    provenance file added: one station's ``climpact_run.json``; and the break tests'
    files of its checks (#365)."""
    from climpact_web.stations.downloads import zip_path

    one = {**record, "stations": [s for s in record["stations"] if s.get("folder") == entry.folder]}
    made = zip_path(entry.source)
    if made is not None and made.is_file():
        shutil.copyfile(made, target)
        with zipfile.ZipFile(target, "a", zipfile.ZIP_DEFLATED) as archive:
            for path, name in _break_files(entry, set(archive.namelist())):
                _write(archive, path, name)
            archive.writestr(PROVENANCE_FILE, provenance_text(one))
        return
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        names = set()
        for path, name in _entries_of(entry.source.station_dir):
            _write(archive, path, name)
            names.add(name)
        for path, name in _break_files(entry, names):
            _write(archive, path, name)
        archive.writestr(PROVENANCE_FILE, provenance_text(one))


def _everything(items: list[Entry], target: Path, texts: dict[str, str]) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for name, text in texts.items():
            archive.writestr(name, text)
        for entry in items:
            if entry.source is not None:
                names = set()
                for path, name in _entries_of(entry.source.station_dir):
                    _write(archive, path, f"{entry.folder}/{name}")
                    names.add(name)
                for path, name in _break_files(entry, names):
                    _write(archive, path, f"{entry.folder}/{name}")
            elif entry.row.indices.state == overview.FAILED:  # as R's batch zip
                error = entry.row.indices.error or _("The station could not be calculated.")
                archive.writestr(f"{entry.station.slug}.errors.txt", error + "\n")


@dataclass
class Built:
    """The workspace's files, made: where they are and what they hold."""

    folder: Path
    provenance: dict
    stations: dict[str, Path] = field(default_factory=dict)  # slug -> its zip

    @property
    def everything(self) -> Path:
        return self.folder / EVERYTHING_FILE

    @property
    def trends(self) -> Path:
        return self.folder / TRENDS_FILE

    @property
    def indices(self) -> Path:
        return self.folder / INDICES_FILE


def build(space: Workspace, items: list[Entry]) -> Built | None:
    """The workspace's files, made now unless they are already: None while a station is
    still being calculated, or when no station has results."""
    if busy(items) or not any(e.source is not None for e in items):
        return None
    root = files_dir(space)
    key = fingerprint(space, items)
    folder = root / key
    if not (folder / PROVENANCE_FILE).is_file():
        temp = root / f".{key}-{uuid.uuid4().hex}"
        temp.mkdir(parents=True)
        try:
            record = provenance(space, items, timezone.now())
            texts = {
                PROVENANCE_FILE: provenance_text(record),
                TRENDS_FILE: trends_csv(items),
                INDICES_FILE: indices_csv(items),
            }
            for entry in items:
                if entry.source is not None:
                    _station_zip(entry, temp / f"{entry.station.slug}.zip", record)
            _everything(items, temp / EVERYTHING_FILE, texts)
            for name in (TRENDS_FILE, INDICES_FILE):
                (temp / name).write_text(texts[name], encoding="utf-8")
            # Last, so a folder with it is complete.
            (temp / PROVENANCE_FILE).write_text(texts[PROVENANCE_FILE], encoding="utf-8")
            try:
                temp.rename(folder)
            except OSError:  # made by another request meanwhile
                shutil.rmtree(temp, ignore_errors=True)
        except BaseException:
            shutil.rmtree(temp, ignore_errors=True)
            raise
        for old in root.iterdir():  # what earlier results made
            if old.name != key and not old.name.startswith("."):
                shutil.rmtree(old, ignore_errors=True)
    record = json.loads((folder / PROVENANCE_FILE).read_text(encoding="utf-8"))
    stations = {
        e.station.slug: folder / f"{e.station.slug}.zip" for e in items if e.source is not None
    }
    return Built(folder, record, stations)


def download_name(space: Workspace, what: str) -> str:
    """The name a workspace file downloads as: ``nsw_coast.zip``, ``nsw_coast_trends.csv``."""
    base = _UNSAFE.sub("_", space.display_name).strip("._").lower()[:60] or "climpact"
    return {
        "everything": f"{base}.zip",
        "trends": f"{base}_trends.csv",
        "indices": f"{base}_indices.csv",
    }[what]


# ---- the page ----------------------------------------------------------------------------


@dataclass
class Cell:
    """One file of the by-station table: its link and size, or why it is missing."""

    url: str = ""
    size: int | None = None
    text: str = ""  # instead of a size: "6 files"
    why: str = ""
    label: str = ""  # the column, for screen readers

    @property
    def has(self) -> bool:
        return bool(self.url)


def _file_cell(entry: Entry, path: Path | None, label: str) -> Cell:
    from django.urls import reverse

    if path is None or not path.is_file():
        return Cell(why=entry.why or "–", label=label)
    rel = entry.source.relative(path) if entry.source else None
    url = reverse("jobs:file", args=[entry.source.job.pk, rel])
    return Cell(url=url, size=path.stat().st_size, label=label)


def table(items: list[Entry], built: Built | None, labels: dict) -> list[dict]:
    """The by-station table: each station's R files (the board's seven columns)."""
    from django.urls import reverse

    from climpact_web.stations import downloads

    rows = []
    for entry in items:
        station, source = entry.station, entry.source
        cells = {}
        if source is not None and built is not None and built.stations.get(station.slug):
            path = built.stations[station.slug]
            cells["folder"] = Cell(
                url=reverse("stations:station_zip", args=[station.workspace_id, station.slug]),
                size=path.stat().st_size,
                label=labels["folder"],
            )
        else:
            cells["folder"] = Cell(why=entry.why or "–", label=labels["folder"])
        if source is not None:
            prefix = source.station
            cells["report"] = _file_cell(entry, downloads.report_path(source), labels["report"])
            cells["all_plots"] = _file_cell(
                entry, source.station_dir / "plots" / f"{prefix}_all_plots.pdf", labels["all_plots"]
            )
            cells["trends"] = _file_cell(
                entry, source.station_dir / "trend" / f"{prefix}_trend.csv", labels["trends"]
            )
            cells["thresholds"] = _file_cell(
                entry, source.station_dir / "thres" / f"{prefix}_thres.csv", labels["thresholds"]
            )
        else:
            for key in ("report", "all_plots", "trends", "thresholds"):
                cells[key] = Cell(why=entry.why or "–", label=labels[key])
        cells["missing"], cells["quality"] = _quality_cells(entry, labels)
        rows.append({"entry": entry, "cells": [cells[k] for k in COLUMNS]})
    return rows


def _quality_cells(entry: Entry, labels: dict) -> tuple[Cell, Cell]:
    """Missing values (the checks' ``nastatistics`` file) and Quality flags (how many
    other files the checks wrote, a link to them on the station's Files)."""
    from django.urls import reverse

    from climpact_web.stations import downloads

    station = entry.station
    why = _("checking") if entry.row.quality.state == "checking" else "–"
    if entry.row.quality.state == "checking":
        return Cell(why=why, label=labels["missing"]), Cell(why=why, label=labels["quality"])
    quality = downloads.quality_downloads(station, entry.source)
    if not quality:
        return Cell(why=why, label=labels["missing"]), Cell(why=why, label=labels["quality"])
    missing, flags = None, []
    for d in quality["files"]:
        if Path(d.path).stem.endswith("_nastatistics"):
            missing = d
        elif Path(d.path).parent.name != "homogeneity":  # the break tests' files (#365)
            flags.append(d)
    if missing is not None:
        url = reverse("jobs:file", args=[quality["job"].pk, missing.path])
        missing_cell = Cell(url=url, size=missing.size, label=labels["missing"])
    else:
        missing_cell = Cell(why="–", label=labels["missing"])
    if flags:
        text = ngettext("%(count)s file", "%(count)s files", len(flags)) % {"count": len(flags)}
        url = reverse("stations:downloads", args=[station.workspace_id, station.slug])
        flags_cell = Cell(url=f"{url}#quality-files", text=text, label=labels["quality"])
    else:
        flags_cell = Cell(why="–", label=labels["quality"])
    return missing_cell, flags_cell

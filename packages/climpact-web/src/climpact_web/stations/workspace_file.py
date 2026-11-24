"""The workspace file (#240): save a workspace as one zip, and open one to rebuild it.

Hosted workspaces are deleted after the retention period and belong to one browser. "Save
file" (the WorkspaceList board) downloads ``climpact_workspace.zip``, which holds:

``workspace.json``
    The manifest: the format and its version (:data:`FORMAT`, :data:`FORMAT_VERSION`),
    the software that saved it, the workspace's name and settings (base period, quality
    thresholds, index settings and output options, and break detection since format 2,
    #367, all filled in) and its stations, each
    with its file in the zip, its file's original name and SHA-256, its name, latitude and
    longitude, its own index values (a batch metadata line's), whether it is the sample and
    whether its results were in use ("Go to indices").
``stations/<slug>.txt``
    Each station's input file, as the workspace keeps it.
``station_history.csv``
    Break detection's station history file, when the workspace has one (#367; its name
    and SHA-256 are in the manifest).
``metadata.txt``
    The stations in Climpact for R's batch metadata format, so the files can be run in R
    too (``stations/`` is the batch's folder of station files). Opening ignores it.
``climpact_run.json``
    The provenance file of every zip the app serves (#239, ``workspace_files.provenance``).

Only stations that are set up (a file, a name and a location) are saved: the others
cannot be checked or calculated anywhere.

"Open a workspace file" (Get started and Workspaces) reads such a zip (:func:`read`) and
rebuilds the workspace for this browser (:func:`open_into`): a new workspace with the
saved name and settings, whose stations are added through Add stations' own routes (#233,
``views_add.add_one`` for one station, ``views_add.add_many``, a batch, for several), so
the checks and indices are calculated again, exactly as for files dropped on Add stations.

The zip is untrusted. :func:`read` refuses, each with a plain message, before anything is
made: a file that is not a zip, too large an upload (the upload limit, enforced by the
middleware), more entries than a batch takes, any entry not in the format (a path with a
folder other than ``stations/``, an absolute path, ``..``, a backslash, a drive letter, a
symbolic link, an encrypted or unusually compressed entry, a name given twice), more data
than a batch can use or an entry compressed suspiciously well (counted while it is read,
not taken from the zip's header), a manifest that is not JSON or does not describe a
workspace, a file from a newer version of the format, settings out of range, a station file
or station history file that changed since it was saved (its SHA-256) or cannot be read.
Format 1 (before #367) has no break detection: it opens with break detection's defaults.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math
import re
import stat
import tempfile
import zipfile
import zlib
from dataclasses import dataclass, field

from django.conf import settings as django_settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from climpact_web.batch import check
from climpact_web.stations import workspace
from climpact_web.stations.models import Station, Workspace

FILE_NAME = "climpact_workspace.zip"
FORMAT = "climpact-workspace"
FORMAT_VERSION = 2  # 2: break detection's settings and station history file (#367)
MANIFEST = "workspace.json"
HISTORY = "station_history.csv"
METADATA = "metadata.txt"
PROVENANCE = "climpact_run.json"
STATIONS_DIR = "stations/"

# The limits of a workspace file, within those of a batch on Add stations (batch/check.py).
MAX_STATIONS = check.MAX_FILES
MAX_ENTRIES = MAX_STATIONS + 5  # the station files, the four others and stations/
MAX_UNPACKED_BYTES = check.MAX_UNPACKED_BYTES  # every entry, uncompressed
MAX_MANIFEST_BYTES = 4 * 1024 * 1024  # workspace.json, metadata.txt, climpact_run.json
MAX_STATION_BYTES = 64 * 1024 * 1024  # one station file: 200 years of days is under 10 MB
# A station file compresses about 5 to 10 times; an entry that unpacks to more than this
# many times its compressed size, past the first megabyte, is refused as a zip bomb.
MAX_RATIO = 200
RATIO_FREE_BYTES = 1024 * 1024
CHUNK = 64 * 1024

_STATION_ENTRY = re.compile(r"stations/[a-z0-9][a-z0-9-]{0,59}\.txt")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_UNSAFE_FILE = re.compile(r"[^A-Za-z0-9._()\- ]+")


class NotAWorkspaceFile(Exception):
    """A workspace file refused: ``message`` says why, for the person who chose it."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ---- saving -------------------------------------------------------------------------------


def saved_stations(space: Workspace, owner: str) -> list[Station]:
    """The stations a workspace file holds: those set up, in the overview's order."""
    from climpact_web.stations.overview import ordered

    return [s for s in ordered(space, owner) if workspace.set_up(s) and s.station_file.is_file()]


def settings_record(space: Workspace) -> dict:
    """The workspace's settings, every value filled in (the defaults where it has none)."""
    from climpact_web.stations import breaks
    from climpact_web.stations.forms import QCParamsForm

    chosen = breaks.settings_of(space)
    history = chosen.pop("history")
    path = breaks.history_path(space)
    if history and path is not None and path.is_file():
        chosen["station_history"] = {
            "file": HISTORY,
            "name": history.get("name") or HISTORY,
            "sha256": history["sha256"],
        }
    else:
        chosen["station_history"] = None
    return {
        "base_period": [space.base_start, space.base_end],
        "quality_thresholds": QCParamsForm.initial_for(space.qc_params),
        "indices": workspace.workspace_settings(space),
        "break_detection": chosen,
    }


def manifest(space: Workspace, stations: list[Station], created: dt.datetime) -> dict:
    """``workspace.json``."""
    from climpact.io.output_files import CLIMPACT_VERSION

    records = []
    for station in stations:
        summary = station.summary or {}
        records.append(
            {
                "name": station.station_name,
                "file": f"{STATIONS_DIR}{station.slug}.txt",
                "file_name": station.file_name,
                "sha256": station.file_hash,
                "latitude": station.latitude,
                "longitude": station.longitude,
                "years": [summary.get("first_year"), summary.get("last_year")],
                "params": workspace.own_params(station),
                "sample": station.source == "sample",
                "use_results": workspace.committed(station),
            }
        )
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "software": (
            f"climpact {workspace.core_version()} (Python port of Climpact {CLIMPACT_VERSION})"
        ),
        "created": created.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "name": space.name,
        "settings": settings_record(space),
        "stations": records,
    }


def metadata_text(stations: list[Station]) -> str:
    """``metadata.txt``: the stations in R's batch metadata format, each with every index
    value it is calculated with (the workspace's, and its own)."""
    rows = []
    for station in stations:
        chosen = workspace.station_settings(station)["params"]
        rows.append(
            {
                "station_file": f"{station.slug}.txt",
                "latitude": station.latitude,
                "longitude": station.longitude,
                "params": {k: chosen[k] for k in check.PARAM_FIELDS.values()},
            }
        )
    return check.metadata_text(rows)


def write(space: Workspace, owner: str, items: list, target) -> int:
    """Write the workspace file of ``space`` to the binary file ``target``. ``items`` are
    the workspace's stations as Files sees them (``workspace_files.entries``), for the
    provenance file. Returns how many stations it holds."""
    from climpact_web.stations import workspace_files

    now = timezone.now()
    stations = saved_stations(space, owner)
    record = manifest(space, stations, now)
    provenance = workspace_files.provenance(space, items, now)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        archive.writestr(METADATA, metadata_text(stations))
        archive.writestr(PROVENANCE, workspace_files.provenance_text(provenance))
        for station in stations:
            archive.write(station.station_file, f"{STATIONS_DIR}{station.slug}.txt")
        if record["settings"]["break_detection"]["station_history"]:
            from climpact_web.stations import breaks

            archive.write(breaks.history_path(space), HISTORY)
    return len(stations)


def saved_file(space: Workspace, owner: str, items: list):
    """The workspace file in a temporary file, at its start, for a response to stream."""
    handle = tempfile.TemporaryFile()
    write(space, owner, items, handle)
    handle.seek(0)
    return handle


# ---- reading ------------------------------------------------------------------------------


@dataclass
class SavedStation:
    name: str
    file: str  # its entry in the zip
    file_name: str  # the file's name as first uploaded, made safe
    data: bytes
    latitude: float
    longitude: float
    params: dict = field(default_factory=dict)
    sample: bool = False
    use_results: bool = False


@dataclass
class Opened:
    """A workspace file, read and checked."""

    name: str
    base_start: int
    base_end: int
    qc_params: dict
    index_settings: dict  # workspace_settings form
    stations: list[SavedStation]
    break_detection: dict = field(default_factory=dict)  # Workspace.break_detection's form
    history: bytes | None = None  # its station history file


def _damaged(detail: str) -> NotAWorkspaceFile:
    return NotAWorkspaceFile(
        _("This workspace file is damaged or was changed after it was saved: %(detail)s")
        % {"detail": detail}
    )


def entry_problem(info: zipfile.ZipInfo) -> str | None:
    """Why an entry of the zip has no place in a workspace file, or None."""
    name = info.filename
    if "\x00" in name or "\\" in name:
        return _("%(name)s has a name no workspace file uses.") % {"name": name}
    if name.startswith("/") or re.match(r"[A-Za-z]:", name):
        return _("%(name)s is an absolute path.") % {"name": name}
    if any(part in ("..", ".") for part in name.split("/")):
        return _("%(name)s points outside the workspace file.") % {"name": name}
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        return _("%(name)s is a symbolic link.") % {"name": name}
    if info.flag_bits & 0x1:
        return _("%(name)s is encrypted.") % {"name": name}
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        return _("%(name)s is compressed in a way workspace files are not.") % {"name": name}
    if name == STATIONS_DIR:
        return None
    if name in (MANIFEST, METADATA, PROVENANCE, HISTORY) or _STATION_ENTRY.fullmatch(name):
        return None
    return _("%(name)s is not part of a workspace file.") % {"name": name}


def _limit_for(name: str) -> int:
    return MAX_STATION_BYTES if name.startswith(STATIONS_DIR) else MAX_MANIFEST_BYTES


def _too_much() -> NotAWorkspaceFile:
    return NotAWorkspaceFile(
        _(
            "This file unpacks to more data than a workspace can hold (%(mb)d MB at most). "
            "It may be a zip bomb, or not a workspace file."
        )
        % {"mb": MAX_UNPACKED_BYTES // (1024 * 1024)}
    )


def unpack(handle) -> dict[str, bytes]:
    """The entries of a workspace file, by name, each checked (:func:`entry_problem`) and
    read within the limits, counted as the data come, whatever the zip's header says."""
    try:
        archive = zipfile.ZipFile(handle)
        infos = archive.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ValueError):
        raise NotAWorkspaceFile(
            _(
                "This is not a zip file. A workspace file is the climpact_workspace.zip "
                "that Save file downloads."
            )
        ) from None
    if len(infos) > MAX_ENTRIES:
        raise NotAWorkspaceFile(
            _("This zip holds %(count)d files; a workspace file holds at most %(max)d stations.")
            % {"count": len(infos), "max": MAX_STATIONS}
        )
    if MANIFEST not in {info.filename for info in infos}:
        raise NotAWorkspaceFile(
            _(
                "This zip has no workspace.json, so it is not a workspace file. To add "
                "station files, use Add stations instead."
            )
        )
    seen: set[str] = set()
    declared = 0
    for info in infos:
        problem = entry_problem(info)
        if problem:
            raise NotAWorkspaceFile(
                _("This is not a workspace file that can be opened: %(problem)s")
                % {"problem": problem}
            )
        if info.filename in seen:
            raise _damaged(_("%(name)s is in it twice.") % {"name": info.filename})
        seen.add(info.filename)
        declared += info.file_size
        if declared > MAX_UNPACKED_BYTES or info.file_size > _limit_for(info.filename):
            raise _too_much()
    out: dict[str, bytes] = {}
    total = 0
    for info in infos:
        if info.is_dir():
            continue
        limit = _limit_for(info.filename)
        size = 0
        parts = []
        try:
            with archive.open(info) as stream:
                while chunk := stream.read(CHUNK):
                    size += len(chunk)
                    total += len(chunk)
                    if size > limit or total > MAX_UNPACKED_BYTES:
                        raise _too_much()
                    if size > RATIO_FREE_BYTES and size > MAX_RATIO * max(info.compress_size, 1):
                        raise _too_much()
                    parts.append(chunk)
        except NotAWorkspaceFile:
            raise
        except (zipfile.BadZipFile, zlib.error, EOFError, OSError, ValueError, RuntimeError):
            raise _damaged(_("%(name)s cannot be read.") % {"name": info.filename}) from None
        out[info.filename] = b"".join(parts)
    return out


def _reject_constant(name: str):
    raise ValueError(name)


def load_manifest(data: bytes) -> dict:
    """``workspace.json`` as a dict, or a refusal saying it is not JSON."""
    try:
        record = json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise _damaged(_("workspace.json is not valid JSON.")) from None
    if not isinstance(record, dict):
        raise _damaged(_("workspace.json does not describe a workspace."))
    return record


def _is_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def check_version(record: dict) -> None:
    if record.get("format") != FORMAT:
        raise NotAWorkspaceFile(
            _("workspace.json is not a Climpact workspace file's: it names no workspace format.")
        )
    version = record.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _damaged(_("workspace.json has no format version."))
    if version > FORMAT_VERSION:
        raise NotAWorkspaceFile(
            _(
                "This workspace file was saved by a newer version of Climpact (format "
                "%(version)d; this one reads format %(supported)d). Update Climpact, or open "
                "it where it was saved."
            )
            % {"version": version, "supported": FORMAT_VERSION}
        )


def check_settings(record) -> tuple[int, int, dict, dict]:
    """The saved settings, checked as the settings pages check them: (base start, base end,
    quality thresholds, index settings in ``workspace_settings`` form)."""
    from django import forms

    from climpact_web.stations.forms import QCParamsForm
    from climpact_web.stations.forms_indices import IndexParamsForm, initial_from_params

    if not isinstance(record, dict):
        raise _damaged(_("its settings are missing."))
    period = record.get("base_period")
    if (
        not isinstance(period, list)
        or len(period) != 2
        or not all(isinstance(y, int) and not isinstance(y, bool) for y in period)
        or not 0 <= period[0] <= period[1] <= 9999
    ):
        raise _damaged(_("its base period is not two years in order."))
    thresholds = record.get("quality_thresholds")
    if not isinstance(thresholds, dict) or not all(_is_number(v) for v in thresholds.values()):
        raise _damaged(_("its quality thresholds are missing."))
    qc_form = QCParamsForm(thresholds)
    if not qc_form.is_valid():
        raise _damaged(_("its quality thresholds are out of range."))
    qc = {k: qc_form.cleaned_data[k] for k in QCParamsForm.base_fields}

    chosen = record.get("indices")
    if not isinstance(chosen, dict) or not isinstance(chosen.get("params"), dict):
        raise _damaged(_("its index settings are missing."))
    custom = chosen["params"].get("custom")
    if custom is not None and not isinstance(custom, dict):
        raise _damaged(_("its custom index is not one."))
    title = chosen.get("plot_title", "")
    if not isinstance(title, str) or not all(
        isinstance(chosen.get(k, True), bool) for k in ("plots", "zip", "report")
    ):
        raise _damaged(_("its output options are not valid."))
    values = initial_from_params(
        chosen["params"],
        title,
        chosen.get("plots", True),
        chosen.get("zip", True),
        chosen.get("report", True),
    )
    unbound = IndexParamsForm(initial=values)
    data = {}
    for name, form_field in unbound.fields.items():
        value = unbound.get_initial_for_field(form_field, name)
        if isinstance(form_field, forms.BooleanField):
            if value:
                data[name] = "on"
        elif value is not None:
            if not isinstance(value, str | int | float) or isinstance(value, bool):
                raise _damaged(_("its index settings are not valid."))
            data[name] = value
    form = IndexParamsForm(data)
    if not form.is_valid():
        raise _damaged(_("its index settings are out of range."))
    cleaned = form.cleaned_data
    index_settings = workspace.settings_of(
        {
            "params": form.job_params(),
            "plot_title": cleaned["plot_title"],
            "plots": cleaned["plots"],
            "zip": cleaned["zip"],
            "report": cleaned["report"],
        }
    )
    return period[0], period[1], qc, index_settings


def check_breaks(record, files: dict[str, bytes]) -> tuple[dict, bytes | None]:
    """The saved break detection settings (none in format 1: the defaults), checked as
    its form checks them, and the station history file they name, checked against its
    SHA-256 and read: (``Workspace.break_detection``, the file or None)."""
    from climpact_web.stations import break_settings, breaks

    if record is None:
        if HISTORY in files:
            raise _damaged(
                _("%(name)s is in it, but its settings don't use it.") % {"name": HISTORY}
            )
        return {}, None
    if not isinstance(record, dict) or not isinstance(record.get("on"), bool):
        raise _damaged(_("its break detection settings are not valid."))
    lists = {}
    for key in ("methods", "variables", "series"):
        value = record.get(key)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise _damaged(_("its break detection settings are not valid."))
        lists[key] = value
    level, years = record.get("level"), record.get("min_years")
    if not _is_number(level) or not isinstance(years, int) or isinstance(years, bool):
        raise _damaged(_("its break detection settings are not valid."))
    data = {**lists, "level": str(float(level)), "min_years": str(years)}
    if record["on"]:
        data["on"] = "on"
    form = break_settings.BreakDetectionForm(data)
    if not form.is_valid():
        raise _damaged(_("its break detection settings are out of range."))
    cleaned = form.cleaned_data
    chosen = {
        "on": record["on"],
        "methods": [m for m in breaks.METHODS if m in cleaned["methods"]],
        "variables": [v for v in breaks.VARIABLES if v in cleaned["variables"]],
        "series": [f for f in breaks.FREQUENCIES if f in cleaned["series"]],
        "level": float(cleaned["level"]),
        "min_years": int(cleaned["min_years"]),
        "history": None,
    }
    saved = record.get("station_history")
    data = None
    if saved is not None:
        if (
            not isinstance(saved, dict)
            or saved.get("file") != HISTORY
            or not isinstance(saved.get("name"), str)
            or not isinstance(saved.get("sha256"), str)
            or not _SHA256.fullmatch(saved["sha256"])
            or HISTORY not in files
        ):
            raise _damaged(_("its station history file is missing."))
        data = files[HISTORY]
        if hashlib.sha256(data).hexdigest() != saved["sha256"]:
            raise _damaged(
                _("the station history file is not the one saved (its SHA-256 differs).")
            )
        history = break_settings.read_history(data, break_settings.safe_name(saved["name"]))
        if not history.ok:
            raise _damaged(_("its station history file cannot be read."))
        chosen["history"] = break_settings.history_record(history, data)
    elif HISTORY in files:
        raise _damaged(_("%(name)s is in it, but its settings don't use it.") % {"name": HISTORY})
    if chosen == {**breaks.DEFAULTS, "history": None}:
        return {}, None
    return chosen, data


def safe_file_name(name, fallback: str) -> str:
    """A saved station's original file name, safe to name a file on disk with."""
    base = check.plain_name(name) if isinstance(name, str) and name else None
    base = _UNSAFE_FILE.sub("_", base or "").strip(" ._")[:120]
    return base or fallback


def check_stations(records, files: dict[str, bytes]) -> list[SavedStation]:
    from climpact_web.stations.forms_indices import PARAM_FIELDS
    from climpact_web.stations.models import file_digest

    if not isinstance(records, list) or not records:
        raise _damaged(_("it lists no stations."))
    if len(records) > MAX_STATIONS:
        raise NotAWorkspaceFile(
            _("This workspace file has %(count)d stations; at most %(max)d can be opened.")
            % {"count": len(records), "max": MAX_STATIONS}
        )
    out, used = [], set()
    for i, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise _damaged(_("station %(n)d is not described.") % {"n": i})
        name = record.get("name")
        entry = record.get("file")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise _damaged(_("station %(n)d has no name.") % {"n": i})
        if not isinstance(entry, str) or entry not in files or entry in used:
            raise _damaged(_("the file of %(name)s is missing.") % {"name": name})
        used.add(entry)
        for key in ("latitude", "longitude"):
            if not _is_number(record.get(key)):
                raise _damaged(_("%(name)s has no %(what)s.") % {"name": name, "what": key})
        params = record.get("params") or {}
        if not isinstance(params, dict) or not all(
            k in PARAM_FIELDS and _is_number(v) for k, v in params.items()
        ):
            raise _damaged(_("the index values of %(name)s are not valid.") % {"name": name})
        data = files[entry]
        digest = record.get("sha256")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise _damaged(_("%(name)s has no SHA-256.") % {"name": name})
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if text is None or file_digest(text) != digest:
            raise _damaged(
                _("the file of %(name)s is not the one saved (its SHA-256 differs).")
                % {"name": name}
            )
        out.append(
            SavedStation(
                name=name.strip(),
                file=entry,
                file_name=safe_file_name(record.get("file_name"), entry.split("/", 1)[1]),
                data=data,
                latitude=float(record["latitude"]),
                longitude=float(record["longitude"]),
                params=dict(params),
                sample=record.get("sample") is True,
                use_results=record.get("use_results") is True,
            )
        )
    unknown = sorted(n for n in files if n.startswith(STATIONS_DIR) and n not in used)
    if unknown:
        raise NotAWorkspaceFile(
            _("This is not a workspace file that can be opened: %(problem)s")
            % {"problem": _("%(name)s is not part of a workspace file.") % {"name": unknown[0]}}
        )
    return out


def read(handle) -> Opened:
    """Read and check a workspace file (a binary file object); refuse it
    (:class:`NotAWorkspaceFile`) unless everything in it is in order."""
    files = unpack(handle)
    record = load_manifest(files[MANIFEST])
    check_version(record)
    name = record.get("name", "")
    if not isinstance(name, str) or len(name) > 100:
        raise _damaged(_("its name is not valid."))
    base_start, base_end, qc, index_settings = check_settings(record.get("settings"))
    break_detection, history = check_breaks(record["settings"].get("break_detection"), files)
    stations = check_stations(record.get("stations"), files)
    return Opened(
        name.strip(), base_start, base_end, qc, index_settings, stations, break_detection, history
    )


# ---- opening ------------------------------------------------------------------------------


def _unique_names(stations: list[SavedStation]) -> list[str]:
    """Each station's file name for Add stations, which names files uniquely."""
    names, taken = [], set()
    for station in stations:
        name = station.file_name
        stem, dot, suffix = name.rpartition(".")
        if not dot:
            stem, suffix = name, "txt"
        n = 1
        while name.casefold() in taken:
            n += 1
            name = f"{stem}_{n}.{suffix}"
        taken.add(name.casefold())
        names.append(name)
    return names


def staged_report(opened: Opened, names: list[str]) -> dict:
    """The report of Add stations' files waiting (``add_stations``) for the saved
    stations: each file read once, its metadata line (its location and own index values)
    and its name and location as typed, so the review table is the saved stations."""
    from climpact_web.stations import add_stations

    rows, edits, files = {}, {}, {}
    for i, (station, name) in enumerate(zip(opened.stations, names, strict=True), start=1):
        files[name] = add_stations.read_file(station.data)
        rows[name] = {
            "line": i,
            "latitude": station.latitude,
            "longitude": station.longitude,
            "params": station.params,
        }
        edits[name] = {
            "name": station.name,
            "latitude": repr(station.latitude),
            "longitude": repr(station.longitude),
        }
    report = {
        "files": files,
        "metadata": {
            "name": MANIFEST,
            "problems": [],
            "problem_count": 0,
            "warnings": [],
            "rows": rows,
        },
        "upload_problems": [],
        "edits": edits,
    }
    if any(s.sample for s in opened.stations):
        report["sample"] = True
    return report


def new_workspace(opened: Opened, owner: str) -> Workspace:
    """The workspace of a file, unsaved: its name and settings (none stored for defaults)."""
    from climpact_web.stations.forms import QC_DEFAULTS

    return Workspace(
        owner=owner,
        name=opened.name,
        base_start=opened.base_start,
        base_end=opened.base_end,
        qc_params={} if opened.qc_params == QC_DEFAULTS else opened.qc_params,
        index_settings=(
            {} if opened.index_settings == workspace.default_settings() else opened.index_settings
        ),
        break_detection=opened.break_detection,
    )


def open_into(request, opened: Opened) -> Workspace:
    """Rebuild a workspace from a file read by :func:`read`, for this browser: a new
    workspace with its name and settings, whose stations are added and calculated as Add
    stations adds them. Every station is reviewed first, as on Add stations, and the hosted
    limits are checked, so a refusal makes nothing."""
    from climpact_web.batch.models import BatchRun
    from climpact_web.core.limits import check_job_quotas
    from climpact_web.jobs.views import owner_token
    from climpact_web.stations import add_stations, calculation
    from climpact_web.stations.models import Step
    from climpact_web.stations.views_add import add_many, add_one, default_workers

    owner = owner_token(request)
    space = new_workspace(opened, owner)
    names = _unique_names(opened.stations)
    report = staged_report(opened, names)
    review = add_stations.review(report, space)
    if review.problem_rows:
        row = review.problem_rows[0]
        station = opened.stations[names.index(row.file)]
        raise NotAWorkspaceFile(
            _("%(name)s cannot be opened: %(problem)s")
            % {"name": station.name, "problem": row.status}
        )
    check_job_quotas(request)  # one change for the hosted limits: refused now, nothing made
    space.save()
    if opened.history is not None:  # before the checks, which use it (#367)
        from climpact_web.stations import break_settings

        break_settings.store_history(space, opened.history)
    run = None
    try:
        with transaction.atomic():
            run = BatchRun(workspace=space, owner=owner)
            run.workers = default_workers(len(names))
            run.save()
            run.save_files({n: s.data for n, s in zip(names, opened.stations, strict=True)})
            run.report = report
            run.save()
        rows = review.addable
        if len(rows) == 1:
            station = add_one(request, run, rows[0])
            if opened.stations[0].use_results:
                calculation.commit(request, station)
                station.advance_to(Step.INDICES)
                station.touch()
                station.save()
            return space
        change = add_many(request, run, rows)
        if space.qc_params:
            # A batch runs with R's default thresholds: each station is calculated again
            # with the workspace's, as part of the same change (calculation.refresh).
            for station in space.stations.all():
                station.advance_to(Step.INDICES)
                calculation.refresh(request, station, change)
    except BaseException:
        if not space.stations.exists():
            if run is not None:
                run.delete_files()
            space.delete_files()
            space.delete()
        raise
    return space


def read_upload(upload) -> Opened:
    """Read an uploaded workspace file (Django's ``UploadedFile``)."""
    upload.seek(0)
    head = upload.read(4)
    upload.seek(0)
    if head != b"PK\x03\x04":
        raise NotAWorkspaceFile(
            _(
                "This is not a zip file. A workspace file is the climpact_workspace.zip "
                "that Save file downloads."
            )
        )
    if upload.size is not None and upload.size > django_settings.MAX_UPLOAD_BYTES:
        raise NotAWorkspaceFile(
            _("This file is larger than %(mb)d MB, the most this site takes.")
            % {"mb": django_settings.MAX_UPLOAD_MB}
        )
    return read(upload.file if hasattr(upload, "file") else io.BytesIO(upload.read()))

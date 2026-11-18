"""Add stations (#233): one way into a workspace, for one file or many.

The files dropped on Add stations (station files, a batch metadata file, or a zip of
them) wait in a :class:`climpact_web.batch.models.BatchRun` of the workspace, its files
and metadata kept as a batch's are, until the user adds them or cancels. The review table
shows a row per station file, with its editable station name, latitude and longitude,
its period and days, its index settings and what reading it found. Every problem is found
in one pass (:func:`review`): files that cannot be read (with the line and what was
expected, :func:`~climpact_web.stations.station_file.inspect_station_bytes`), a missing
latitude or longitude, a name that is missing or given twice, a metadata value out of
range, a base period the data do not reach; repeated dates are a warning, not a problem.

Reading a file is the slow part, so each file is read once, when it arrives
(:func:`read_files`), and what was found is kept in the run's ``report``:

``files``
    ``{name: {"ok", "problems", "problem_count", "warnings", "repeats", "summary"}}``,
    in the order the files came.
``metadata``
    The metadata file's name, its problems and warnings, and its stations by file:
    ``{"name", "problems", "problem_count", "warnings", "rows": {file: {"line",
    "latitude", "longitude", "params"}}}``; empty without one.
``upload_problems``
    Problems with the uploads themselves (a zip that cannot be opened, two files with one
    name).
``edits``
    What the user typed in the table: ``{file: {"name", "latitude", "longitude"}}``.

"Add N stations and check them" adds the complete rows (:func:`addable`): one becomes a
station of its own, checked and calculated with ``station`` jobs as before
(:func:`climpact_web.stations.calculation.bring_up_to_date`); several run as a batch that
fills the workspace (:mod:`climpact_web.batch.fill`), each station's quality checks queued
beside it. See ``stations/views_add.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from climpact_web.batch import check
from climpact_web.core import numbers

# The sample station's own name (#219): the file is "sydney_observatory_hill_1936-2015.txt".
SAMPLE_NAME = "Sydney Observatory Hill"
SAMPLE_FILE = "sydney_observatory_hill_1936-2015.txt"
SAMPLE_COORDINATES = (-33.86, 151.21)  # reference/stations.csv

# A row's state: ready to add; needs something typed (a name or a coordinate); has a
# problem in the files that only a new file fixes (unread, missing, a metadata value).
READY, NEEDS, BLOCKED = "ready", "needs", "blocked"

# A trailing year range in a file name: "sydney_observatory_hill_1936-2015".
_YEARS = re.compile(r"[\s_-]*\(?\d{4}\s*[-–_]\s*\d{4}\)?$")


def tidy_name(file_name: str) -> str:
    """A station name from a file name, for the review table to start from (#219): no
    extension, no trailing year range, underscores as spaces, each lower-case word
    capitalised. ``moruya_heads_069018.txt`` -> ``Moruya Heads 069018``. The sample file
    gives the sample station's name."""
    if file_name == SAMPLE_FILE:
        return SAMPLE_NAME
    stem = check.plain_name(file_name) or file_name
    stem = PurePosixPath(stem).stem if "." in stem else stem
    stem = _YEARS.sub("", stem) or stem
    words = re.sub(r"[_\s]+", " ", stem).strip().split(" ")
    name = " ".join(w.capitalize() if w.islower() else w for w in words if w)
    return name[:100]


# ---- reading the files, once --------------------------------------------------------------


def _missing_percent(summary: dict) -> float:
    """The share of all values missing, over the three variables."""
    variables = summary.get("variables") or []
    days = summary.get("days") or 0
    if not variables or not days:
        return 0.0
    missing = sum(v["missing"] for v in variables)
    return round(100 * missing / (days * len(variables)), 1)


def read_file(raw: bytes) -> dict:
    """What reading one station file found, as the report keeps it."""
    from climpact_web.stations.station_file import inspect_station_bytes

    inspection = inspect_station_bytes(raw)
    out = {
        "ok": inspection.ok,
        "problems": [
            {"message": p.message, "line": p.line, "text": p.text, "short": p.short}
            for p in inspection.problems
        ],
        "problem_count": inspection.problem_count,
        "warnings": list(inspection.warnings),
        "repeats": inspection.repeats,
        "summary": None,
    }
    if inspection.summary:
        summary = check.short_summary(inspection.summary)
        summary["missing_percent"] = _missing_percent(inspection.summary)
        out["summary"] = summary
    return out


def read_metadata(name: str, raw: bytes) -> dict:
    """A metadata file's stations, by the file each names, and its problems."""
    result = check.BatchCheck()
    stations = check.check_metadata(raw, result)
    rows = {}
    for s in stations:
        rows[s.station_file] = {
            "line": s.line,
            "latitude": s.latitude,
            "longitude": s.longitude,
            "params": s.params,
        }
    return {
        "name": name,
        "problems": result.metadata_problems,
        "problem_count": result.metadata_problem_count,
        "warnings": result.metadata_warnings,
        "rows": rows,
    }


def read_files(
    report: dict, uploads: list[tuple[str, bytes]]
) -> tuple[dict, dict[str, bytes], tuple[str, bytes] | None]:
    """Add ``uploads`` (loose files and zips, :func:`climpact_web.batch.check.unpack`) to
    the report: each station file read once, replacing one of the same name; a metadata
    file, loose or in a zip, replacing the one before. Returns the report, the station
    files to keep by name, and the metadata file (its name and bytes) when one came."""
    loose_metadata = []
    station_uploads = []
    for name, data in uploads:
        if not name.lower().endswith(".zip") and check.looks_like_metadata(data):
            loose_metadata.append((check.plain_name(name) or "metadata.txt", data))
        else:
            station_uploads.append((name, data))
    unpacked = check.unpack(station_uploads)
    report = dict(report)
    files = dict(report.get("files") or {})
    for name, data in unpacked.files.items():
        files.pop(name, None)  # a replaced file moves to the end, where it was added
        files[name] = read_file(data)
    report["files"] = files
    found = loose_metadata + ([unpacked.metadata] if unpacked.metadata else [])
    problems = list(unpacked.problems)
    if len(found) > 1:
        problems.append(
            _("%(count)d metadata files were added (%(names)s); the last one is used.")
            % {"count": len(found), "names": ", ".join(n for n, _ in found)}
        )
    metadata = found[-1] if found else None
    if metadata is not None:
        report["metadata"] = read_metadata(*metadata)
    report["upload_problems"] = problems
    return report, unpacked.files, metadata


# ---- the review table ------------------------------------------------------------------


@dataclass
class Row:
    """One station file in the review table."""

    file: str
    name: str
    latitude: str  # as typed, or the metadata's
    longitude: str
    period: str = ""
    days: str = ""
    settings: str = ""
    params: dict = field(default_factory=dict)  # the metadata line's index values
    state: str = READY
    status: str = ""  # the Read column
    status_kind: str = "ok"  # ok, warning or problem: the Read column's colour
    problems: list[dict] = field(default_factory=list)  # every problem, with its line
    hidden_problems: int = 0
    warnings: list[str] = field(default_factory=list)
    name_error: str = ""
    latitude_error: str = ""
    longitude_error: str = ""
    kind: str = ""  # what blocks it, for the line under the table
    summary: dict | None = None
    metadata_line: int | None = None
    ready_status: str = ""  # the Read column once the typed values are fine
    readable: bool = True
    values: dict = field(default_factory=dict)  # the cleaned name and coordinates

    @property
    def addable(self) -> bool:
        return self.state == READY


@dataclass
class Review:
    rows: list[Row]
    metadata: dict
    upload_problems: list[str]

    @property
    def addable(self) -> list[Row]:
        return [r for r in self.rows if r.addable]

    @property
    def problem_rows(self) -> list[Row]:
        return [r for r in self.rows if not r.addable]

    @property
    def noted_rows(self) -> list[Row]:
        """The rows with a problem or a warning to list in full under the table."""
        return [r for r in self.rows if r.problems or r.warnings]

    @property
    def station_files(self) -> int:
        return sum(1 for r in self.rows if r.readable)

    def summary(self) -> str:
        """The line under the table: what stands between the rows and being added."""
        return problem_sentence(self.problem_rows, len(self.addable))


def _coordinate_text(value) -> str:
    """A metadata coordinate as a cell starts with it: the file's digits, typed text's
    hyphen-minus (numbers.py: text the user types keeps it)."""
    if value is None:
        return ""
    return f"{value:g}"


def parse_coordinate(text: str) -> str:
    """A typed coordinate as the form reads it: U+2212 and a decimal comma accepted."""
    text = (text or "").strip().replace(numbers.MINUS, "-").replace("–", "-")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    return text


def _settings_label(params: dict, shared: dict) -> str:
    """The Index settings column: "Defaults", or the metadata's values that differ from
    the workspace's ("Custom (wsdin 4)")."""
    if not params:
        return _("Defaults")
    names = {v: k for k, v in check.PARAM_FIELDS.items()}
    differ = [
        f"{names[k]} {numbers.number(v, 2) if isinstance(v, float) else v}"
        for k, v in params.items()
        if k in names and shared.get(k) != v
    ]
    if not differ:
        return _("Defaults")
    if len(differ) <= 2:
        return _("Custom (%(values)s)") % {"values": ", ".join(differ)}
    return ngettext("Custom (%(count)d value)", "Custom (%(count)d values)", len(differ)) % {
        "count": len(differ)
    }


def _read_status(found: dict, base_short: bool, warnings: int) -> str:
    """The Read column of a file that was read: what to know first (repeated dates, a
    base period the data barely reach, other warnings), else its missing data."""
    summary = found["summary"] or {}
    repeats = found.get("repeats") or 0
    if repeats:
        return ngettext(
            "Read · %(count)d repeated date; checks will list it",
            "Read · %(count)d repeated dates; checks will list them",
            repeats,
        ) % {"count": repeats}
    if base_short:
        return _("Read · under a year in the base period")
    percent = summary.get("missing_percent", 0.0)
    shown = numbers.fixed(percent, 1) if percent >= 0.1 or not percent else "<0.1"
    text = _("Read · %(percent)s%% missing") % {"percent": shown}
    if warnings:
        text += " · " + ngettext(
            "%(count)d thing to check", "%(count)d things to check", warnings
        ) % {"count": warnings}
    return text


def review(report: dict, space) -> Review:
    """The review table of the files in ``report`` for a workspace ``space``: every row
    and every problem, in one pass."""
    from climpact_web.stations.forms import MetadataForm
    from climpact_web.stations.workspace import workspace_settings

    shared = workspace_settings(space)["params"]
    metadata = report.get("metadata") or {}
    listed = metadata.get("rows") or {}
    edits = report.get("edits") or {}
    files = report.get("files") or {}
    rows: list[Row] = []

    for name, found in files.items():
        entry = listed.get(name) or {}
        typed = edits.get(name) or {}
        row = Row(
            file=name,
            name=typed["name"] if "name" in typed else tidy_name(name),
            latitude=typed.get("latitude", _coordinate_text(entry.get("latitude"))),
            longitude=typed.get("longitude", _coordinate_text(entry.get("longitude"))),
            params=entry.get("params") or {},
            metadata_line=entry.get("line"),
            summary=found.get("summary"),
            warnings=list(found.get("warnings") or []),
        )
        if name == SAMPLE_FILE and "latitude" not in typed and not entry:
            row.latitude, row.longitude = (_coordinate_text(v) for v in SAMPLE_COORDINATES)
        row.settings = _settings_label(row.params, shared)
        if not found["ok"]:
            row.readable = False
            row.state, row.kind, row.status_kind = BLOCKED, "unread", "problem"
            row.problems = found["problems"]
            row.hidden_problems = found["problem_count"] - len(found["problems"])
            first = found["problems"][0] if found["problems"] else {}
            row.status = _("Not read: %(problem)s") % {
                "problem": first.get("short") or first.get("message", "")
            }
            if found["problem_count"] > 1:
                row.status += " " + ngettext(
                    "(and %(count)d more)",
                    "(and %(count)d more)",
                    found["problem_count"] - 1,
                ) % {"count": found["problem_count"] - 1}
            row.settings = "–"
            rows.append(row)
            continue
        summary = found["summary"] or {}
        if summary:
            row.period = f"{summary['first_year']}–{summary['last_year']}"
            row.days = numbers.grouped(summary["days"])
        for message in check.parameter_problems(row.params):
            row.problems.append({"message": message, "line": row.metadata_line, "text": ""})
        form = MetadataForm(
            {
                "station_name": row.name,
                "latitude": parse_coordinate(row.latitude),
                "longitude": parse_coordinate(row.longitude),
                "base_start": space.base_start,
                "base_end": space.base_end,
            },
            summary=summary or None,
        )
        valid = form.is_valid()
        row.name_error = " ".join(form.errors.get("station_name", []))
        row.latitude_error = " ".join(form.errors.get("latitude", []))
        row.longitude_error = " ".join(form.errors.get("longitude", []))
        for message in form.errors.get("base_end", []):
            row.problems.append({"message": message, "line": None, "text": ""})
        for messages in form.warnings.values():
            row.warnings.extend(messages)
        row.ready_status = _read_status(
            found, bool(form.warnings.get("base_period")), len(row.warnings)
        )
        if valid:
            keys = ("station_name", "latitude", "longitude")
            row.values = {k: form.cleaned_data[k] for k in keys}
        _settle(row)
        rows.append(row)

    for name, entry in listed.items():
        if name in files:
            continue
        row = Row(
            file=name,
            name="",
            latitude=_coordinate_text(entry.get("latitude")),
            longitude=_coordinate_text(entry.get("longitude")),
            params=entry.get("params") or {},
            metadata_line=entry.get("line"),
            readable=False,
            state=BLOCKED,
            kind="missing",
            status_kind="problem",
        )
        row.settings = "–"
        similar = check.similar_file(name, files)
        if similar:
            row.status = _("Not added: the metadata names this file, but %(similar)s came") % {
                "similar": similar
            }
        else:
            row.status = _("Not added: the metadata names this file, and it did not come")
        row.problems = [{"message": row.status, "line": entry.get("line"), "text": ""}]
        rows.append(row)

    _repeated_names(rows)
    return Review(rows, metadata, list(report.get("upload_problems") or []))


def _settle(row: Row) -> None:
    """A read row's state, Read column and what blocks it, from its errors."""
    if row.problems:
        row.state, row.status_kind = BLOCKED, "problem"
        row.kind = "base" if row.metadata_line is None else "value"
        row.status = row.problems[0]["message"]
        return
    if row.latitude_error or row.longitude_error or row.name_error:
        row.state, row.status_kind = NEEDS, "problem"
        lat_missing = not parse_coordinate(row.latitude)
        lon_missing = not parse_coordinate(row.longitude)
        if row.name_error:
            row.kind = "name"
            row.status = _("Station name needed") if not row.name.strip() else row.name_error
        elif lat_missing and lon_missing:
            row.kind, row.status = "both", _("Latitude and longitude needed")
        elif lat_missing:
            row.kind, row.status = "latitude", _("Latitude needed")
        elif lon_missing:
            row.kind, row.status = "longitude", _("Longitude needed")
        else:
            row.kind = "range"
            row.status = row.latitude_error or row.longitude_error
        return
    row.state = READY
    row.status = row.ready_status
    row.status_kind = "warning" if row.warnings else "ok"


def _repeated_names(rows: list[Row]) -> None:
    """Two rows to add under one name: both wait for one to be renamed, as each station's
    results are named after it."""
    seen: dict[str, list[Row]] = {}
    for row in rows:
        if row.state != BLOCKED and row.name.strip():
            seen.setdefault(row.name.strip().casefold(), []).append(row)
    for group in seen.values():
        if len(group) < 2:
            continue
        for row in group:
            row.state, row.status_kind, row.kind = NEEDS, "problem", "repeated"
            row.name_error = _("Another file has this station name.")
            row.status = _("Two files have this station name")


# ---- the line under the table -------------------------------------------------------------


def problem_sentence(problem_rows: list[Row], ready: int) -> str:
    """ "2 problems to fix before these stations can be added: a missing latitude and an
    unreadable file." Or, with nothing to fix, how many will be added."""
    if not problem_rows:
        if not ready:
            return ""
        return ngettext(
            "%(count)d station is ready to add.", "%(count)d stations are ready to add.", ready
        ) % {"count": ready}
    counts: dict[str, int] = {}
    for row in problem_rows:
        counts[row.kind] = counts.get(row.kind, 0) + 1
    parts = [_kind_words(kind, n) for kind, n in counts.items()]
    if len(parts) == 1:
        listed = parts[0]
    else:
        listed = _("%(first)s and %(last)s") % {"first": ", ".join(parts[:-1]), "last": parts[-1]}
    total = len(problem_rows)
    if ready:
        return ngettext(
            "%(count)d problem to fix before these stations can be added: %(list)s. "
            "The others can be added now.",
            "%(count)d problems to fix before these stations can be added: %(list)s. "
            "The others can be added now.",
            total,
        ) % {"count": total, "list": listed}
    return ngettext(
        "%(count)d problem to fix before these stations can be added: %(list)s.",
        "%(count)d problems to fix before these stations can be added: %(list)s.",
        total,
    ) % {"count": total, "list": listed}


def _kind_words(kind: str, n: int) -> str:
    words = {
        "unread": ngettext("an unreadable file", "%(count)d unreadable files", n),
        "missing": ngettext("a missing file", "%(count)d missing files", n),
        "latitude": ngettext("a missing latitude", "%(count)d missing latitudes", n),
        "longitude": ngettext("a missing longitude", "%(count)d missing longitudes", n),
        "both": ngettext(
            "a missing latitude and longitude", "%(count)d missing latitudes and longitudes", n
        ),
        "range": ngettext("a coordinate out of range", "%(count)d coordinates out of range", n),
        "name": ngettext("a missing station name", "%(count)d missing station names", n),
        "repeated": ngettext(
            "a station name given twice", "%(count)d station names given twice", n
        ),
        "value": ngettext(
            "a metadata value out of range", "%(count)d metadata values out of range", n
        ),
        "base": ngettext(
            "a file outside the base period", "%(count)d files outside the base period", n
        ),
    }
    return words.get(kind, ngettext("a problem", "%(count)d problems", n)) % {"count": n}


def button_label(count: int) -> str:
    return ngettext(
        "Add %(count)d station and check it", "Add %(count)d stations and check them", count
    ) % {"count": count}

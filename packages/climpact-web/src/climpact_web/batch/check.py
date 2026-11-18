"""Checking a batch before it runs (#80): the metadata file, then each station it lists.

The core (:func:`climpact.batch.read_batch_metadata`) stays the authority on what the
metadata file means, but its errors are written for the command line and it stops at the
first. This module walks the file first with the same rules (whitespace-separated
fields, ``#`` comments and blank lines skipped, the first line a header) and reports every
problem in plain language with its **line number** and the line itself, as the station
file check of step 1 does (:mod:`climpact_web.stations.station_file`).

Each station is then *ready*, *missing* (no file of that name was uploaded) or *invalid*
(its file has problems, its name cannot be used, or its location or index parameters are
out of range), with the reasons. Station files are checked by the single-station check
(:func:`~climpact_web.stations.station_file.inspect_station_bytes`), so a file accepted
here is accepted in step 1 and the other way round.

Uploads may be loose files or zip files holding them (and the metadata file); see
:func:`unpack`.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import PurePosixPath

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from climpact_web.jobs.forms import STATION_NAME
from climpact_web.stations.station_file import (
    MAX_PROBLEMS_SHOWN,
    decode,
    inspect_station_bytes,
    shorten,
)

# The metadata columns, as climpact.batch.COLUMNS (R's read.file.list.metadata).
COLUMNS = (
    "station_file",
    "latitude",
    "longitude",
    "wsdin",
    "csdin",
    "Tb_HDD",
    "Tb_CDD",
    "Tb_GDD",
    "rxnday",
    "rnnmm",
    "txtn",
    "SPEI",
)
INTEGER_COLUMNS = {"wsdin", "csdin", "rxnday", "txtn", "SPEI"}
# The metadata columns as IndexParams fields (climpact.batch.read_batch_metadata).
PARAM_FIELDS = {
    "wsdin": "wsdi_days",
    "csdin": "csdi_days",
    "Tb_HDD": "hdd_base",
    "Tb_CDD": "cdd_base",
    "Tb_GDD": "gdd_base",
    "rxnday": "rx_days",
    "rnnmm": "rnnmm",
    "txtn": "txtn_days",
    "SPEI": "spei_months",
}

MAX_FILES = 500  # station files in one batch
MAX_UNPACKED_BYTES = 500 * 1024 * 1024  # all files of the zips, uncompressed


def column_label(column: str) -> str:
    """A metadata column as the user guide describes it, with its name in the file."""
    labels = {
        "station_file": _("station file"),
        "latitude": _("latitude"),
        "longitude": _("longitude"),
        "wsdin": _("wsdin (days for WSDI)"),
        "csdin": _("csdin (days for CSDI)"),
        "Tb_HDD": _("Tb_HDD (base temperature for heating degree days)"),
        "Tb_CDD": _("Tb_CDD (base temperature for cooling degree days)"),
        "Tb_GDD": _("Tb_GDD (base temperature for growing degree days)"),
        "rxnday": _("rxnday (days for Rxnday)"),
        "rnnmm": _("rnnmm (millimetres for Rnnmm)"),
        "txtn": _("txtn (days for TXdTNd and TXbdTNbd)"),
        "SPEI": _("SPEI (months for the custom SPEI and SPI)"),
    }
    return labels[column]


@dataclass
class Problem:
    message: str
    line: int | None = None
    text: str = ""


@dataclass
class StationCheck:
    """One row of the metadata file, and what was found for it."""

    name: str
    station_file: str
    line: int
    latitude: float
    longitude: float
    params: dict  # IndexParams fields from the metadata row
    status: str = "ready"  # "ready", "missing" or "invalid"
    problems: list[dict] = field(default_factory=list)
    problem_count: int = 0
    warnings: list[str] = field(default_factory=list)
    summary: dict | None = None  # period and missing data, from the file

    def add(self, message: str, line: int | None = None, text: str = "") -> None:
        self.problem_count += 1
        if len(self.problems) < MAX_PROBLEMS_SHOWN:
            self.problems.append(asdict(Problem(message, line, text)))


@dataclass
class BatchCheck:
    """Everything the check page shows: as JSON in ``BatchRun.check``."""

    metadata_problems: list[dict] = field(default_factory=list)
    metadata_problem_count: int = 0
    metadata_warnings: list[str] = field(default_factory=list)
    stations: list[StationCheck] = field(default_factory=list)
    extra_files: list[str] = field(default_factory=list)
    upload_problems: list[str] = field(default_factory=list)

    def add(self, message: str, line: int | None = None, text: str = "") -> None:
        self.metadata_problem_count += 1
        if len(self.metadata_problems) < MAX_PROBLEMS_SHOWN:
            self.metadata_problems.append(asdict(Problem(message, line, text)))

    @property
    def metadata_ok(self) -> bool:
        return not self.metadata_problem_count

    def to_json(self) -> dict:
        return asdict(self)


# ---- Uploads ----------------------------------------------------------------------------


@dataclass
class Unpacked:
    """The uploaded files by name, the metadata file found in a zip (if any), and
    problems with the uploads themselves."""

    files: dict[str, bytes] = field(default_factory=dict)
    metadata: tuple[str, bytes] | None = None
    problems: list[str] = field(default_factory=list)


def plain_name(name: str) -> str | None:
    """A file name without any folder, or None when it cannot be a station file name
    (empty, hidden, or a folder)."""
    base = PurePosixPath(name.replace("\\", "/")).name
    if not base or base.startswith(".") or len(base) > 255:
        return None
    return base


def looks_like_metadata(raw: bytes) -> bool:
    """A batch metadata file: a first line of 12 column names starting ``station_file``."""
    text = decode(raw[:4096])
    if text is None:
        return False
    for line in text.split("\n"):
        fields = line.split("#", 1)[0].split()
        if fields:
            return len(fields) == len(COLUMNS) and fields[0].lower() == "station_file"
    return False


def unpack(uploads: list[tuple[str, bytes]]) -> Unpacked:
    """Station files from loose files and zip files, by name without folders.

    A zip may hold the station files in any folders, and the metadata file too (the file
    whose first line is the metadata header). Hidden files and macOS's ``__MACOSX``
    folders are ignored. A name given twice keeps the last file and says so."""
    out = Unpacked()
    unpacked_bytes = 0
    metadata_found: list[tuple[str, bytes]] = []

    def add(name: str, data: bytes, origin: str = "") -> None:
        base = plain_name(name)
        if base is None:
            return
        if base in out.files:
            out.problems.append(
                _("Two files are named %(name)s; the last one is used.") % {"name": base}
            )
        if len(out.files) >= MAX_FILES and base not in out.files:
            if len(out.files) == MAX_FILES:
                out.problems.append(
                    _("Only the first %(count)d files are used.") % {"count": MAX_FILES}
                )
            return
        out.files[base] = data

    for name, data in uploads:
        if data[:4] == b"PK\x03\x04" and name.lower().endswith(".zip"):
            try:
                archive = zipfile.ZipFile(BytesIO(data))
                infos = archive.infolist()
            except zipfile.BadZipFile:
                out.problems.append(
                    _("%(name)s is not a zip file that can be opened.") % {"name": name}
                )
                continue
            for info in infos:
                path = info.filename
                if info.is_dir() or path.startswith("__MACOSX/") or plain_name(path) is None:
                    continue
                unpacked_bytes += info.file_size
                if unpacked_bytes > MAX_UNPACKED_BYTES:
                    out.problems.append(
                        _(
                            "%(name)s holds more data than a batch can use; the rest of it "
                            "is left out."
                        )
                        % {"name": name}
                    )
                    break
                try:
                    content = archive.read(info)
                except (zipfile.BadZipFile, NotImplementedError, RuntimeError):
                    out.problems.append(
                        _("%(file)s in %(name)s could not be read (damaged or encrypted).")
                        % {"file": path, "name": name}
                    )
                    continue
                if looks_like_metadata(content):
                    metadata_found.append((plain_name(path), content))
                else:
                    add(path, content)
        else:
            add(name, data)

    if len(metadata_found) == 1:
        out.metadata = metadata_found[0]
    elif metadata_found:
        out.problems.append(
            _(
                "The zip holds more than one metadata file (%(names)s). Choose the one to use "
                "in the metadata box."
            )
            % {"names": ", ".join(n for n, _ in metadata_found)}
        )
    return out


# ---- The metadata file ------------------------------------------------------------------


def _number(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value == value and abs(value) != float("inf") else None


def check_metadata(raw: bytes, result: BatchCheck) -> list[StationCheck]:
    """The stations of the metadata file, adding a problem for every line the core could
    not read (R's ``read.table`` would stop the whole batch on any of them)."""
    if not raw.strip():
        result.add(_("The metadata file is empty."))
        return []
    text = decode(raw)
    if text is None:
        result.add(
            _(
                "The metadata file is not a text file. If it is a spreadsheet, save it as "
                "text (tab-delimited) with the 12 columns of the template."
            )
        )
        return []
    rows = []
    for number, line in enumerate(text.split("\n"), start=1):
        fields = line.split("#", 1)[0].split()
        if fields:
            rows.append((number, line, fields))
    if not rows:
        result.add(_("The metadata file is empty."))
        return []
    header_line, header_text, header = rows[0]
    if len(header) == len(COLUMNS) and _number(header[1]) is not None:
        result.metadata_warnings.append(
            _(
                "Line %(line)d looks like a station, not the line of column names. The "
                "first line is always read as column names, so this station is left out, "
                "as in Climpact for R. Add the column names as the first line to include it."
            )
            % {"line": header_line}
        )
    if len(rows) == 1:
        result.add(_("The metadata file has the line of column names but no stations."))
        return []

    stations = []
    for number, line, fields in rows[1:]:
        if len(fields) != len(COLUMNS):
            message = ngettext(
                "Line %(line)d has %(count)d value; each line needs 12: the station file, "
                "latitude, longitude, wsdin, csdin, Tb_HDD, Tb_CDD, Tb_GDD, rxnday, rnnmm, "
                "txtn and SPEI.",
                "Line %(line)d has %(count)d values; each line needs 12: the station file, "
                "latitude, longitude, wsdin, csdin, Tb_HDD, Tb_CDD, Tb_GDD, rxnday, rnnmm, "
                "txtn and SPEI.",
                len(fields),
            ) % {"line": number, "count": len(fields)}
            if "," in line:
                message += " " + _("Separate the values with spaces or tabs, not commas.")
            result.add(message, number, shorten(line))
            continue
        values = {}
        for column, value in zip(COLUMNS[1:], fields[1:], strict=True):
            number_value = _number(value)
            if number_value is None:
                result.add(
                    _("Line %(line)d: “%(value)s” in the %(column)s column is not a number.")
                    % {"line": number, "value": value[:20], "column": column_label(column)},
                    number,
                    shorten(line),
                )
                break
            if column in INTEGER_COLUMNS and not number_value.is_integer():
                result.add(
                    _("Line %(line)d: %(column)s must be a whole number, not %(value)s.")
                    % {"line": number, "value": value[:20], "column": column_label(column)},
                    number,
                    shorten(line),
                )
                break
            values[column] = int(number_value) if column in INTEGER_COLUMNS else number_value
        else:
            from climpact.batch import strip_file_extension

            stations.append(
                StationCheck(
                    name=strip_file_extension(fields[0]),
                    station_file=fields[0],
                    line=number,
                    latitude=values["latitude"],
                    longitude=values["longitude"],
                    params={PARAM_FIELDS[c]: values[c] for c in PARAM_FIELDS},
                )
            )

    seen: dict[str, StationCheck] = {}
    for station in stations:
        first = seen.setdefault(station.name, station)
        if first is not station:
            result.add(
                _(
                    "Lines %(first)d and %(line)d both give the station name “%(name)s” "
                    "(%(file1)s and %(file2)s). Each station's results go in a folder named "
                    "after it, so each needs its own name."
                )
                % {
                    "first": first.line,
                    "line": station.line,
                    "name": station.name,
                    "file1": first.station_file,
                    "file2": station.station_file,
                },
                station.line,
            )
    if not result.metadata_ok:
        return []
    if not stations:
        result.add(_("The metadata file has the line of column names but no stations."))
    return stations


# ---- Each station -----------------------------------------------------------------------


def check_parameters(station: StationCheck) -> None:
    """R's ``validate_climdexInputParams`` and the location ranges, in plain language.
    In R a bad parameter stops the whole batch; here it stops only its station."""
    p = station.params
    if not -90 <= station.latitude <= 90:
        station.add(
            _("Latitude %(value)s is outside -90 to 90.") % {"value": f"{station.latitude:g}"},
            station.line,
        )
    if not -180 <= station.longitude <= 180:
        station.add(
            _("Longitude %(value)s is outside -180 to 180.") % {"value": f"{station.longitude:g}"},
            station.line,
        )
    for message in parameter_problems(p):
        station.add(message, station.line)
    if station.latitude == 0:
        station.warnings.append(
            _(
                "Latitude 0 is treated as the Southern Hemisphere (as in Climpact for R), "
                "which decides the season used for the growing season length and heatwaves."
            )
        )


def parameter_problems(p: dict) -> list[str]:
    """R's ``validate_climdexInputParams`` for a metadata line's index values (IndexParams
    fields), in plain language; none for values not given."""
    rules = [
        ("wsdin", lambda v: not 1 <= v <= 10, _("%(column)s must be between 1 and 10.")),
        ("csdin", lambda v: not 1 <= v <= 10, _("%(column)s must be between 1 and 10.")),
        ("rxnday", lambda v: v < 1, _("%(column)s must be 1 or more.")),
        ("txtn", lambda v: v < 1, _("%(column)s must be 1 or more.")),
        ("rnnmm", lambda v: v < 0, _("%(column)s must be 0 or more.")),
        ("SPEI", lambda v: v < 1, _("%(column)s must be 1 or more.")),
    ]
    out = []
    for column, bad, message in rules:
        value = p.get(PARAM_FIELDS[column])
        if value is not None and bad(value):
            out.append(
                (message % {"column": column_label(column)})
                + " "
                + _("It is %(value)s.") % {"value": f"{value:g}"}
            )
    return out


def check_name(station: StationCheck) -> bool:
    if "/" in station.station_file or "\\" in station.station_file:
        station.add(
            _(
                "“%(file)s” is a folder path. Give only the file's name, e.g. "
                "%(example)s, and upload the file."
            )
            % {
                "file": station.station_file,
                "example": PurePosixPath(station.station_file.replace("\\", "/")).name,
            },
            station.line,
        )
        return False
    if not re.match(STATION_NAME, station.name):
        station.add(
            _(
                "The station name “%(name)s” (the file name without its extension) cannot "
                "be used: use letters, digits, spaces and . ( ) - _ only, not starting with "
                "a dot. Rename the file and the line in the metadata file."
            )
            % {"name": station.name},
            station.line,
        )
        return False
    return True


def similar_file(name: str, files: dict[str, bytes]) -> str | None:
    """An uploaded file the user may have meant: the same name in other capitals, or the
    same name with another extension."""
    lower = name.lower()
    stem = PurePosixPath(lower).stem
    for candidate in files:
        if candidate.lower() == lower:
            return candidate
    for candidate in files:
        if PurePosixPath(candidate.lower()).stem == stem:
            return candidate
    return None


def short_summary(summary: dict) -> dict:
    """What the check page shows of a station's data (and the base period check needs)."""
    keys = ("first_date", "last_date", "first_year", "last_year", "days")
    out = {k: summary[k] for k in keys}
    out["missing"] = {v["key"]: v["percent_missing"] for v in summary["variables"]}
    return out


def check_station(station: StationCheck, files: dict[str, bytes]) -> None:
    if not check_name(station):
        station.status = "invalid"
        return
    check_parameters(station)
    raw = files.get(station.station_file)
    if raw is None:
        if station.problem_count:
            station.status = "invalid"
            return
        station.status = "missing"
        similar = similar_file(station.station_file, files)
        if similar:
            station.add(
                _(
                    "No file named %(file)s was uploaded, but %(similar)s was. Names must "
                    "match the metadata file exactly, including capitals and the extension."
                )
                % {"file": station.station_file, "similar": similar}
            )
        else:
            station.add(_("No file named %(file)s was uploaded.") % {"file": station.station_file})
        return
    inspection = inspect_station_bytes(raw)
    for problem in inspection.problems:
        station.add(problem.message, problem.line, problem.text)
    station.problem_count += inspection.hidden_problems
    station.warnings.extend(inspection.warnings)
    if inspection.summary:
        station.summary = short_summary(inspection.summary)
    station.status = "invalid" if station.problem_count else "ready"


def check_batch(metadata: bytes | None, files: dict[str, bytes]) -> BatchCheck:
    """Check a batch: the metadata file and every station it lists."""
    result = BatchCheck()
    if metadata is None:
        result.add(_("Choose the batch metadata file."))
        stations = []
    else:
        stations = check_metadata(metadata, result)
    for station in stations:
        check_station(station, files)
    result.stations = stations
    listed = {s.station_file for s in stations}
    result.extra_files = sorted(name for name in files if name not in listed)
    return result


def ready_stations(check: dict) -> list[dict]:
    return [s for s in check.get("stations", []) if s["status"] == "ready"]


def metadata_text(stations: list[dict]) -> str:
    """A metadata file in R's format (tab-separated, R's header) for these stations."""
    from_fields = {v: k for k, v in PARAM_FIELDS.items()}
    lines = ["\t".join(COLUMNS)]
    for s in stations:
        values = {from_fields[k]: v for k, v in s["params"].items()}
        row = [s["station_file"], _text(s["latitude"]), _text(s["longitude"])]
        row += [_text(values[c]) for c in COLUMNS[3:]]
        lines.append("\t".join(row))
    return "\n".join(lines) + "\n"


def _text(value: float | int) -> str:
    """A number as text that reads back the same (``repr``), without a needless ``.0``."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return repr(value)

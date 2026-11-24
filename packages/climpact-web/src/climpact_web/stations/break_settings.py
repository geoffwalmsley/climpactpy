"""Break detection's settings (#367, the BreakSettings board).

Break detection (#365, :mod:`.breaks`) runs with each station's checks, with the
workspace's settings (``Workspace.break_detection``): whether it is on, the tests, the
variables and series, the significance level, the shortest segment and the station history
file. Workspace settings lists it as its fourth item, summed up in one line
(:func:`summary`); its Edit opens :class:`BreakDetectionForm` on a page of its own
(``views_workspace.break_detection``). The other fields keep their values while detection
is off, so turning it back on restores them.

The station history file is read when it is chosen (:func:`read_history`, by the rules of
the core's ``read_station_history``, without importing the core, which takes seconds to
load): its events and stations, the first rows and the workspace's stations it has none
for, so a station name that doesn't match is visible; or refused with the line that is
wrong. Every line is checked, not only the lines of the workspace's stations, since the
file is the workspace's. A file in use is kept in the workspace's folder under its SHA-256
(:func:`store_history`), so that undoing a change finds the file of the settings it puts
back; the others are deleted when the settings change again (:func:`prune_history`).

Applying the form changes the settings as one change (``calculation.change_settings``),
which reruns each station's checks' job only, never the indices; Workspace settings shows
its progress with Undo while it runs (:func:`change_line`), as the overview's run status
line does.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
from dataclasses import dataclass, field

from django import forms
from django.utils.html import format_html
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.utils.translation import ngettext

from climpact_web.core import numbers
from climpact_web.stations import breaks

MAX_HISTORY_BYTES = 1024 * 1024  # a station history is a few kilobytes
PREVIEW_ROWS = 3
MAX_SEGMENT_YEARS = 50
# About how long one station's checks take with the break tests (the Sydney sample's 80
# years: 0.3 to 0.6 s in a worker that has run them before), and at least how long a
# change takes (a worker's first SNHT simulates its critical values, about 5 s): for the
# form's hint and impact line.
SECONDS_PER_STATION = 1
SECONDS_AT_LEAST = 5

# Each test in a few words, codes first (the board); "How the break tests work" has more.
TEST_NOTES = {
    "pettitt": _lazy("a rank test, robust to outliers; one break at a time"),
    "snht": _lazy("standard normal homogeneity test; most sensitive near the ends"),
    "pmf": _lazy("RHtests' penalised maximal F test; allows for a trend"),
    "pmt": _lazy("RHtests' penalised maximal t test; assumes no trend, so finds more"),
}
SERIES_LABELS = {"annual": _lazy("Annual"), "monthly": _lazy("Monthly")}
DATE_FORMATS = ("%Y-%m-%d", "%Y-%m", "%Y")


# ---- the station history file ---------------------------------------------------------------


@dataclass
class Event:
    date: str  # as written in the file
    station: str  # "" when the file has no station column
    text: str


@dataclass
class History:
    """A station history file, read: its events, or the problem that refuses it."""

    name: str
    events: list[Event] = field(default_factory=list)
    has_station: bool = False
    error: str = ""  # safe HTML: "Line 4: date <code>1997/06</code> is not ..."

    @property
    def ok(self) -> bool:
        return not self.error

    def counts(self) -> dict[str, int]:
        """The number of events of each station named, in the file's order."""
        out: dict[str, int] = {}
        for event in self.events:
            out[event.station] = out.get(event.station, 0) + 1
        return out

    @property
    def summary(self) -> str:
        """ "12 events for 3 stations", or "12 events for every station"."""
        n = len(self.events)
        events = ngettext("%(n)s event", "%(n)s events", n) % {"n": numbers.grouped(n)}
        if not self.has_station:
            return _("%(events)s for every station") % {"events": events}
        k = len(self.counts())
        return ngettext("%(events)s for %(k)s station", "%(events)s for %(k)s stations", k) % {
            "events": events,
            "k": numbers.grouped(k),
        }

    @property
    def preview(self) -> list[Event]:
        return self.events[:PREVIEW_ROWS]

    def rest(self, stations: list[str]) -> str:
        """Under the first rows: how many more, the events of each station named, and the
        workspace's stations with none ("9 more · Sydney Observatory Hill 5, Nowra 4 ·
        Newcastle Nobbys and Port Macquarie have none.")."""
        parts = []
        more = len(self.events) - len(self.preview)
        if more > 0:
            parts.append(_("%(n)s more") % {"n": numbers.grouped(more)})
        if self.has_station:
            counts = self.counts()
            nameless = _("no station")  # an event whose station is empty applies to none
            parts.append(
                ", ".join(f"{name or nameless} {numbers.grouped(n)}" for name, n in counts.items())
            )
            missing = [s for s in stations if s not in counts]
            if missing:
                parts.append(
                    ngettext("%(names)s has none", "%(names)s have none", len(missing))
                    % {"names": breaks._join(missing)}
                )
        return " · ".join(parts) + "." if parts else ""


def safe_name(name: str) -> str:
    """A chosen file's name, as shown and kept: its last part, at most 120 characters."""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name[:120] or breaks.HISTORY_FILE


def _date(text: str) -> bool:
    for fmt in DATE_FORMATS:
        try:
            dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
        return True
    return False


def read_history(data: bytes, name: str) -> History:
    """Read a station history file by the core's rules (``climpact.homogeneity.detect.
    read_station_history``): UTF-8 CSV with the columns ``date`` (YYYY-MM-DD, YYYY-MM or
    YYYY) and ``event``, and ``station`` to name each event's station. A problem names the
    line, in the core's words; the line is the file's own (blank lines count)."""
    history = History(name=name)
    if len(data) > MAX_HISTORY_BYTES:
        history.error = _(
            "The file is larger than %(kb)s kB; a station history is a few kilobytes."
        ) % {"kb": numbers.grouped(MAX_HISTORY_BYTES // 1024)}
        return history
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        history.error = _("The file is not UTF-8 text. Save it as CSV UTF-8 and choose it again.")
        return history
    reader = csv.DictReader(io.StringIO(text, newline=""))
    try:
        columns = {(c or "").strip().lower() for c in reader.fieldnames or ()}
        if not {"date", "event"} <= columns:
            history.error = _("The station history needs the columns date and event.")
            return history
        history.has_station = "station" in columns
        for row in reader:
            line = reader.line_num
            if None in row:
                history.error = _(
                    "Line %(line)s: more fields than columns (put an event with a comma in "
                    "double quotes)."
                ) % {"line": line}
                return history
            values = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            if not _date(values["date"]):
                history.error = format_html(
                    _("Line {line}: date {date} is not YYYY-MM-DD, YYYY-MM or YYYY."),
                    line=line,
                    date=format_html("<code>{}</code>", values["date"]),
                )
                return history
            history.events.append(Event(values["date"], values.get("station", ""), values["event"]))
    except csv.Error as exc:
        history.error = _("Line %(line)s: %(problem)s.") % {
            "line": reader.line_num,
            "problem": str(exc),
        }
    return history


def history_record(history: History, data: bytes) -> dict:
    """What the settings keep of a station history file: its name, its SHA-256 (its name
    on disk) and its counts, for the settings' summary."""
    return {
        "name": history.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "events": len(history.events),
        "stations": len(history.counts()) if history.has_station else None,
    }


def store_history(space, data: bytes) -> str:
    """Keep a station history file with the workspace, under its SHA-256; returns it."""
    sha256 = hashlib.sha256(data).hexdigest()
    path = breaks.history_path(space, sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_bytes(data)
    return sha256


def prune_history(space) -> None:
    """Delete the workspace's station history files that neither its settings nor the
    settings its last change would put back use."""
    keep = set()
    for chosen in (
        space.break_detection,
        ((space.undo or {}).get("settings") or {}).get("break_detection"),
    ):
        sha256 = ((chosen or {}).get("history") or {}).get("sha256")
        if sha256:
            keep.add(f"{sha256}.csv")
    folder = breaks.history_dir(space)
    if folder.is_dir():
        for path in folder.iterdir():
            if path.name not in keep:
                path.unlink(missing_ok=True)


def saved_history(space) -> History | None:
    """The workspace's station history file, read again for the form."""
    record = breaks.settings_of(space)["history"]
    path = breaks.history_path(space)
    if not record or path is None or not path.is_file():
        return None
    return read_history(path.read_bytes(), record.get("name") or breaks.HISTORY_FILE)


@dataclass
class HistoryState:
    """What the form shows of the station history file: ``empty`` (none), ``saved`` (the
    workspace's), ``chosen`` (a new file, read; ``sha256`` when it is kept already, after
    the form was sent with another problem) or ``error`` (a new file, refused)."""

    state: str
    history: History | None = None
    rest: str = ""
    sha256: str = ""


def history_state(space, chosen: History | None = None, sha256: str = "") -> HistoryState:
    """The station history part of the form, for a file just chosen (``chosen``) or the
    workspace's own."""
    names = space.stations.order_by("created_at", "station_name", "pk")  # the overview's order
    stations = [s for s in names.values_list("station_name", flat=True) if s]
    if chosen is not None:
        if not chosen.ok:
            return HistoryState("error", chosen)
        return HistoryState("chosen", chosen, chosen.rest(stations), sha256)
    saved = saved_history(space)
    if saved is not None and saved.ok:
        return HistoryState("saved", saved, saved.rest(stations))
    return HistoryState("empty")


# ---- the settings ---------------------------------------------------------------------------


def level_label(level: float) -> str:
    return _("%(level)s%%") % {"level": numbers.number(100 * float(level), 2)}


def series_text(series: list[str]) -> str:
    chosen = [str(SERIES_LABELS[s]).lower() for s in breaks.FREQUENCIES if s in series]
    return breaks._join(chosen)


def history_text(record: dict | None) -> str:
    """ "history: 12 events for 3 stations", or "no station history"."""
    if not record:
        return _("no station history")
    n = int(record.get("events") or 0)
    events = ngettext("%(n)s event", "%(n)s events", n) % {"n": numbers.grouped(n)}
    k = record.get("stations")
    if k is None:
        return _("history: %(events)s for every station") % {"events": events}
    return ngettext(
        "history: %(events)s for %(k)s station", "history: %(events)s for %(k)s stations", k
    ) % {"events": events, "k": numbers.grouped(k)}


def summary(space) -> str:
    """Break detection in one line, for Workspace settings: "On · Pettitt, SNHT, PMF, PMT
    · TX TN PRCP · annual and monthly · 95% · segments of 5+ years · no station
    history."."""
    chosen = breaks.settings_of(space)
    if not chosen["on"]:
        return _("Off.")
    parts = [
        _("On"),
        ", ".join(breaks.METHOD_NAMES[m] for m in breaks.METHODS if m in chosen["methods"]),
        " ".join(v for v in breaks.VARIABLES if v in chosen["variables"]),
        series_text(chosen["series"]),
        level_label(chosen["level"]),
        _("segments of %(years)s+ years") % {"years": int(chosen["min_years"])},
        history_text(chosen["history"]),
    ]
    return " · ".join(parts) + "."


def impact(space) -> str:
    """What applying the form updates (the impact line)."""
    count = space.stations.count()
    seconds = max(SECONDS_AT_LEAST, count * SECONDS_PER_STATION)
    from climpact_web.jobs.views import format_duration

    took = format_duration(dt.timedelta(seconds=seconds))
    if count == 1:
        text = _("Applying looks for breaks again in the station, about %(time)s.")
    else:
        text = _("Applying looks for breaks again in all %(count)s stations, about %(time)s.")
    return " ".join(
        [
            text % {"count": count, "time": took},
            _("The checks and the indices don't change."),
        ]
    )


class BreakDetectionForm(forms.Form):
    """Break detection's form. Its tests, variables and series need one choice each while
    detection is on (the core refuses an empty choice); off, they keep what they hold."""

    on = forms.BooleanField(label=_lazy("Look for breaks"), required=False)
    methods = forms.MultipleChoiceField(
        label=_lazy("Tests"),
        choices=[(m, breaks.METHOD_NAMES[m]) for m in breaks.METHODS],
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    variables = forms.MultipleChoiceField(
        label=_lazy("Variables"),
        choices=[(v, v) for v in breaks.VARIABLES],
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    series = forms.MultipleChoiceField(
        label=_lazy("Series"),
        choices=[(s, SERIES_LABELS[s]) for s in breaks.FREQUENCIES],
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    level = forms.TypedChoiceField(
        label=_lazy("Significance level"),
        choices=[(str(level), level_label(level)) for level in breaks.LEVELS],
        coerce=float,
    )
    min_years = forms.IntegerField(
        label=_lazy("Shortest segment"), min_value=1, max_value=MAX_SEGMENT_YEARS
    )
    history = forms.FileField(label=_lazy("Station history"), required=False)
    # A file chosen and read when the form was sent with another problem: kept with the
    # workspace already, so it need not be chosen again (the browser forgets it).
    history_sha = forms.RegexField(regex=r"^[0-9a-f]{64}$", required=False)
    remove_history = forms.BooleanField(label=_lazy("Remove"), required=False)

    def __init__(self, *args, space=None, **kwargs):
        self.space = space
        self.history_read: History | None = None
        self.history_data = b""
        self.history_sha = ""
        if not args and "initial" not in kwargs and space is not None:
            chosen = breaks.settings_of(space)
            kwargs["initial"] = {
                "on": chosen["on"],
                "methods": chosen["methods"],
                "variables": chosen["variables"],
                "series": chosen["series"],
                "level": str(chosen["level"]),
                "min_years": chosen["min_years"],
            }
        super().__init__(*args, **kwargs)
        for name in ("on", "level", "min_years"):  # their hints, in the template
            self.fields[name].widget.attrs["aria-describedby"] = f"id_{name}_helptext"

    def clean_history(self):
        upload = self.cleaned_data.get("history")
        if not upload:
            return None
        data = upload.read(MAX_HISTORY_BYTES + 1)
        self.history_data = data
        self.history_read = read_history(data, safe_name(upload.name))
        if not self.history_read.ok:
            raise forms.ValidationError(self.history_read.error)
        self.history_sha = store_history(self.space, data)
        return upload

    def clean(self):
        data = super().clean()
        sha256 = data.get("history_sha")
        if self.history_read is None and sha256 and not self.has_error("history"):
            path = breaks.history_path(self.space, sha256)
            if path is not None and path.is_file():
                self.history_data = path.read_bytes()
                name = self.data.get("history_name") or breaks.HISTORY_FILE
                self.history_read = read_history(self.history_data, safe_name(name))
                self.history_sha = sha256
        if not data.get("on"):
            return data
        empty = {
            "methods": _("Choose at least one test."),
            "variables": _("Choose at least one variable."),
            "series": _("Choose at least one series."),
        }
        for name, message in empty.items():
            if name in data and not data[name]:
                self.add_error(name, message)
        if data.get("variables") == ["PRCP"] and data.get("series") == ["monthly"]:
            self.add_error("series", _("PRCP is tested yearly only: choose Annual, or TX or TN."))
        return data

    def settings(self) -> dict:
        """The settings chosen, the station history file kept with the workspace when a
        new one was chosen ({} for the defaults, as ``Workspace.break_detection`` keeps
        them)."""
        data = self.cleaned_data
        history = breaks.settings_of(self.space)["history"]
        if data.get("remove_history"):
            history = None
        elif self.history_read is not None and self.history_read.ok:
            history = history_record(self.history_read, self.history_data)
        chosen = {
            "on": bool(data["on"]),
            "methods": [m for m in breaks.METHODS if m in data["methods"]],
            "variables": [v for v in breaks.VARIABLES if v in data["variables"]],
            "series": [s for s in breaks.FREQUENCIES if s in data["series"]],
            "level": float(data["level"]),
            "min_years": int(data["min_years"]),
            "history": history,
        }
        if chosen == {**breaks.DEFAULTS, "history": None}:
            return {}
        return chosen


# ---- the change's progress on Workspace settings ---------------------------------------------


@dataclass
class ChangeLine:
    """Workspace settings' line while a change to break detection is on the way (the
    board's saved state): ``running`` with its progress and Undo, else ``done``."""

    tone: str
    head: str
    rest: str
    percent: int = 0
    can_undo: bool = False


def breaks_change(space) -> bool:
    """Whether the workspace's last change to its settings changed break detection alone."""
    record = space.undo or {}
    if not record.get("change"):
        return False
    fields = record.get("fields")
    if fields is not None:
        return list(fields) == ["break_detection"]
    before = record.get("settings") or {}
    changed = [name for name, value in before.items() if getattr(space, name) != value]
    return changed == ["break_detection"]


def change_line(space) -> ChangeLine | None:
    """The line Workspace settings shows of the last change, when it changed break
    detection alone (None otherwise, or when nothing was queued)."""
    from climpact_web.stations import workspace

    if not breaks_change(space):
        return None
    state = workspace.change_state(space)
    if state is None or not state.total:
        return None
    head = _("Break detection changed.")
    finished = state.done + state.failed + state.cancelled
    values = {"total": numbers.grouped(state.total), "done": numbers.grouped(finished)}
    if not state.finished:
        rest = (
            ngettext(
                "Looking for breaks in %(total)s station: %(done)s of %(total)s done.",
                "Looking for breaks in %(total)s stations: %(done)s of %(total)s done.",
                state.total,
            )
            % values
        )
        percent = int(100 * finished / state.total)
        return ChangeLine(
            "running",
            head,
            " ".join([rest, _("The indices don't change.")]),
            percent,
            state.can_undo,
        )
    rest = ngettext(
        "Breaks looked for again in %(done)s of %(total)s station.",
        "Breaks looked for again in %(done)s of %(total)s stations.",
        state.total,
    ) % {"total": numbers.grouped(state.total), "done": numbers.grouped(state.done)}
    if state.failed:
        rest += " " + ngettext(
            "%(n)s station's checks failed: its Quality says why.",
            "%(n)s stations' checks failed: their Quality says why.",
            state.failed,
        ) % {"n": state.failed}
    return ChangeLine("done", head, " ".join([rest, _("The indices didn't change.")]), 100)

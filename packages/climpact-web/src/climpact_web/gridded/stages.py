"""A gridded run's stages while it calculates, and what to change when it fails (#294,
the GridRun board): what the run's Map tab shows in place of the map.

- **The status line** (the workspace's Run status line): one sentence on where the run
  is ("Calculating indices: 62%."), the time left once the last main stage has a rate,
  the time so far, a bar and Cancel; or where it failed or was cancelled, with "Change
  the settings" and "Forget this run".
- **The stages**: Check the files, Read the thresholds file (indices from a file), the
  cell-first copy (only when one is made), Thresholds (the thresholds file), Indices and
  Trends and the map, each with its state and time. A run's jobs (thresholds, indices)
  are one table: an indices job after a thresholds job opens and copies the files again,
  which its Indices row counts. Each job's stages and their times come from its
  ``stages.json`` (:class:`climpact_web.jobs.runners.StageTimes`).
- **The failure**: the error in words, the setting that fixes it with a link to it on
  Set-up, what is kept, and the run's log.
- **Beside it**, what is being calculated.

A new start of a finished run (#293) shows the same status line and stages above the
results it will replace (``again``).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from django.urls import reverse
from django.utils import dateformat, timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from climpact_web.core import numbers
from climpact_web.gridded import runs
from climpact_web.gridded.models import GriddedRun
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.runners import read_stage_times
from climpact_web.jobs.views import poll_delay
from climpact_web.jobs.worker import worker_running

MB_PER_MILLION = 8  # bytes per value the blocks hold, as the set-up's hint says

# The stages in the words of "The run failed in the <stage> stage."
STAGE_WORDS = {
    "check": gettext_lazy("check"),
    "read": gettext_lazy("thresholds file"),
    "rechunk": gettext_lazy("cell-first copy"),
    "thresholds": gettext_lazy("thresholds"),
    "indices": gettext_lazy("indices"),
    "trends": gettext_lazy("trends"),
}


# ---- Each job's stages -------------------------------------------------------------------


def _time(value) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def main_stage(job: Job) -> str:
    return "thresholds" if job.kind == "gridded-thresholds" else "indices"


def has_trends(job: Job) -> bool:
    return job.kind == "gridded-indices" and (job.params or {}).get("trends", True) is not False


def stage_keys(job: Job) -> list[str]:
    """A job's stages in the order it runs them."""
    keys = ["check", "rechunk", main_stage(job)]
    return keys + ["trends"] if has_trends(job) else keys


@dataclass
class Segment:
    key: str
    start: dt.datetime | None
    end: dt.datetime | None  # None while it is under way
    step: int = 0  # the job's count when the stage began

    def duration(self, now: dt.datetime) -> dt.timedelta | None:
        if self.start is None:
            return None
        return max((self.end or now) - self.start, dt.timedelta(0))


@dataclass
class JobStages:
    """One job's stages so far, from its ``stages.json``."""

    job: Job
    segments: list[Segment] = field(default_factory=list)
    blocks: int = 0
    copy: bool = False
    copy_bytes: int = 0
    stopped_in: str = ""  # failed or cancelled: the stage it stopped in

    @property
    def current(self) -> str:
        return self.segments[-1].key if self.segments else "check"

    def segment(self, key: str) -> Segment | None:
        return next((s for s in self.segments if s.key == key), None)


def job_stages(job: Job) -> JobStages:
    out = JobStages(job)
    if job.status == Status.QUEUED:  # a file left by an earlier attempt is not this one's
        return out
    data = read_stage_times(job.folder)
    out.blocks = int(data.get("blocks") or 0)
    out.copy = bool(data.get("copy"))
    out.copy_bytes = int(data.get("copy_bytes") or 0)
    end = job.finished_at if job.is_finished else None
    entries = [e for e in data.get("stages") or [] if isinstance(e, dict)]
    for i, entry in enumerate(entries):
        later = _time(entries[i + 1].get("at")) if i + 1 < len(entries) else None
        key = str(entry.get("stage") or "")
        out.segments.append(
            Segment(key, _time(entry.get("at")), later or end, int(entry.get("step") or 0))
        )
    if not out.segments:
        # A job run before the stages were recorded, or not yet started on them.
        if job.status == Status.RUNNING:
            key = (job.stage or "").split(":")[0] or "check"
            out.segments.append(Segment(key, job.started_at, None))
        return out
    opened = _time(data.get("opened"))
    last = out.segments[-1]
    if last.key == "check" and opened is not None:
        # The files are open and checked: the next stage has begun, its first step not
        # yet reported.
        last.end = opened
        out.segments.append(Segment("rechunk" if out.copy else main_stage(job), opened, end))
    if job.status in (Status.FAILED, Status.CANCELLED):
        stop = out.segments[-1].key
        total, step = job.total, job.step
        if stop == "rechunk" and out.blocks and total and step >= total - out.blocks:
            stop = main_stage(job)  # the copy had finished: the first block failed
        if stop == main_stage(job) and total and step >= total and has_trends(job):
            stop = "trends"  # every block was done: the trends failed before a step
        if stop != out.segments[-1].key:
            out.segments.append(Segment(stop, None, None))
        out.stopped_in = stop
    return out


# ---- The rows of the stages table ---------------------------------------------------------


def clock(value: dt.timedelta | None) -> str:
    """A stage's time as the board gives it: ``0:04``, ``7:51``, ``1:02:03``."""
    if value is None:
        return ""
    seconds = max(0, int(value.total_seconds()))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


MARKS = {"done": "✓", "kept": "✓", "running": "›", "failed": "✗", "cancelled": "✗"}


@dataclass
class StageRow:
    key: str  # check, read, rechunk, thresholds, indices, trends
    title: str
    text: str  # one line on what it does
    state: str = "waiting"  # done, kept, running, waiting, failed, cancelled, not_run
    label: str = ""  # the State column's words
    percent: int | None = None  # running, when the steps are counted
    time: str = ""
    job: Job | None = None
    current: str = ""  # running: the stage its job is in (an Indices row may be copying)
    # Running: blocks done and in all, and the stage's time so far (for the time left).
    done: int = 0
    of: int = 0
    elapsed: dt.timedelta | None = None

    @property
    def mark(self) -> str:
        return MARKS.get(self.state, "·")


def _progress(js: JobStages, key: str) -> tuple[int, int]:
    """Steps done and in all of the stage ``key`` the job is in."""
    job, seg = js.job, js.segment(key)
    total, step = job.total, job.step
    if not total or seg is None or job.stage.split(":")[0] != key:
        return 0, 0
    if key == "rechunk":
        steps = total - js.blocks if js.blocks and total > js.blocks else total
        return min(step, steps), steps
    if key in ("thresholds", "indices") and js.blocks:
        first = max(0, total - js.blocks)
        return max(0, min(step - first, js.blocks)), js.blocks
    return max(0, step - seg.step), max(1, total - seg.step)


def _state(js: JobStages, keys: list[str], kept: bool) -> str:
    job = js.job
    order = stage_keys(job)
    last = max(order.index(k) for k in keys)
    if job.status == Status.QUEUED:
        return "waiting"
    if job.status == Status.SUCCEEDED:
        return "kept" if kept else "done"
    if job.status == Status.RUNNING:
        current = js.current
        if current in keys:
            return "running"
        return "done" if current in order and order.index(current) > last else "waiting"
    stop = js.stopped_in or js.current
    if stop in keys:
        return "failed" if job.status == Status.FAILED else "cancelled"
    return "done" if stop in order and order.index(stop) > last else "not_run"


STATE_LABELS = {
    "done": gettext_lazy("Done"),
    "kept": gettext_lazy("Kept from the last start"),
    "waiting": gettext_lazy("Waiting"),
    "failed": gettext_lazy("Failed"),
    "cancelled": gettext_lazy("Cancelled"),
    "not_run": gettext_lazy("Not run"),
}


def _fill(row: StageRow, js: JobStages, keys: list[str], kept: bool, now: dt.datetime) -> StageRow:
    job = js.job
    row.job = job
    row.state = _state(js, keys, kept)
    row.label = str(STATE_LABELS.get(row.state, ""))
    segments = [s for s in js.segments if s.key in keys]
    times = [d for s in segments if (d := s.duration(now)) is not None]
    if times:
        row.time = clock(sum(times, dt.timedelta(0)))
    elif row.state in ("done", "kept") and row.key == main_stage(job) and not js.segments:
        row.time = clock(job.elapsed(now))  # a job run before the stages were recorded
    main = main_stage(job)
    if row.state == "running":
        current = row.current = js.current
        done, of = _progress(js, current)
        if current == main or current == "trends":
            row.percent = int(100 * done / of) if of else None
            if current == main and js.blocks and of:
                row.label = _("%(percent)s%% · block %(done)s of %(of)s") % {
                    "percent": row.percent,
                    "done": numbers.grouped(done),
                    "of": numbers.grouped(of),
                }
                row.done, row.of = done, of
                seg = js.segment(current)
                row.elapsed = seg.duration(now) if seg else None
            elif row.percent is not None:
                row.label = _("%(percent)s%%") % {"percent": row.percent}
            else:
                row.label = _("Under way")
        elif current == "rechunk":
            row.percent = int(100 * done / of) if of else None
            row.label = (
                _("Copying the files by cell · %(percent)s%%") % {"percent": row.percent}
                if row.key != "rechunk" and row.percent is not None
                else (
                    _("%(percent)s%%") % {"percent": row.percent}
                    if row.percent is not None
                    else _("Under way")
                )
            )
        else:  # the check
            row.label = _("Checking the files") if row.key != "check" else _("Under way")
    if row.state == "failed" and row.key == main and js.blocks and job.total:
        failed_in = min(js.blocks, _blocks_done(js) + 1)
        row.label = _("Failed in block %(block)s of %(blocks)s") % {
            "block": numbers.grouped(failed_in),
            "blocks": numbers.grouped(js.blocks),
        }
    return row


def _blocks_done(js: JobStages) -> int:
    job = js.job
    first = max(0, job.total - js.blocks)
    return max(0, min(job.step - first, js.blocks))


def stage_rows(
    thresholds_job: Job | None, indices_job: Job | None, now: dt.datetime | None = None
) -> list[StageRow]:
    """The stages table of a start: its thresholds job, its indices job, or both."""
    now = now or timezone.now()
    jobs = [j for j in (thresholds_job, indices_job) if j is not None]
    if not jobs:
        return []
    stages = {j.pk: job_stages(j) for j in jobs}
    newest = max(j.created_at for j in jobs)

    def kept(job: Job) -> bool:  # finished before this start: kept from the last one
        return job.status == Status.SUCCEEDED and bool(job.finished_at) and job.finished_at < newest

    first = jobs[0]
    fs = stages[first.pk]
    params = (indices_job or first).params or {}
    rows = [
        _fill(
            StageRow("check", _("Check the files"), _check_text(first)),
            fs,
            ["check"],
            kept(first),
            now,
        )
    ]
    from_file = indices_job is not None and thresholds_job is None and params.get("thresholds_file")
    if from_file:
        rows.append(_read_row(fs, str(params["thresholds_file"]), rows[0], now))
    if fs.copy or fs.segment("rechunk"):
        if fs.copy_bytes:
            text = _("The files are chunked by time; a %(size)s copy laid out by cell.") % {
                "size": _size(fs.copy_bytes)
            }
        else:
            text = _("The files are chunked by time; a copy laid out by cell.")
        rows.append(
            _fill(
                StageRow("rechunk", _("Cell-first copy"), text), fs, ["rechunk"], kept(first), now
            )
        )
    base = f"{params.get('base_start', '')}–{params.get('base_end', '')}"
    if thresholds_job is not None:
        keys = ["thresholds"] if thresholds_job is first else ["check", "rechunk", "thresholds"]
        text = _("Percentiles of %(base)s for every cell, written to the thresholds file.") % {
            "base": base
        }
        rows.append(
            _fill(
                StageRow("thresholds", _("Thresholds"), text),
                stages[thresholds_job.pk],
                keys,
                kept(thresholds_job),
                now,
            )
        )
    if indices_job is not None:
        js = stages[indices_job.pk]
        keys = ["indices"] if indices_job is first else ["check", "rechunk", "indices"]
        rows.append(
            _fill(
                StageRow("indices", _("Indices"), _indices_text(indices_job)),
                js,
                keys,
                kept(indices_job),
                now,
            )
        )
        if has_trends(indices_job):
            text = _("Sen’s slope for every cell and index, for the Trend view.")
            rows.append(
                _fill(
                    StageRow("trends", _("Trends and the map"), text),
                    js,
                    ["trends"],
                    kept(indices_job),
                    now,
                )
            )
    return rows


def _size(value: int) -> str:
    from climpact_web.gridded.setup_page import size_text

    return size_text(value)


def _check_text(job: Job) -> str:
    count = len((job.params or {}).get("input_files") or [])
    return ngettext(
        "Climpact opens the file and checks its grid, calendar and units.",
        "Climpact opens the %(count)s files and checks their grid, calendar and units.",
        count,
    ) % {"count": count}


def _indices_text(job: Job) -> str:
    p = job.params or {}
    chosen = p.get("indices")
    count = len(chosen) if chosen else _all_index_count()
    return ngettext(
        "%(count)s index in blocks of cells, %(workers)s at a time.",
        "%(count)s indices in blocks of cells, %(workers)s at a time.",
        count,
    ) % {"count": count, "workers": int(p.get("workers") or 1)}


def _all_index_count() -> int:
    from climpact_web.gridded.forms import all_indices

    return len(all_indices())


def _read_row(js: JobStages, path: str, check: StageRow, now) -> StageRow:
    """Read the thresholds file: checked with the files (no stage of its own in the
    core), so it is done once the check is, or failed when the check failed on it."""
    from pathlib import Path

    row = StageRow("read", _("Read the thresholds file"), Path(path).name, job=js.job)
    if check.state in ("failed", "cancelled") and thresholds_problem(js.job.error):
        row.state, check.state = check.state, "done"
        check.label = str(STATE_LABELS["done"])
    elif check.state in ("failed", "cancelled"):
        row.state = "not_run"
    elif check.state == "running":
        row.state = "waiting"
    else:
        row.state = check.state
    row.label = str(STATE_LABELS.get(row.state, ""))
    return row


# ---- What to change when it fails -------------------------------------------------------


def thresholds_problem(error: str) -> bool:
    text = (error or "").lower()
    return (
        "thresholds file" in text
        or "missing thresholds" in text
        or ("thresholds" in text and "differs" in text)
    )


@dataclass
class Failure:
    error: str  # what happened, in words
    detail: str = ""  # more on it
    fix: str = ""  # what to change
    kept: str = ""  # what is kept, so starting again resumes
    button: str = ""
    href: str = ""
    log: str = ""


FILES_PROBLEMS = (
    "a gap between",
    "overlap",
    "does not have the grid of",
    "calendar and",
    "has no time steps",
    "same time axis",
    "a day more than once",
    "input file not found",
    "cannot decode the time axis",
    "dates outside",
)
UNITS_PROBLEMS = ("units",)
VARIABLE_PROBLEMS = ("not found in", "does not have the dimensions of", "expected dimensions")


def failure_for(rows: list[StageRow], run: GriddedRun, options: dict) -> Failure | None:
    """The failure box: the failed job's error, the setting that fixes it with a link to
    it on Set-up, and what is kept."""
    failed = next((r for r in rows if r.state == "failed"), None)
    if failed is None or failed.job is None:
        return None
    job = failed.job
    error = job.error or _("The run failed.")
    lower = error.lower()
    setup = reverse("gridded:setup", args=[run.pk])
    out = Failure(error=error, log=reverse("gridded:log", args=[run.pk]))
    if "out of memory" in lower:
        values = float(options.get("max_values") or 0)
        cores = int(options.get("workers") or 1)
        js = job_stages(job)
        if failed.key == main_stage(job) and js.blocks:
            out.error = _("The run ran out of memory in block %(block)s of %(blocks)s.") % {
                "block": numbers.grouped(min(js.blocks, _blocks_done(js) + 1)),
                "blocks": numbers.grouped(js.blocks),
            }
        else:
            out.error = _("The run ran out of memory.")
        if values:
            per_core = values * 1e6 * MB_PER_MILLION
            out.detail = ngettext(
                "Each block holds %(values)s million values (about %(per_core)s per core, "
                "%(total)s on %(cores)s core).",
                "Each block holds %(values)s million values (about %(per_core)s per core, "
                "%(total)s on %(cores)s cores).",
                cores,
            ) % {
                "values": numbers.number(values),
                "per_core": _size(per_core),
                "total": _size(per_core * cores),
                "cores": cores,
            }
            out.fix = _(
                "Lower Values read at once to %(lower)s million, or use fewer cores, under "
                "Set-up › Computing, then start again."
            ) % {"lower": numbers.number(max(0.1, round(values / 2, 1)))}
        else:
            out.fix = _(
                "Lower Values read at once, or use fewer cores, under Set-up › Computing, "
                "then start again."
            )
        out.button, out.href = _("Change the computing settings"), f"{setup}#id_max_values"
    elif "cell-first copy" in lower:
        out.fix = _(
            "Choose a folder with more room for the copy, or turn the copy off, under "
            "Set-up › Computing, then start again."
        )
        out.button, out.href = _("Change the computing settings"), f"{setup}#id_rechunk"
    elif "could not be copied to" in lower:
        out.fix = _("Choose another folder to copy the results to under Set-up › Output files.")
        out.button, out.href = _("Change the output files"), f"{setup}#id_copy_to"
    elif "longer than this site allows" in lower:
        out.fix = _(
            "Choose fewer indices under Set-up › Indices, or install Climpact on your own "
            "computer, which has no time limit."
        )
        out.button, out.href = _("Change the indices"), f"{setup}#indices-title"
    elif failed.key == "read" or thresholds_problem(error):
        out.fix = _(
            "Choose another thresholds file, or calculate the thresholds with the indices, "
            "under Set-up › What to calculate."
        )
        out.button, out.href = _("Change what to calculate"), f"{setup}#task-title"
    elif "base period" in lower:
        out.fix = _("Choose a base period inside the files’ years under Set-up › Base period.")
        out.button, out.href = _("Change the base period"), f"{setup}#base-title"
    elif any(p in lower for p in FILES_PROBLEMS):
        out.fix = _(
            "The files of each variable must follow on day after day, with one grid, "
            "calendar and units. Add the missing file or choose other files, then start "
            "again."
        )
        out.button, out.href = _("Check the files"), f"{setup}#files-title"
    elif any(p in lower for p in UNITS_PROBLEMS):
        out.fix = _(
            "Climpact reads temperatures in K or °C and precipitation in kg m-2 d-1 "
            "(mm/day) or kg m-2 s-1. Check how each variable is read under Set-up › "
            "Variables, or convert the file first."
        )
        out.button, out.href = _("Check the variables"), f"{setup}#variables-title"
    elif any(p in lower for p in VARIABLE_PROBLEMS):
        out.fix = _(
            "Choose the variable for each of TX, TN and precipitation under Set-up › Variables."
        )
        out.button, out.href = _("Check the variables"), f"{setup}#variables-title"
    elif "stopped unexpectedly" in lower:
        out.fix = _("Start again on Set-up.")
        out.button, out.href = _("Open Set-up"), setup
    else:
        out.fix = _(
            "Check the settings on Set-up, then start again. The run’s log has the details."
        )
        out.button, out.href = _("Change the settings"), setup
    out.kept = kept_text(rows)
    return out


def kept_text(rows: list[StageRow]) -> str:
    """What a failed or cancelled start keeps, so starting again resumes."""
    jobs = {r.job.kind: r.job for r in rows if r.job is not None}
    thresholds, indices = jobs.get("gridded-thresholds"), jobs.get("gridded-indices")
    if thresholds is None or indices is None:
        return ""
    if thresholds.status == Status.SUCCEEDED and indices.status != Status.SUCCEEDED:
        return _(
            "The thresholds file is kept: starting again with the same files and base "
            "period begins at the indices."
        )
    if indices.status == Status.SUCCEEDED and thresholds.status != Status.SUCCEEDED:
        return _(
            "The indices are kept: starting again with the same settings writes the "
            "thresholds file only."
        )
    return ""


# ---- The status line ----------------------------------------------------------------------


@dataclass
class Link:
    label: str
    url: str
    post: bool = False


@dataclass
class StatusLine:
    tone: str  # running, failed, stopped (cancelled)
    head: str
    rest: str = ""
    percent: int | None = None
    links: list[Link] = field(default_factory=list)


RUNNING_HEADS = {
    "check": lambda p: _("Checking the files."),
    "read": lambda p: _("Checking the files."),
    "rechunk": lambda p: _("Making the cell-first copy: %(percent)s%%.") % {"percent": p},
    "thresholds": lambda p: _("Calculating thresholds: %(percent)s%%.") % {"percent": p},
    "indices": lambda p: _("Calculating indices: %(percent)s%%.") % {"percent": p},
    "trends": lambda p: _("Calculating trends: %(percent)s%%.") % {"percent": p},
}


def status_line(
    run: GriddedRun,
    rows: list[StageRow],
    again: bool,
    when: str,
    now: dt.datetime,
    failure: Failure | None = None,
) -> StatusLine:
    jobs = [r.job for r in rows if r.job is not None]
    jobs = list({j.pk: j for j in jobs}.values())
    setup = reverse("gridded:setup", args=[run.pk])
    forget = Link(_("Forget this run"), reverse("gridded:delete", args=[run.pk]))
    shown = (
        _("Map and Files show the run of %(when)s until this one has finished, then its results.")
        % {"when": when}
        if again
        else ""
    )
    active = [j for j in jobs if not j.is_finished]
    if active:
        cancel = Link(_("Cancel"), reverse("gridded:cancel", args=[run.pk]), post=True)
        if any(j.cancel_requested for j in active):
            return StatusLine("running", _("Cancelling…"), shown, None, [])
        running = next((r for r in rows if r.state == "running"), None)
        started = min((j.started_at for j in jobs if j.started_at), default=None)
        if running is None:
            rest = _("It starts when the calculations before it have finished.")
            if not again:
                rest += " " + _("You can close this page.")
            return StatusLine(
                "running", _("Waiting to start."), f"{rest} {shown}".strip(), 0, [cancel]
            )
        key = running.key
        if key in ("thresholds", "indices") and running.current in ("check", "rechunk"):
            key = running.current  # an indices job after the thresholds opens the files again
        percent = running.percent or 0
        head = RUNNING_HEADS.get(key, RUNNING_HEADS["check"])(percent)
        so_far = runs.short_duration(now - started) if started else ""
        left = _time_left(running, rows)
        parts = []
        if left and so_far:
            parts.append(
                _("About %(left)s left, %(so_far)s so far.") % {"left": left, "so_far": so_far}
            )
        elif so_far:
            parts.append(_("%(so_far)s so far.") % {"so_far": so_far})
        parts.append(shown or _("You can close this page."))
        return StatusLine("running", head, " ".join(parts), percent, [cancel])

    stopped = next((r for r in rows if r.state in ("failed", "cancelled")), None)
    if stopped is None:
        return StatusLine("running", _("Finishing…"), shown)
    words = str(STAGE_WORDS.get(stopped.key, stopped.key))
    kept = _kept_short(rows)
    if stopped.state == "failed":
        head = (
            _("The last start failed in the %(stage)s stage.")
            if again
            else _("The run failed in the %(stage)s stage.")
        ) % {"stage": words}
        rest = kept or _("Nothing was written.")
        change = Link(_("Change the settings"), failure.href if failure and failure.href else setup)
        links = [change] if again else [change, forget]
        tone = "failed"
    else:
        head = (
            _("The last start was cancelled in the %(stage)s stage.")
            if again
            else _("The run was cancelled in the %(stage)s stage.")
        ) % {"stage": words}
        rest = kept or _("Nothing was written.")
        start = Link(_("Start again on Set-up"), setup)
        links = [start] if again else [start, forget]
        tone = "stopped"
    if again:
        rest = _("Map and Files still show the run of %(when)s.") % {"when": when}
        if kept:
            rest = f"{kept} {rest}"
    return StatusLine(tone, head, rest, None, links)


def _kept_short(rows: list[StageRow]) -> str:
    jobs = {r.job.kind: r.job for r in rows if r.job is not None}
    thresholds, indices = jobs.get("gridded-thresholds"), jobs.get("gridded-indices")
    if thresholds is None or indices is None:
        return ""
    if thresholds.status == Status.SUCCEEDED and indices.status != Status.SUCCEEDED:
        return _("The thresholds file is kept.")
    if indices.status == Status.SUCCEEDED and thresholds.status != Status.SUCCEEDED:
        return _("The indices are kept.")
    return ""


def _time_left(running: StageRow, rows: list[StageRow]) -> str:
    """A linear estimate once the last main stage has done two blocks in two seconds;
    "" before, or while a main stage waits after this one."""
    mains = [r for r in rows if r.key in ("thresholds", "indices")]
    if not mains or running is not mains[-1] or running.done < 2 or not running.of:
        return ""
    if running.elapsed is None or running.elapsed < dt.timedelta(seconds=2):
        return ""
    left = running.elapsed * (running.of - running.done) / running.done
    return runs.short_duration(left)


# ---- Beside it: what is being calculated --------------------------------------------------


def facts(run: GriddedRun, options: dict, names: dict, jobs: list[Job]) -> list[tuple[str, str]]:
    summary = runs.grid_summary(run)
    size = sum(f.get("size") or 0 for f in run.files)
    chosen = [names.get(role) for role in ("tasmax", "tasmin", "pr") if names.get(role)]
    out = [
        (_("Files"), " · ".join(p for p in (", ".join(chosen), _size(size) if size else "") if p))
    ]
    if summary.ny:
        out.append((_("Grid"), f"{summary.ny} × {summary.nx}, {runs.period_text(summary)}"))
    if options.get("base_start"):
        base = f"{options['base_start']}–{options['base_end']}"
        if options.get("task") == "indices" and options.get("thresholds_source") == "file":
            from pathlib import Path

            name = Path(str(options.get("thresholds_file") or "")).name
            base = _("%(base)s, from %(file)s") % {"base": base, "file": name} if name else base
        out.append((_("Base period"), base))
    task = options.get("task")
    if task == "thresholds":
        out.append((_("Indices"), _("Thresholds file only")))
    elif task:
        count = len(options.get("indices") or []) or _all_index_count()
        files = _index_file_count(options)
        text = str(count)
        if files:
            text += " · " + ngettext("%(count)s file", "%(count)s files", files) % {"count": files}
        out.append((_("Indices"), text))
    cores = int(options.get("workers") or 1)
    values = options.get("max_values")
    computing = ngettext("%(count)s core", "%(count)s cores", cores) % {"count": cores}
    if values:
        computing += " · " + _("%(values)s M values") % {"values": numbers.number(float(values))}
    out.append((_("Computing"), computing))
    started = min((j.started_at for j in jobs if j.started_at), default=None)
    out.append((_("Started"), when_text(started) if started else _("Not yet")))
    return out


def _index_file_count(options: dict) -> int:
    """The index files the run writes: one for each chosen index and frequency."""
    from dataclasses import replace

    from climpact_web.gridded.forms import SetupForm

    try:
        from climpact.gridded.indices import WRAPPER_PARAMS, index_files

        values = {k: options[k] for k in SetupForm.PARAMS if options.get(k) is not None}
        specs = index_files(replace(WRAPPER_PARAMS, **values))
    except (ImportError, TypeError, ValueError):
        return 0
    chosen = set(options.get("indices") or [])
    return len([s for s in specs if not chosen or s.index in chosen])


def when_text(value: dt.datetime) -> str:
    return dateformat.format(timezone.localtime(value), "j M Y, H:i")


# ---- The Map tab's state ------------------------------------------------------------------


@dataclass
class RunProgress:
    again: bool  # a new start beside the results it will replace (#293)
    active: bool
    status: StatusLine
    rows: list[StageRow]
    failure: Failure | None
    facts: list[tuple[str, str]]
    about_title: str
    about_note: str
    delay: int
    worker_missing: bool


def view(
    run: GriddedRun, hidden: bool = False, now: dt.datetime | None = None
) -> RunProgress | None:
    """What the Map tab shows of the run's calculation: its first start while it runs,
    failed or was cancelled; a new start (#293) while it runs or after it failed or was
    cancelled, above the results shown. None once there is nothing to say: the run has
    finished and no new start waits."""
    now = now or timezone.now()
    if run.next_jobs:
        again = True
        thresholds_job, indices_job = run.next_thresholds_job, run.next_indices_job
        settings_ = run.next_settings or {}
        options, names = settings_.get("options") or {}, settings_.get("names") or run.names
    elif run.jobs and not runs.all_done(run):
        again = False
        thresholds_job, indices_job = run.thresholds_job, run.indices_job
        options, names = run.options, run.names
    else:
        return None
    jobs = [j for j in (thresholds_job, indices_job) if j is not None]
    rows = stage_rows(thresholds_job, indices_job, now)
    _started, finished = _finished(run.jobs)
    when = when_text(finished) if finished else "–"
    active = [j for j in jobs if not j.is_finished]
    failure = failure_for(rows, run, options) if not active else None
    status = status_line(run, rows, again, when, now, failure)
    if active:
        title = _("What is being calculated")
        note = _about_note(options.get("task") == "thresholds")
    else:
        title = _("What the run calculates")
        kept = runs.kept_until(run)
        if kept:
            note = _("The run is on Gridded until %(date)s.") % {"date": kept}
        else:  # runs stay until forgotten (#301)
            note = _("The run stays on Gridded until you forget it.")
    return RunProgress(
        again=again,
        active=bool(active),
        status=status,
        rows=rows,
        failure=failure,
        facts=facts(run, options, names, jobs),
        about_title=title,
        about_note=note,
        delay=min((poll_delay(j, hidden, now) for j in active), default=0),
        worker_missing=any(j.status == Status.QUEUED for j in active) and not worker_running(now),
    )


def _about_note(thresholds_only: bool) -> str:
    """The line under "What is being calculated": the run goes on in the background, and
    how long it is listed on Gridded (until a date, or until forgotten where runs do not
    expire, #301)."""
    from django.conf import settings

    from climpact_web.gridded.setup_page import _kept_date

    if settings.WORKSPACE_EXPIRY:
        kept = _("the run is on Gridded until %(date)s.") % {"date": _kept_date()}
    else:
        kept = _("the run stays on Gridded until you forget it.")
    if thresholds_only:
        first = _(
            "It runs in the background: close this page if you like. Its file is on Files "
            "when it finishes;"
        )
    else:
        first = _(
            "It runs in the background: close this page if you like. The map opens here "
            "when it finishes;"
        )
    return f"{first} {kept}"


def _finished(jobs: list[Job]):
    started = min((j.started_at for j in jobs if j.started_at), default=None)
    finished = max((j.finished_at for j in jobs if j.finished_at), default=None)
    return started, finished

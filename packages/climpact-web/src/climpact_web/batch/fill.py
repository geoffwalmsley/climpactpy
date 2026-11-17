"""A batch fills its workspace (#255, part 3 of #231).

A batch is a way to fill a workspace, not a separate kind of result (#230, decision 5).
Every station of its metadata file is a :class:`Station` of the batch's workspace, whether
it calculated or not, as on the workspace overview (``Calculate.dc.html``, #234): a row of
the Stations table each, with its run state.

:func:`add_stations` adds them when the run is queued (``run_batch``): the stations that
will run, waiting, and those the check left out, "not run" with why. The job has the
parameter ``stations_added``. :func:`fill_workspace` records how the run went once its job
has succeeded, the first time the batch results are shown after it (the results page and
its progress fragment, which stand in as the workspace page until #234) or a station is
opened from them: a station that calculated shows the batch's results for it until a
change to the workspace's settings recalculates it with ``station`` jobs
(:mod:`climpact_web.stations.calculation`); one that failed keeps no results, only R's or
our error in words. It is idempotent: ``BatchRun.filled_job`` records the run filled in,
and a station the user deletes from the workspace during the run is not added again. A
job queued before ``stations_added`` (from before this was built) adds its stations there.

A station's ``origin`` (:class:`Station`) holds the batch's results, when it has some
(``job``, ``outputs``, ``inputs``), and the state of its latest batch run (``run``):
``{"job", "state", "error"}``, ``state`` being ``waiting``, ``done``, ``failed`` or
``not_run``. :func:`run_states` reads it, live while the job runs, and
:func:`run_progress` the run as a whole, for the workspace's overview (#234).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from climpact_web.batch import check
from climpact_web.batch.models import BatchRun
from climpact_web.jobs.models import Job, Status

JOB_METADATA = "batch_metadata.txt"  # the metadata file of the ready stations, in input/
JOB_STATIONS = "stations"  # their station files, in input/
ADDED = "stations_added"  # a batch job's parameter: its stations were added when queued

# A station's state in its run (the Stations table's indices state, #234).
WAITING, CALCULATING, DONE, NOT_RUN, FAILED = "waiting", "calculating", "done", "not_run", "failed"
# The runner's states (``jobs.runners.BatchStatus``) as the station's.
RUNNER_STATES = {
    "waiting": WAITING,
    "running": CALCULATING,
    "done": DONE,
    "failed": FAILED,
    "skipped": NOT_RUN,
}


def batch_index_settings() -> dict:
    """The index settings a batch's workspace starts with: the defaults, without a custom
    index, as Climpact for R's batch calculates none."""
    from climpact_web.stations.workspace import default_settings

    out = default_settings()
    out["params"]["custom"] = None
    return out


def job_stations(job: Job) -> dict[str, check.StationCheck]:
    """The stations a batch job ran, by name, from the metadata file it was given (not the
    batch's check, which a later upload may have changed)."""
    path = job.input_dir / JOB_METADATA
    try:
        raw = path.read_bytes()
    except OSError:
        return {}
    return {s.name: s for s in check.check_metadata(raw, check.BatchCheck())}


def batch_inputs(station, job: Job, entry: check.StationCheck, file_hash: str) -> dict:
    """The inputs the batch's results for ``station`` were produced from (#179): the file
    and details the job was given, the run's base period and custom index, its metadata
    line's index values and R's default thresholds (a batch takes no others). The output
    options are the workspace's, as ``plots`` is an option of the run, not an input of its
    results. When the station's or the workspace's differ, the station shows its results
    as out of date."""
    from climpact_web.stations.forms import QCParamsForm
    from climpact_web.stations.workspace import current_inputs, workspace_settings

    params = job.params or {}
    inputs = current_inputs(station)
    inputs["file"] = file_hash
    # Add stations (#233) names a batch's stations: the job ran each under its name in the
    # batch (the file's stem, as R names them), the station has the name the user gave.
    names = params.get("names") or {}
    inputs["metadata"].update(
        name=names.get(entry.name, entry.name),
        latitude=entry.latitude,
        longitude=entry.longitude,
        base_start=params.get("base_start", 1971),
        base_end=params.get("base_end", 2000),
    )
    inputs["qc"] = QCParamsForm.initial_for({})
    settings = workspace_settings(station.workspace)
    settings["params"]["custom"] = params.get("custom")
    settings["params"].update(entry.params or {})
    inputs["settings"] = settings
    return inputs


# ---- adding the stations -----------------------------------------------------------------


def _read(path) -> tuple[str | None, object]:
    """A station file's text, as a station keeps it, and its inspection; (None, None) when
    it is missing or cannot be read."""
    from climpact_web.stations.station_file import inspect_station_bytes

    try:
        inspection = inspect_station_bytes(path.read_bytes())
    except OSError:
        return None, None
    return (inspection.text, inspection) if inspection.ok else (None, None)


def _place(run: BatchRun, existing: dict, name: str, station_file: str, entry: dict, path):
    """The workspace's station of the batch's station ``name``, made or updated with its
    file (when it can be read) and details; not saved."""
    from climpact_web.stations.models import Source, Station, Step

    station = existing.get(name)
    if station is None:
        station = Station(workspace=run.workspace, owner=run.owner, source=Source.BATCH)
    station.file_name = station_file[:255]
    # The name the user gave on Add stations (#233), else the batch's (the file's stem).
    station.station_name = (entry.get("station_name") or name)[:100]
    station.latitude, station.longitude = entry["latitude"], entry["longitude"]
    text, inspection = _read(path) if path is not None else (None, None)
    if text is not None:
        station.summary = inspection.summary
        station.warnings = inspection.warnings
        station.save_station_text(text)
        if entry.get("ready"):
            station.advance_to(Step.QC)
    origin = dict(station.origin or {})
    # The station's own index values: its metadata line's (Add stations keeps only those,
    # the job's metadata file has the workspace's for the others).
    own = entry["own_params"] if "own_params" in entry else entry["params"]
    origin.update(batch=str(run.pk), station=name, params=own)
    station.origin = origin
    return station


def _existing(run: BatchRun) -> dict:
    from climpact_web.stations.models import Station

    return {
        (s.origin or {}).get("station"): s
        for s in Station.objects.filter(workspace=run.workspace, origin__batch=str(run.pk))
    }


def add_stations(run: BatchRun, job: Job, skipped: list[dict]) -> None:
    """Add every station of the batch's check to its workspace as its job is queued: those
    that will run, waiting, and those left out (``skipped``, with why), not run. A station
    of an earlier run of the batch keeps the results it shows until this run's replace them
    (:func:`fill_workspace`); its file and details are this run's from now on."""
    reasons = {s["name"]: s["error"] for s in skipped}
    with transaction.atomic():
        existing = _existing(run)
        for s in run.report.get("stations", []):
            ready = s["status"] == "ready"
            path = run.files_dir / s["station_file"] if "/" not in s["station_file"] else None
            entry = {**s, "ready": ready}
            station = _place(run, existing, s["name"], s["station_file"], entry, path)
            state = {"job": str(job.pk), "state": WAITING if ready else NOT_RUN}
            if not ready:
                state["error"] = reasons.get(s["name"], "")
            station.origin["run"] = state
            station.touch()
            station.save()


def fill_workspace(run: BatchRun) -> None:
    """Record how the batch's finished job went on its workspace's stations, once per run
    (see the module). Does nothing until the job has succeeded."""
    job = run.job
    if job is None or job.status != Status.SUCCEEDED or run.filled_job_id == job.pk:
        return
    with transaction.atomic():
        # One request fills them in: another waits here, then finds them filled.
        locked = BatchRun.objects.select_for_update().get(pk=run.pk)
        if locked.filled_job_id != job.pk:
            _fill(locked, job)
            locked.filled_job = job
            locked.save(update_fields=["filled_job"])
    run.filled_job = job


def _fill(run: BatchRun, job: Job) -> None:
    from climpact_web.stations.models import Step, file_digest

    added = bool((job.params or {}).get(ADDED))
    listed = job_stations(job)
    existing = _existing(run)
    for result in job.result.get("stations", []):
        name = result["name"]
        entry = listed.get(name)
        station = existing.get(name)
        if entry is None or (station is None and added):
            continue  # deleted from the workspace during the run
        path = job.input_dir / JOB_STATIONS / entry.station_file
        if station is None:  # a job from before ``stations_added``
            details = {
                "latitude": entry.latitude,
                "longitude": entry.longitude,
                "params": entry.params,
                "ready": True,
            }
            station = _place(run, existing, name, entry.station_file, details, path)
        origin = dict(station.origin)
        if result.get("ok"):
            text, _inspection = _read(path)
            if text is None:
                continue
            _forget_older_jobs(station, job)
            origin.update(
                job=str(job.pk),
                outputs=result.get("folder"),
                inputs=batch_inputs(station, job, entry, file_digest(text)),
                run={"job": str(job.pk), "state": DONE},
            )
        else:
            # No results, not an earlier run's: the station failed with this run's inputs.
            _forget_older_jobs(station, job)
            for key in ("job", "outputs", "inputs"):
                origin.pop(key, None)
            # It opens on its Indices, which say nothing was calculated and lead to the
            # settings: the fix is usually there (another base period, say).
            if station.station_file.is_file():
                station.advance_to(Step.INDICES)
            origin["run"] = {
                "job": str(job.pk),
                "state": FAILED,
                "error": plain_error(result.get("error"), job),
            }
        station.origin = origin
        station.touch()
        station.save()
    if not added:  # the stations the check left out, from before ``stations_added``
        for item in job.result.get("skipped", []):
            if item["name"] in existing:
                continue
            details = {"latitude": None, "longitude": None, "params": {}, "ready": False}
            file_name = item.get("station_file", "")
            station = _place(run, existing, item["name"], file_name, details, None)
            station.origin["run"] = {"job": str(job.pk), "state": NOT_RUN, "error": item["error"]}
            station.touch()
            station.save()


def _forget_older_jobs(station, job: Job) -> None:
    """A new run of the batch: its results replace what the station showed, so the
    station's own checks and runs from before it go. One queued since (a change to the
    workspace's settings during the run) stays, and shows once it has finished."""
    for field in ("qc_job", "indices_job", "sector_job"):
        own = getattr(station, field)
        if own is not None and own.created_at < job.created_at:
            setattr(station, field, None)


def batch_stations(run: BatchRun) -> dict[str, object]:
    """The workspace's stations from this batch, by their name in the batch."""
    return _existing(run)


# ---- the run's state, for the workspace's overview (#234) --------------------------------


def station_status(job: Job) -> list[dict]:
    """Each station's progress in a batch job, from the runner's ``stations.json`` (written
    as it goes) or, once the job has succeeded, from its result: ``{"name", "state",
    "step", "total", "error", ...}``, ``state`` as the runner's (``waiting``, ``running``,
    ``done``, ``failed``, ``skipped``)."""
    from climpact_web.jobs.runners import STATIONS_FILE

    if job.status == Status.SUCCEEDED and job.result.get("stations") is not None:
        rows = []
        for s in job.result["stations"]:
            rows.append({**s, "state": "done" if s["ok"] else "failed"})
        for s in job.result.get("skipped", []):
            rows.append({**s, "state": "skipped", "ok": False})
        return rows
    try:
        data = json.loads((job.output_dir / STATIONS_FILE).read_text())
    except (OSError, ValueError):
        return []
    return data.get("stations", [])


def plain_error(text: str | None, job: Job) -> str:
    """A station's error as the user sees it: without the exception's class name or the
    job folder's path (the error file keeps the text as written)."""
    if not text:
        return ""
    text = text.replace(str(job.input_dir) + "/", "").replace(str(job.output_dir) + "/", "")
    head, sep, rest = text.partition(": ")
    if sep and head.isidentifier() and head[:1].isupper() and head.endswith(("Error", "Exception")):
        text = rest
    if text.startswith("station file not found: "):
        text = _("The station file was not found.")
    return text


@dataclass(frozen=True)
class RunState:
    """A station's state in its latest run: ``state`` (``waiting``, ``calculating``,
    ``done``, ``not_run`` or ``failed``), how far a calculating one is (``percent``), and
    why one failed or was not run (``error``, in words). ``job`` is the run's job."""

    state: str
    percent: int | None = None
    error: str = ""
    job: Job | None = None


def _percent(step: int, total: int) -> int:
    return int(100 * step / total) if total else 0


def _own_state(job: Job) -> RunState | None:
    """The state of a station's own run (a recalculation in the workspace), or None when
    it was cancelled, so the batch's shows."""
    if job.status == Status.QUEUED:
        return RunState(WAITING, job=job)
    if job.status == Status.RUNNING:
        return RunState(CALCULATING, job.percent, job=job)
    if job.status == Status.SUCCEEDED:
        return RunState(DONE, job=job)
    if job.status == Status.FAILED:
        return RunState(FAILED, error=plain_error(job.error, job), job=job)
    return None


def run_states(stations) -> dict:
    """Each station's :class:`RunState`, by its id: its own run when one was queued after
    the batch's (a change to the workspace's settings), else its batch run's, live from
    the runner while the job runs. A station of no batch with no run of its own has
    none."""
    stations = list(stations)
    job_ids = {(s.origin or {}).get("run", {}).get("job") for s in stations} - {None}
    jobs = {str(j.pk): j for j in Job.objects.filter(pk__in=job_ids)}
    live: dict[str, dict] = {}
    out = {}
    for station in stations:
        recorded = (station.origin or {}).get("run") or {}
        batch_job = jobs.get(recorded.get("job"))
        own = station.indices_job
        if own is not None and (batch_job is None or own.created_at > batch_job.created_at):
            state = _own_state(own)
            if state is not None:
                out[station.pk] = state
                continue
        if not recorded or batch_job is None:
            continue
        name = (station.origin or {}).get("station") or ""
        out[station.pk] = _batch_state(name, recorded, batch_job, live)
    return out


def _batch_state(name: str, recorded: dict, job: Job, live: dict) -> RunState:
    state = recorded.get("state", WAITING)
    if state != WAITING:  # recorded when queued (not run) or when filled in
        return RunState(state, error=recorded.get("error", ""), job=job)
    if job.status == Status.FAILED:
        return RunState(FAILED, error=plain_error(job.error, job), job=job)
    if job.status == Status.CANCELLED:
        return RunState(NOT_RUN, error=_("The run was cancelled."), job=job)
    key = str(job.pk)
    if key not in live:
        live[key] = {s["name"]: s for s in station_status(job)}
    row = live[key].get(name)
    if row is None:
        return RunState(WAITING, job=job)
    state = RUNNER_STATES.get(row.get("state"), WAITING)
    if state == CALCULATING:
        return RunState(state, _percent(row.get("step", 0), row.get("total", 0)), job=job)
    if state == FAILED:
        return RunState(state, error=plain_error(row.get("error"), job), job=job)
    return RunState(state, job=job)


def run_state(station) -> RunState | None:
    """One station's :class:`RunState` (see :func:`run_states`)."""
    return run_states([station]).get(station.pk)


@dataclass(frozen=True)
class RunProgress:
    """A batch run as a whole, for the run status line (#234): how many of the stations
    it calculates are ``done`` of ``total`` (those not run are not counted), how many
    failed, are calculating or waiting, and were not run, how long it has taken
    (``elapsed``) and is likely to take still (``remaining``), and whether it has
    ``finished``."""

    total: int
    done: int
    failed: int
    calculating: int
    waiting: int
    not_run: int
    elapsed: dt.timedelta | None
    remaining: dt.timedelta | None
    finished: bool
    status: str


def run_progress(run: BatchRun, now: dt.datetime | None = None) -> RunProgress | None:
    """The batch's latest run (:class:`RunProgress`); None before it has been queued."""
    job = run.job
    if job is None:
        return None
    now = now or timezone.now()
    counts = dict.fromkeys((WAITING, CALCULATING, DONE, FAILED, NOT_RUN), 0)
    rows = station_status(job)
    for row in rows:
        counts[RUNNER_STATES.get(row.get("state"), WAITING)] += 1
    if not rows:  # queued: the runner has not written its list yet
        counts[WAITING] = len(job_stations(job))
        counts[NOT_RUN] = len((job.params or {}).get("skipped") or [])
    total = sum(counts.values()) - counts[NOT_RUN]
    return RunProgress(
        total=total,
        done=counts[DONE],
        failed=counts[FAILED],
        calculating=counts[CALCULATING],
        waiting=counts[WAITING],
        not_run=counts[NOT_RUN],
        elapsed=job.elapsed(now),
        remaining=None if job.is_finished else job.remaining(now),
        finished=job.is_finished,
        status=job.status,
    )

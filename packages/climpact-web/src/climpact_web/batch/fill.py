"""A batch fills its workspace (#255, part 3 of #231).

A batch is a way to fill a workspace, not a separate kind of result (#230, decision 5). Once
its job has finished, each station it calculated becomes a :class:`Station` of the batch's
workspace, showing the batch's results for it (``Station.origin``) until a change to the
workspace's settings recalculates it with ``station`` jobs (:mod:`climpact_web.stations.
calculation`). A station that failed in the run, or was left out before it, is not added:
it has no results to show, and its error stays on the batch results page and in the zip.

:func:`fill_workspace` adds them the first time the batch results are shown after the run
(the results page and its progress fragment, which stand in as the workspace page until
#234) or a station is opened from them. It reads each station's file from the job's
``input/`` folder, so it is not done in a migration. It is idempotent:
``BatchRun.filled_job`` records the run whose stations were added, so a station the user
deletes from the workspace is not added again for that run. A new run of the same batch
(from its check page) adds its stations again: those still in the workspace show its
results in place of what they showed, the others are added.
"""

from __future__ import annotations

from django.db import transaction

from climpact_web.batch import check
from climpact_web.batch.models import BatchRun
from climpact_web.jobs.models import Job, Status

JOB_METADATA = "batch_metadata.txt"  # the metadata file of the ready stations, in input/
JOB_STATIONS = "stations"  # their station files, in input/


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


def batch_inputs(station, job: Job) -> dict:
    """The inputs the batch's results for ``station`` were produced from (#179): its file
    and details, the run's base period and custom index, its metadata line's index values
    and R's default thresholds (a batch takes no others). The output options are the
    workspace's, as ``plots`` is an option of the run, not an input of its results. When
    the workspace's settings differ, the station shows its results as out of date."""
    from climpact_web.stations.forms import QCParamsForm
    from climpact_web.stations.workspace import current_inputs, workspace_settings

    params = job.params or {}
    inputs = current_inputs(station)
    inputs["metadata"]["base_start"] = params.get("base_start", 1971)
    inputs["metadata"]["base_end"] = params.get("base_end", 2000)
    inputs["qc"] = QCParamsForm.initial_for({})
    settings = workspace_settings(station.workspace)
    settings["params"]["custom"] = params.get("custom")
    settings["params"].update((station.origin or {}).get("params") or {})
    inputs["settings"] = settings
    return inputs


def fill_workspace(run: BatchRun) -> None:
    """Add the stations the batch's finished job calculated to its workspace, once per
    run (see the module). Does nothing until the job has succeeded."""
    job = run.job
    if job is None or job.status != Status.SUCCEEDED or run.filled_job_id == job.pk:
        return
    with transaction.atomic():
        # One request adds them: another waits here, then finds them added.
        locked = BatchRun.objects.select_for_update().get(pk=run.pk)
        if locked.filled_job_id != job.pk:
            _add_stations(locked, job)
            locked.filled_job = job
            locked.save(update_fields=["filled_job"])
    run.filled_job = job


def _add_stations(run: BatchRun, job: Job) -> None:
    from climpact_web.stations.models import Source, Station, Step
    from climpact_web.stations.station_file import inspect_station_bytes

    listed = job_stations(job)
    existing = {
        (s.origin or {}).get("station"): s
        for s in Station.objects.filter(workspace=run.workspace, origin__batch=str(run.pk))
    }
    for result in job.result.get("stations", []):
        name = result["name"]
        entry = listed.get(name)
        if not result.get("ok") or entry is None:
            continue
        station = existing.get(name)
        path = job.input_dir / JOB_STATIONS / entry.station_file
        try:
            inspection = inspect_station_bytes(path.read_bytes())
        except OSError:
            continue
        if not inspection.ok:
            continue
        if station is None:
            station = Station(workspace=run.workspace, owner=run.owner, source=Source.BATCH)
        else:
            # A new run of the batch: its results replace what the station showed.
            station.qc_job = station.indices_job = station.sector_job = None
        station.workspace = run.workspace
        station.file_name = entry.station_file[:255]
        station.summary = inspection.summary
        station.warnings = inspection.warnings
        station.station_name = name
        station.latitude, station.longitude = entry.latitude, entry.longitude
        station.advance_to(Step.QC)
        station.origin = {
            "batch": str(run.pk),
            "job": str(job.pk),
            "station": name,
            "params": entry.params,
            "outputs": result.get("folder"),
        }
        station.save_station_text(inspection.text)
        station.origin["inputs"] = batch_inputs(station, job)
        station.touch()
        station.save()


def batch_stations(run: BatchRun) -> dict[str, object]:
    """The workspace's stations from this batch, by their name in the batch."""
    from climpact_web.stations.models import Station

    return {
        (s.origin or {}).get("station"): s
        for s in Station.objects.filter(workspace=run.workspace_id, origin__batch=str(run.pk))
    }

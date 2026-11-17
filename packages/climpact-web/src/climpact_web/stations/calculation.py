"""Queueing a station's quality checks and index calculation (#77, #78), the speculative
run (#178), and bringing the workspace up to date after a change (#179).

The station flow has no Calculate step since #178. Once the user confirms the station
details, the checks are queued (:func:`queue_qc`) and :func:`speculate` queues a
calculation with the settings the form would start from (:func:`previous_params`: the
defaults, or the last run's). It runs while the user looks at the quality checks, so "Use
this data" usually opens finished results. The settings are the Inputs panel's Index
settings sheet (#199), which queues an ordinary run (:func:`queue_station_run`).

A speculative run is a job with ``params["speculative"]`` true (``jobs.models.SPECULATIVE``).
In hosted mode it is queued only when the worker has room
(``core.limits.check_speculative_quotas``); a refusal is silent, and "See results" then
queues the run (:func:`commit`), which makes it an ordinary job.

A change to the file or the station details (#179) keeps every job: each records its
inputs, and :mod:`.workspace` shows its results as out of date. :func:`bring_up_to_date`
cancels what is still queued for the old inputs and queues the checks and the run again,
each naming the finished job it replaces (``workspace.REPLACES``), whose results stay on
the page until the new ones are ready. The replacement run is speculative until the user
has chosen to use the data, and an ordinary job after that, as the user's own calculation.

The base period, the thresholds and the index settings are the workspace's (#254). A change
to them (:func:`change_settings`) does the same for every station of the workspace at once.
All the jobs one change queues carry its id (``params["change"]``), so the hosted limits
count them as one job, and :func:`undo` can put the settings back, cancel them and show the
earlier results again while they are still on the way.
"""

from __future__ import annotations

import logging
import uuid

from django.core.files import File
from django.utils.translation import gettext as _

from climpact_web.core.limits import Refused
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.views import create_job, promote
from climpact_web.stations import workspace
from climpact_web.stations.forms_indices import IndexParamsForm, initial_from_params
from climpact_web.stations.models import STATION_FILE, Station, Step, Workspace
from climpact_web.stations.workspace import REPLACES

logger = logging.getLogger("climpact_web.stations")


def station_title(analysis: Station) -> str:
    """The plots' default title: R's ``title.station`` (the core's ``station_title``)."""
    from climpact.config import StationMetadata
    from climpact.plots import station_title as core_title

    return core_title(
        StationMetadata(analysis.station_name, analysis.latitude or 0.0, analysis.longitude or 0.0)
    )


def previous_params(analysis: Station) -> tuple[dict, str, bool, bool, bool, str]:
    """The parameters to start the form from and to run with: the workspace's settings,
    with the station's own index values (``workspace.station_settings``). Returns (params,
    plot title, plots, zip, report, where they come from: ``batch`` when the station has
    values of its own from a batch's metadata file, ``workspace`` when the workspace's
    settings were changed, else ``default``)."""
    settings = workspace.station_settings(analysis)
    if workspace.own_params(analysis):
        source = "batch"
    elif analysis.workspace.index_settings:
        source = "workspace"
    else:
        source = "default"
    return (
        settings["params"],
        settings["plot_title"],
        settings["plots"],
        settings["zip"],
        settings["report"],
        source,
    )


def settings_form(analysis: Station, previous=None, **initial) -> IndexParamsForm:
    """The settings form, unbound, with the values of :func:`previous_params`."""
    params, plot_title, plots, zip_, report, _source = previous or previous_params(analysis)
    values = initial_from_params(params, plot_title, plots, zip_, report)
    values.update(initial)
    return IndexParamsForm(initial=values, station_title=station_title(analysis))


def bound_settings(analysis: Station, previous=None) -> IndexParamsForm:
    """The form as if submitted unchanged: what the Calculate button sent before #178."""
    from django import forms

    unbound = settings_form(analysis, previous)
    data = {}
    for name, field in unbound.fields.items():
        value = unbound.get_initial_for_field(field, name)
        if isinstance(field, forms.BooleanField):
            if value:
                data[name] = "on"
        elif value is not None:
            data[name] = value
    return IndexParamsForm(data, station_title=station_title(analysis))


def station_params(analysis: Station, form: IndexParamsForm) -> dict:
    """The ``station`` job's parameters from a valid settings form."""
    data = form.cleaned_data
    return {
        "station_file": STATION_FILE,
        "metadata": analysis.metadata,
        "params": form.job_params(),
        "qc": workspace.qc_values(analysis),  # Quality's thresholds (#77)
        "plot_title": data["plot_title"],
        "plots": data["plots"],
        "zip": data["zip"],
        "report": data["report"],
    }


def _create(request, analysis: Station, params: dict, speculative=False, change="") -> Job:
    with analysis.station_file.open("rb") as handle:
        return create_job(
            request,
            "station",
            params,
            {STATION_FILE: File(handle)},
            title=analysis.station_name,
            speculative=speculative,
            inputs=workspace.job_inputs(analysis, "station", params),
            change=change,
        )


# ---- the quality checks (#77) ------------------------------------------------------------


def qc_job_params(analysis: Station) -> dict:
    return {
        "station_file": STATION_FILE,
        "metadata": analysis.metadata,
        "qc": workspace.qc_values(analysis),
    }


def queue_qc(request, analysis: Station, change: str = "") -> Job:
    """Queue the quality checks of the analysis's file with its thresholds, replacing a
    check still waiting or running. The checks shown until it has finished are named in
    its ``replaces`` (#179); ``change``, the change it is queued for (#254)."""
    old = analysis.qc_job
    params = qc_job_params(analysis)
    if replaces := workspace.replaces_for(old):
        params[REPLACES] = replaces
    with analysis.station_file.open("rb") as handle:
        job = create_job(
            request,
            "qc",
            params,
            {STATION_FILE: File(handle)},
            title=_("%(name)s: quality checks") % {"name": analysis.station_name},
            inputs=workspace.job_inputs(analysis, "qc", params),
            change=change,
        )
    if old is not None and old.can_cancel:
        old.request_cancel()
    analysis.qc_job = job
    analysis.touch()
    analysis.save()
    return job


# ---- the index calculation (#78, #178) ---------------------------------------------------


def queue_station_run(
    request, analysis: Station, form: IndexParamsForm, change: str = ""
) -> Job | None:
    """Queue the calculation the user asked for (the Index settings sheet, or "Use this
    data" without a speculative run). A run of this analysis still waiting or running is
    cancelled, as this one replaces it; finished results stay on the page until the new
    run has finished (:data:`REPLACES`). The caller saves the analysis."""
    if not analysis.station_file.is_file():
        return None
    params = station_params(analysis, form)
    old = analysis.indices_job
    if old is not None and old.kind == "station" and (replaces := workspace.replaces_for(old)):
        params[REPLACES] = replaces  # the last finished results, shown until this finishes
    job = _create(request, analysis, params, change=change)
    if old is not None and old.can_cancel:
        old.request_cancel()
    analysis.indices_job = job
    return job


def speculate(request, analysis: Station, change: str = "") -> Job | None:
    """Queue a speculative run of the analysis with its settings (:func:`previous_params`),
    replacing one that is now stale. None, and
    nothing queued, when the data cannot be calculated yet, when the analysis shows a
    batch's results (``origin``), or when the hosted limits have no room. The caller saves
    the analysis."""
    old = analysis.indices_job
    analysis.cancel_speculative()
    if not (analysis.metadata_complete and analysis.station_file.is_file()):
        return None
    if workspace.batch_results(analysis) and analysis.indices_job is None:
        return None  # the batch's results are shown; the Index settings sheet recalculates
    form = bound_settings(analysis)
    if not form.is_valid():  # a batch line's settings the form no longer accepts
        return None
    params = station_params(analysis, form)
    if old is not None and old.kind == "station" and (replaces := workspace.replaces_for(old)):
        params[REPLACES] = replaces
    try:
        job = _create(request, analysis, params, speculative=True, change=change)
    except Refused as refused:
        logger.info("No speculative run for analysis %s: %s", analysis.pk, refused.reason)
        analysis.indices_job = None
        return None
    analysis.indices_job = job
    return job


def commit(request, analysis: Station) -> Job | None:
    """ "See results": the speculative run becomes the user's own, or, if there is none
    (refused, cancelled, failed), a run with the same settings is queued. The caller saves
    the analysis."""
    job = analysis.indices_job
    if job is not None and job.kind == "station" and job.status != Status.CANCELLED:
        promote(request, job)
        return job
    if workspace.batch_results(analysis) and job is None:
        return None  # the batch's results are the results until recalculated here
    form = bound_settings(analysis)
    if not form.is_valid():
        return None
    return queue_station_run(request, analysis, form)


def recalculate(request, analysis: Station) -> Job | None:
    """ "Recalculate" on out-of-date results (#179): bring the run waiting for the current
    inputs forward (a speculative one becomes the user's), or queue one with the latest
    settings. The caller saves the analysis."""
    job = analysis.indices_job
    if (
        job is not None
        and job.kind == "station"
        and job.can_cancel
        and not workspace.pending_changes(analysis, job, "station")
    ):
        promote(request, job)
        return job
    form = bound_settings(analysis)
    if not form.is_valid():
        return None
    return queue_station_run(request, analysis, form)


def replace_run(request, analysis: Station, change: str = "") -> Job | None:
    """Queue the run of the current inputs with the workspace's settings: a speculative
    one before "See results", the user's own after it. None when the hosted limits refuse
    it: the results then say they are out of date, with a "Recalculate" button. The caller
    saves the analysis."""
    if not workspace.committed(analysis):
        return speculate(request, analysis, change)
    if not (analysis.metadata_complete and analysis.station_file.is_file()):
        return None
    form = bound_settings(analysis)
    if not form.is_valid():
        return None
    try:
        return queue_station_run(request, analysis, form, change)
    except Refused as refused:
        logger.info("No replacement run for analysis %s: %s", analysis.pk, refused.reason)
        return None


def new_change() -> str:
    """An id for the jobs of one change (``params["change"]``)."""
    return uuid.uuid4().hex


def bring_up_to_date(request, analysis: Station) -> tuple[bool, bool]:
    """After a change to the station's own inputs, its file or its details (#179): bring
    the station up to date (:func:`refresh`), as one change. A change to one station's
    inputs can no longer be undone by undoing an earlier change to the settings, so that
    undo is forgotten. Returns whether the checks and the run were queued. Saves the
    analysis."""
    forget_undo(analysis.workspace)
    return refresh(request, analysis, new_change())


def refresh(request, analysis: Station, change: str) -> tuple[bool, bool]:
    """Cancel what was queued for the station's old inputs (:func:`workspace.settle`), then
    queue the checks and the run of the new ones for ``change``, when the data can be
    checked and the details fit it. The results of the old inputs stay shown, out of date,
    until then. Returns whether the checks and the run were queued. Saves the analysis."""
    workspace.settle(analysis)
    queued_qc = queued_run = False
    ready = (
        analysis.reached(Step.QC)
        and analysis.station_file.is_file()
        and workspace.details_valid(analysis)
    )
    if ready:
        qc = analysis.qc_job
        if qc is None or workspace.pending_changes(analysis, qc, "qc"):
            queue_qc(request, analysis, change)
            queued_qc = True
        run = analysis.indices_job
        if run is None:  # none yet, or a batch's results (origin)
            batch = workspace.batch_job(analysis)
            needed = batch is None or bool(workspace.run_changes(analysis, batch))
        else:
            needed = bool(workspace.pending_changes(analysis, run, "station"))
        if needed:
            queued_run = replace_run(request, analysis, change) is not None
    analysis.touch()
    analysis.save()
    return queued_qc, queued_run


# ---- a change to the workspace's settings, and its undo (#254) ---------------------------

SETTINGS_FIELDS = ("base_start", "base_end", "qc_params", "index_settings")


def forget_undo(space: Workspace) -> None:
    """Drop the record of the last change to the settings: it can no longer be undone."""
    if space.undo:
        space.undo = {}
        Workspace.objects.filter(pk=space.pk).update(undo={})


def workspace_stations(analysis: Station) -> list[Station]:
    """Every station of the analysis's workspace, ``analysis`` itself among them (the same
    object, so the caller sees what is changed on it)."""
    others = analysis.workspace.stations.exclude(pk=analysis.pk).select_related(
        "qc_job", "indices_job"
    )
    return [analysis, *others]


def change_settings(request, analysis: Station, own: dict | None = None, **values) -> bool:
    """Change the settings of the analysis's workspace (``values``: any of
    :data:`SETTINGS_FIELDS`) and, with ``own``, index values that are the analysis's own
    (``origin["params"]``, a batch's metadata line). Every station of the workspace goes
    out of date at once, and its checks (when the thresholds changed) and its run are
    queued again (:func:`refresh`), all as one change: one job for the hosted limits, which
    are checked first, so a refusal changes nothing. The settings, jobs and own values
    before it are kept for :func:`undo`. Returns False when nothing changed."""
    from climpact_web.core.limits import check_job_quotas

    space = analysis.workspace
    before = {name: getattr(space, name) for name in SETTINGS_FIELDS}
    changed = {k: v for k, v in values.items() if k in SETTINGS_FIELDS and before[k] != v}
    own_before = dict((analysis.origin or {}).get("params") or {})
    own_after = {**own_before, **(own or {})}
    if not changed and own_after == own_before:
        return False
    check_job_quotas(request)  # the change is one job: refused now, nothing is changed
    stations = workspace_stations(analysis)
    change = new_change()
    space.undo = {
        "change": change,
        "settings": before,
        "stations": {
            str(station.pk): {
                "qc_job": str(station.qc_job_id) if station.qc_job_id else None,
                "indices_job": str(station.indices_job_id) if station.indices_job_id else None,
                "own": (station.origin or {}).get("params"),
            }
            for station in stations
        },
    }
    for name, value in changed.items():
        setattr(space, name, value)
    space.touch()
    space.save()
    if own_after != own_before:
        analysis.origin = {**analysis.origin, "params": own_after}
    for station in stations:
        station.workspace = space
        refresh(request, station, change)
    if not workspace.change_jobs(change).exists():
        forget_undo(space)  # nothing was queued: there is nothing to undo
    return True


def undo(space: Workspace) -> bool:
    """Undo the workspace's last change to its settings while its recalculation is still on
    the way (``workspace.undo_available``): put the settings and the stations' own values
    back, cancel the jobs the change queued, and show each station's earlier checks and
    results again, which are current once more. Returns False when it is too late."""
    if not workspace.undo_available(space):
        return False
    record = space.undo
    for job in workspace.change_jobs(record["change"]):
        if job.can_cancel:
            job.request_cancel()
    for name, value in record["settings"].items():
        setattr(space, name, value)
    space.undo = {}
    space.touch()
    space.save()
    saved = record.get("stations") or {}
    ids = {pk for jobs in saved.values() for k, pk in jobs.items() if k.endswith("_job") and pk}
    jobs = {str(job.pk): job for job in Job.objects.filter(pk__in=ids)}
    for station in space.stations.all():
        before = saved.get(str(station.pk))
        if before is None:
            continue
        station.qc_job = jobs.get(before.get("qc_job") or "")
        station.indices_job = jobs.get(before.get("indices_job") or "")
        if station.origin:
            station.origin = {**station.origin, "params": before.get("own") or {}}
        workspace.restore_if_cancelled(station)
        station.touch()
        station.save()
    return True

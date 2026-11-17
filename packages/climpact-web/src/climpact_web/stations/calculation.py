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

A change to the file, the station details or the thresholds (#179) keeps every job: each
records its inputs, and :mod:`.workspace` shows its results as out of date.
:func:`bring_up_to_date` cancels what is still queued for the old inputs and queues the
checks and the run again, each naming the finished job it replaces
(``workspace.REPLACES``), whose results stay on the page until the new ones are ready. The
replacement run is speculative until the user has chosen to use the data, and an ordinary
job after that, as the user's own calculation.
"""

from __future__ import annotations

import logging

from django.core.files import File
from django.utils.translation import gettext as _

from climpact_web.core.limits import Refused
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.views import create_job, promote
from climpact_web.stations import workspace
from climpact_web.stations.forms_indices import IndexParamsForm, initial_from_params
from climpact_web.stations.models import STATION_FILE, Station, Step
from climpact_web.stations.workspace import REPLACES, batch_job

logger = logging.getLogger("climpact_web.stations")


def station_title(analysis: Station) -> str:
    """The plots' default title: R's ``title.station`` (the core's ``station_title``)."""
    from climpact.config import StationMetadata
    from climpact.plots import station_title as core_title

    return core_title(
        StationMetadata(analysis.station_name, analysis.latitude or 0.0, analysis.longitude or 0.0)
    )


def batch_custom(job: Job | None) -> dict | None:
    return (job.params or {}).get("custom") if job is not None else None


def previous_params(analysis: Station) -> tuple[dict, str, bool, bool, bool, str]:
    """The parameters to start the form from: the last calculation's, else the batch
    station's (``origin``), else the defaults. Returns (params, plot title, plots, zip,
    report, where they come from)."""
    job = analysis.indices_job
    if job is not None and job.kind == "station":
        p = job.params or {}
        return (
            p.get("params") or {},
            p.get("plot_title") or "",
            bool(p.get("plots", True)),
            bool(p.get("zip", True)),
            bool(p.get("report", True)),
            "job",
        )
    origin = analysis.origin or {}
    if origin.get("params"):
        params = dict(origin["params"])
        params["custom"] = batch_custom(batch_job(analysis))
        return params, "", True, True, True, "batch"
    return {}, "", True, True, True, "default"


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


def _create(request, analysis: Station, params: dict, speculative=False) -> Job:
    with analysis.station_file.open("rb") as handle:
        return create_job(
            request,
            "station",
            params,
            {STATION_FILE: File(handle)},
            title=analysis.station_name,
            speculative=speculative,
            inputs=workspace.job_inputs(analysis, "station", params),
        )


# ---- the quality checks (#77) ------------------------------------------------------------


def qc_job_params(analysis: Station) -> dict:
    return {
        "station_file": STATION_FILE,
        "metadata": analysis.metadata,
        "qc": workspace.qc_values(analysis),
    }


def queue_qc(request, analysis: Station) -> Job:
    """Queue the quality checks of the analysis's file with its thresholds, replacing a
    check still waiting or running. The checks shown until it has finished are named in
    its ``replaces`` (#179)."""
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
        )
    if old is not None and old.can_cancel:
        old.request_cancel()
    analysis.qc_job = job
    analysis.touch()
    analysis.save()
    return job


# ---- the index calculation (#78, #178) ---------------------------------------------------


def queue_station_run(request, analysis: Station, form: IndexParamsForm) -> Job | None:
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
    job = _create(request, analysis, params)
    if old is not None and old.can_cancel:
        old.request_cancel()
    analysis.indices_job = job
    return job


def speculate(request, analysis: Station, previous=None) -> Job | None:
    """Queue a speculative run of the analysis with the settings the form would start from
    (``previous``, else :func:`previous_params`), replacing one that is now stale. None, and
    nothing queued, when the data cannot be calculated yet, when the analysis shows a
    batch's results (``origin``), or when the hosted limits have no room. The caller saves
    the analysis."""
    old = analysis.indices_job
    analysis.cancel_speculative()
    if not (analysis.metadata_complete and analysis.station_file.is_file()):
        return None
    if analysis.origin and analysis.indices_job is None:
        return None  # the batch's results are shown; the Index settings sheet recalculates
    form = bound_settings(analysis, previous)
    if not form.is_valid():  # a batch line's settings the form no longer accepts
        return None
    params = station_params(analysis, form)
    if old is not None and old.kind == "station" and (replaces := workspace.replaces_for(old)):
        params[REPLACES] = replaces
    try:
        job = _create(request, analysis, params, speculative=True)
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
    if analysis.origin and job is None:
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


def replace_run(request, analysis: Station, previous=None) -> Job | None:
    """Queue the run of the current inputs with the latest settings (``previous``, else
    :func:`previous_params`): a speculative one before "See results", the user's own
    after it. None when the hosted limits refuse it: the results then say they are out of
    date, with a "Recalculate" button. The caller saves the analysis."""
    if not workspace.committed(analysis):
        return speculate(request, analysis, previous)
    if not (analysis.metadata_complete and analysis.station_file.is_file()):
        return None
    form = bound_settings(analysis, previous)
    if not form.is_valid():
        return None
    try:
        return queue_station_run(request, analysis, form)
    except Refused as refused:
        logger.info("No replacement run for analysis %s: %s", analysis.pk, refused.reason)
        return None


def bring_up_to_date(request, analysis: Station) -> tuple[bool, bool]:
    """After a change to the file, the station details or the thresholds (#179): cancel
    what was queued for the old inputs (:func:`workspace.settle`), then queue the checks and
    the run of the new ones, when the data can be checked and the details fit it. The
    results of the old inputs stay shown, out of date, until then. Returns whether the
    checks and the run were queued. Saves the analysis."""
    previous = previous_params(analysis)
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
            queue_qc(request, analysis)
            queued_qc = True
        run = analysis.indices_job
        if run is None:  # none yet, or a batch's results (origin)
            batch = workspace.batch_job(analysis)
            needed = batch is None or bool(workspace.run_changes(analysis, batch))
        else:
            needed = bool(workspace.pending_changes(analysis, run, "station"))
        if needed:
            queued_run = replace_run(request, analysis, previous) is not None
    analysis.touch()
    analysis.save()
    return queued_qc, queued_run

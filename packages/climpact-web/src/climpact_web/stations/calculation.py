"""Queueing a station's index calculation (#78), and the speculative run (#178).

The station flow has no Calculate step since #178. Once the user confirms the station
details, :func:`speculate` queues a calculation with the settings the form would start
from (:func:`previous_params`: the defaults, or the last run's). It runs while the user
looks at the quality checks, so "Use this data" usually opens finished results. The
settings are "Adjust and recalculate" on Results, which queues an ordinary run
(:func:`queue_station_run`) that replaces the results when it finishes.

A speculative run is a job with ``params["speculative"]`` true (``jobs.models.SPECULATIVE``).
It is cancelled whenever the file, the station details or the quality thresholds change
(``StationAnalysis.reset_later_steps``, :func:`speculate` replacing it), so a run of old
data is never shown as the results, and it becomes an ordinary job when the user chooses to
use the data (:func:`commit`). In hosted mode it is queued only when the worker has room
(``core.limits.check_speculative_quotas``); a refusal is silent, and "Use this data" then
queues the run.
"""

from __future__ import annotations

import logging

from django.core.files import File

from climpact_web.core.limits import Refused
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.views import create_job, promote
from climpact_web.stations.forms import QCParamsForm
from climpact_web.stations.forms_indices import IndexParamsForm, initial_from_params
from climpact_web.stations.models import STATION_FILE, StationAnalysis

logger = logging.getLogger("climpact_web.stations")

# The station job's ``params`` key naming the finished job a recalculation replaces: its
# results stay on the page, under the progress, until the new run has finished.
REPLACES = "replaces"


def station_title(analysis: StationAnalysis) -> str:
    """The plots' default title: R's ``title.station`` (the core's ``station_title``)."""
    from climpact.config import StationMetadata
    from climpact.plots import station_title as core_title

    return core_title(
        StationMetadata(analysis.station_name, analysis.latitude or 0.0, analysis.longitude or 0.0)
    )


def batch_job(analysis: StationAnalysis) -> Job | None:
    """The finished batch job an analysis was opened from, if it is still kept."""
    job_id = (analysis.origin or {}).get("job")
    if not job_id:
        return None
    return Job.objects.filter(pk=job_id, owner=analysis.owner, status=Status.SUCCEEDED).first()


def batch_custom(job: Job | None) -> dict | None:
    return (job.params or {}).get("custom") if job is not None else None


def previous_params(analysis: StationAnalysis) -> tuple[dict, str, bool, bool, bool, str]:
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


def settings_form(analysis: StationAnalysis, previous=None, **initial) -> IndexParamsForm:
    """The settings form, unbound, with the values of :func:`previous_params`."""
    params, plot_title, plots, zip_, report, _source = previous or previous_params(analysis)
    values = initial_from_params(params, plot_title, plots, zip_, report)
    values.update(initial)
    return IndexParamsForm(initial=values, station_title=station_title(analysis))


def bound_settings(analysis: StationAnalysis, previous=None) -> IndexParamsForm:
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


def station_params(analysis: StationAnalysis, form: IndexParamsForm) -> dict:
    """The ``station`` job's parameters from a valid settings form."""
    data = form.cleaned_data
    return {
        "station_file": STATION_FILE,
        "metadata": analysis.metadata,
        "params": form.job_params(),
        "qc": QCParamsForm.initial_for(analysis.qc_params),  # step 2's thresholds (#77)
        "plot_title": data["plot_title"],
        "plots": data["plots"],
        "zip": data["zip"],
        "report": data["report"],
    }


def _create(request, analysis: StationAnalysis, params: dict, speculative=False) -> Job:
    with analysis.station_file.open("rb") as handle:
        return create_job(
            request,
            "station",
            params,
            {STATION_FILE: File(handle)},
            title=analysis.station_name,
            speculative=speculative,
        )


def queue_station_run(request, analysis: StationAnalysis, form: IndexParamsForm) -> Job | None:
    """Queue the calculation the user asked for ("Adjust and recalculate", or "Use this
    data" without a speculative run). A run of this analysis still waiting or running is
    cancelled, as this one replaces it; finished results stay on the page until the new
    run has finished (:data:`REPLACES`). The caller saves the analysis."""
    if not analysis.station_file.is_file():
        return None
    params = station_params(analysis, form)
    old = analysis.indices_job
    if old is not None and old.kind == "station":
        if old.status == Status.SUCCEEDED:
            params[REPLACES] = str(old.pk)
        elif (old.params or {}).get(REPLACES):
            params[REPLACES] = old.params[REPLACES]  # still the last finished results
    job = _create(request, analysis, params)
    if old is not None and old.can_cancel:
        old.request_cancel()
    analysis.indices_job = job
    return job


def speculate(request, analysis: StationAnalysis, previous=None) -> Job | None:
    """Queue a speculative run of the analysis with the settings the form would start from
    (``previous``, else :func:`previous_params`), replacing one that is now stale. None, and
    nothing queued, when the data cannot be calculated yet, when the analysis shows a
    batch's results (``origin``), or when the hosted limits have no room. The caller saves
    the analysis."""
    analysis.cancel_speculative()
    if not (analysis.metadata_complete and analysis.station_file.is_file()):
        return None
    if analysis.origin and analysis.indices_job is None:
        return None  # the batch's results are shown; "Adjust and recalculate" is there
    form = bound_settings(analysis, previous)
    if not form.is_valid():  # a batch line's settings the form no longer accepts
        return None
    try:
        job = _create(request, analysis, station_params(analysis, form), speculative=True)
    except Refused as refused:
        logger.info("No speculative run for analysis %s: %s", analysis.pk, refused.reason)
        analysis.indices_job = None
        return None
    analysis.indices_job = job
    return job


def commit(request, analysis: StationAnalysis) -> Job | None:
    """ "Use this data": the speculative run becomes the user's own, or, if there is none
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

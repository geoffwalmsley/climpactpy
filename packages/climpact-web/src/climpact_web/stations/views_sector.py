"""Step 5 of a station (#90): compare the indices with yearly sector data.

Replaces the R app's step 4 (``modules/singleStationStep4UI.R``, ``singleStationStep4.R``,
``server/sector_correlation.R``). URLs (``/station/<id>/...``, private to the session like
the other steps):

``sector``            the form (GET; POST checks the file and queues a ``sector`` job), the
                      job's progress while it runs, then its results; ``?order=strength``
                      sorts the bar chart by the size of the correlation
``sector/progress``   htmx: the progress fragment; when the job ends it reloads the page
``sector-sample.csv`` Climpact for R's sample sector file (R links to it too)

The job runs the core's ``run_sector_correlation`` (the ``sector`` runner) on the run the
results dashboard shows: the analysis's own station job, or its batch station's outputs
(``origin``). A sector job made for another run of the indices is not shown.
"""

from __future__ import annotations

from django.core.files import File
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from climpact_web.core.limits import human_required
from climpact_web.core.navigation import station_steps
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.views import create_job, progress_context
from climpact_web.stations import sector_plots
from climpact_web.stations.models import STATION_FILE, StationAnalysis, Step
from climpact_web.stations.sector_file import (
    R_NO_COMMON_DATA,
    SAMPLE_FILE,
    SAMPLE_NAME,
    SECTOR_FILE,
    SectorForm,
)
from climpact_web.stations.views import get_analysis
from climpact_web.stations.views_indices import current_source


def sector_job(analysis: StationAnalysis, source) -> Job | None:
    """The analysis's sector job, if it was made from the run shown now."""
    job = analysis.sector_job
    if job is None or source is None:
        return None
    p = job.params or {}
    if p.get("station_job") != str(source.job.pk) or p.get("station") != source.station:
        return None
    return job


def phases(job: Job) -> list[dict]:
    """The stages of a sector run as a short list (done, current, failed, pending). The
    job's stage is the last one the core finished (``climpact.sector.sector_steps``)."""
    labels = (
        _("Read the station and sector data"),
        _("Calculate the correlations"),
        _("Write the tables and draw the plots"),
        _("Make the zip file"),
    )
    stage = job.stage or ""
    if job.status == Status.QUEUED:
        current = -1
    elif stage == "zip":
        current = 4
    elif stage == "write:index-sector":
        current = 3
    elif stage == "correlate" or stage.startswith("write:"):
        current = 2
    elif stage == "read":
        current = 1
    else:
        current = 0
    out = []
    for i, label in enumerate(labels):
        if job.status == Status.SUCCEEDED or i < current:
            state = "done"
        elif i == current:
            state = "failed" if job.status == Status.FAILED else "current"
        else:
            state = "pending"
        out.append({"label": label, "state": state})
    return out


def queue_sector(request, analysis: StationAnalysis, source, form: SectorForm) -> Job:
    params = {
        "station_job": str(source.job.pk),
        "station": source.station,
        "station_file": STATION_FILE,
        "sector_file": SECTOR_FILE,
        **form.job_params(analysis.station_name),
    }
    with analysis.station_file.open("rb") as handle:
        files = {STATION_FILE: File(handle), SECTOR_FILE: ContentFile(form.text_bytes)}
        job = create_job(request, "sector", params, files, title=analysis.station_name)
    old = analysis.sector_job
    if old is not None and old.can_cancel:
        old.request_cancel()
    analysis.sector_job = job
    analysis.advance_to(Step.SECTOR)
    analysis.touch()
    analysis.save()
    return job


def initial(analysis: StationAnalysis, job: Job | None) -> dict:
    """The form starts from the last comparison's settings, else R's defaults: the station
    name as title, the y label from the file name, detrended."""
    if job is not None:
        p = job.params or {}
        return {
            "title": p.get("title", analysis.station_name),
            "y_label": "",
            "detrend": bool(p.get("detrend", True)),
        }
    return {"title": analysis.station_name, "y_label": "", "detrend": True}


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def sector(request, analysis_id):
    """Step 5: the sector file and plot settings, the job's progress, then its results."""
    analysis = get_analysis(request, analysis_id)
    indices_job, source = current_source(analysis)
    context = {
        "analysis": analysis,
        "steps": station_steps("sector", analysis.step_urls()),
        "indices_job": indices_job,
        "source": source,
        "sample_name": SAMPLE_NAME,
        "r_no_common_data": R_NO_COMMON_DATA,
    }
    if source is None:  # R: "Please calculate climate indices."
        return render(request, "stations/sector.html", context)
    job = sector_job(analysis, source)
    if request.method == "POST":
        form = SectorForm(
            request.POST,
            request.FILES,
            summary=analysis.summary,
            sample=bool(request.POST.get("sample")),
        )
        if form.is_valid():
            queue_sector(request, analysis, source, form)
            return redirect("stations:sector", analysis_id=analysis.pk)
    else:
        form = SectorForm(initial=initial(analysis, job), summary=analysis.summary)
        if not analysis.reached(Step.SECTOR):
            analysis.advance_to(Step.SECTOR)
            analysis.save(update_fields=["step"])
    context.update(
        {
            "form": form,
            "job": job,
            "from_batch": source.from_batch and analysis.indices_job is None,
        }
    )
    if job is not None and not job.is_finished:
        context.update(progress_context(request, job))
        context["phases"] = phases(job)
    elif job is not None and job.status == Status.FAILED:
        context["phases"] = phases(job)
        context["r_error"] = R_NO_COMMON_DATA in (job.error or "")
    elif job is not None and job.status == Status.SUCCEEDED:
        results = sector_plots.load(job)
        if results is not None:
            order = "strength" if request.GET.get("order") == "strength" else "r"
            bars = results.ordered(order)
            context.update(
                {
                    "results": results,
                    "order": order,
                    "bars": bars,
                    "bars_svg": sector_plots.bar_svg(bars, results.title),
                    "categories": [
                        {"key": key, "label": sector_plots.category_label(key), "token": token}
                        for key, token in sector_plots.TOKENS.items()
                        if any(b.category == key for b in results.bars)
                    ],
                }
            )
        else:
            context["missing_outputs"] = True
    return render(request, "stations/sector.html", context)


@never_cache
@require_safe
def sector_progress(request, analysis_id):
    """htmx: the sector job's progress; once it has finished, the page reloads."""
    analysis = get_analysis(request, analysis_id)
    _indices_job, source = current_source(analysis)
    job = sector_job(analysis, source)
    if job is None:
        raise Http404
    if job.status == Status.RUNNING:
        from climpact_web.jobs.worker import reap_stale

        if reap_stale():
            job.refresh_from_db()
    if job.is_finished:
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse("stations:sector", args=[analysis.pk])
        return response
    context = {**progress_context(request, job), "analysis": analysis, "phases": phases(job)}
    return render(request, "stations/_sector_progress.html", context)


@require_safe
def sector_sample(request):
    """Climpact for R's sample sector file, yearly wheat yields for New South Wales."""
    return FileResponse(
        SAMPLE_FILE.open("rb"), as_attachment=True, filename=SAMPLE_NAME, content_type="text/csv"
    )

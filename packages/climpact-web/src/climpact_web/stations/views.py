"""The single-station steps. Step 1 (#76): load the station file, or the sample, and give
the station's metadata. Step 2 (#77): the quality checks, run as a ``qc`` job, and their
results (:mod:`.qc_review`, :mod:`.qc_plots`). Results (#78, #79, #90) add their pages to
the same analysis (``/station/<id>/...``, :mod:`.views_indices`).

Confirming the details also queues the indices with the default settings (#178,
:mod:`.calculation`), so they are calculated while the user looks at the quality checks;
any later change to the file, the details or the thresholds replaces that run.

An analysis is visible only to the browser session that created it, like a job: any
other session gets 404.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.files import File
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from climpact_web.core.limits import disk_required, human_required
from climpact_web.core.navigation import station_steps
from climpact_web.jobs.forms import safe_station_name
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.views import OWNER_KEY, create_job, owner_token
from climpact_web.stations import calculation, preview
from climpact_web.stations.forms import (
    QC_DEFAULTS,
    MetadataForm,
    QCParamsForm,
    UploadForm,
)
from climpact_web.stations.models import STATION_FILE, Source, StationAnalysis, Step
from climpact_web.stations.station_file import (
    Inspection,
    inspect_station_bytes,
    variable_label,
)

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"
SAMPLE_NAME = "sydney_observatory_hill_1936-2015.txt"
# Sydney Observatory Hill (ASN00066062), as in reference/stations.csv.
SAMPLE_METADATA = {
    "station_name": "sydney_observatory_hill_1936-2015",
    "latitude": -33.86,
    "longitude": 151.21,
}
RECENT_ANALYSES = 5


def sample_bytes() -> bytes:
    return gzip.decompress((SAMPLE_DIR / f"{SAMPLE_NAME}.gz").read_bytes())


def get_analysis(request, analysis_id) -> StationAnalysis:
    owner = request.session.get(OWNER_KEY) or "-"
    return get_object_or_404(StationAnalysis, pk=analysis_id, owner=owner)


def default_name(file_name: str) -> str:
    """The station name from the file name without its extension, as the command line
    and the R app do, keeping only the characters allowed in result file names."""
    return safe_station_name(Path(file_name).stem)


# ---- Step 1: the file --------------------------------------------------------------------


def apply_inspection(analysis: StationAnalysis, inspection: Inspection, file_name: str):
    analysis.file_name = file_name[:255]
    analysis.summary = inspection.summary
    analysis.warnings = inspection.warnings
    analysis.reset_later_steps()
    analysis.touch()
    analysis.save()
    analysis.save_station_text(inspection.text)


def read_upload(uploaded) -> bytes:
    return b"".join(uploaded.chunks())


@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def upload(request):
    """Start: upload a station file (or choose the sample)."""
    inspection = None
    if request.method == "POST":
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data["station_file"]
            inspection = inspect_station_bytes(read_upload(uploaded))
            if inspection.ok:
                with transaction.atomic():
                    analysis = StationAnalysis(
                        owner=owner_token(request),
                        source=Source.UPLOAD,
                        station_name=default_name(uploaded.name),
                    )
                    apply_inspection(analysis, inspection, uploaded.name)
                return redirect("stations:load", analysis_id=analysis.pk)
    else:
        form = UploadForm()
    return render(request, "stations/upload.html", upload_context(request, form, inspection))


def upload_context(request, form, inspection=None) -> dict:
    owner = request.session.get(OWNER_KEY) or "-"
    return {
        "form": form,
        "inspection": inspection,
        "file_name": form.files.get("station_file").name if form.files.get("station_file") else "",
        "steps": station_steps("upload"),
        "recent": StationAnalysis.objects.filter(owner=owner)[:RECENT_ANALYSES],
        "sample_name": SAMPLE_NAME,
        "max_upload_mb": settings.MAX_UPLOAD_MB,
    }


@require_http_methods(["GET", "HEAD", "POST"])
@disk_required
def sample(request):
    """One click: an analysis of the Sydney sample with its metadata filled in."""
    if request.method != "POST":
        return redirect("stations:upload")
    inspection = inspect_station_bytes(sample_bytes())
    with transaction.atomic():
        analysis = StationAnalysis(owner=owner_token(request), source=Source.SAMPLE)
        apply_inspection(analysis, inspection, SAMPLE_NAME)
        for name, value in SAMPLE_METADATA.items():
            setattr(analysis, name, value)
        analysis.save()
    return redirect("stations:load", analysis_id=analysis.pk)


@require_safe
def sample_file(request):
    """The sample station file, to look at or to use as a template (R links to it)."""
    response = HttpResponse(sample_bytes(), content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{SAMPLE_NAME}"'
    return response


@require_POST
@human_required
def replace_file(request, analysis_id):
    """Load a different file into the analysis, keeping the metadata."""
    analysis = get_analysis(request, analysis_id)
    form = UploadForm(request.POST, request.FILES)
    inspection = None
    if form.is_valid():
        uploaded = form.cleaned_data["station_file"]
        inspection = inspect_station_bytes(read_upload(uploaded))
        if inspection.ok:
            old_default = default_name(analysis.file_name)
            if not analysis.station_name or analysis.station_name == old_default:
                analysis.station_name = default_name(uploaded.name)
            analysis.source = Source.UPLOAD
            apply_inspection(analysis, inspection, uploaded.name)
            messages.success(request, _("The new file is loaded."))
            return redirect("stations:load", analysis_id=analysis.pk)
    metadata = MetadataForm(initial=initial_metadata(analysis), summary=analysis.summary)
    context = load_context(request, analysis, metadata)
    context.update(replace_form=form, inspection=inspection, replace_open=True)
    return render(request, "stations/load.html", context)


# ---- Step 1: the metadata ----------------------------------------------------------------


def initial_metadata(analysis: StationAnalysis) -> dict:
    return {
        "station_name": analysis.station_name,
        "latitude": analysis.latitude,
        "longitude": analysis.longitude,
        "base_start": analysis.base_start,
        "base_end": analysis.base_end,
    }


def percent_text(variable: dict) -> str:
    if variable["missing"] and variable["percent_missing"] < 0.1:
        return _("under 0.1%")
    return _("%(value)s%%") % {"value": f"{variable['percent_missing']:.1f}"}


def summary_context(analysis: StationAnalysis) -> dict:
    summary = analysis.summary or {}
    if not summary:
        return {}
    variables = [
        {
            **v,
            "label": variable_label(v["key"]),
            "percent_text": percent_text(v),
            "token": f"--chart-{v['key']}",
        }
        for v in summary["variables"]
    ]
    years = [
        {
            **y,
            "cells": [
                {"value": y[k], "percent": round(100 * y[k] / y["days"])}
                for k in ("prcp", "tmax", "tmin")
            ],
        }
        for y in summary["years"]
    ]
    return {
        "summary": summary,
        "variables": variables,
        "years": years,
        "year_count": summary["last_year"] - summary["first_year"] + 1,
        "panels": preview.panels(summary.get("preview", {})),
    }


def load_context(request, analysis: StationAnalysis, form: MetadataForm) -> dict:
    return {
        "analysis": analysis,
        "form": form,
        "replace_form": UploadForm(),
        "steps": station_steps("upload", analysis.step_urls()),
        **summary_context(analysis),
    }


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def load(request, analysis_id):
    """Step 1's main page: what is in the file, and the station metadata."""
    analysis = get_analysis(request, analysis_id)
    if request.method == "POST":
        form = MetadataForm(request.POST, summary=analysis.summary)
        if form.is_valid():
            data = form.cleaned_data
            changed = any(getattr(analysis, k) != v for k, v in data.items())
            for name, value in data.items():
                setattr(analysis, name, value)
            if changed:
                analysis.reset_later_steps()
            analysis.advance_to(Step.QC)
            analysis.touch()
            analysis.save()
            if analysis.qc_job is None:
                # Run the checks at once with the thresholds kept (R's defaults at first).
                queue_qc(request, analysis)
            if analysis.indices_job is None:
                # And the indices with the default settings, behind the checks (#178).
                calculation.speculate(request, analysis)
                analysis.save()
            return redirect("stations:qc", analysis_id=analysis.pk)
    else:
        if analysis.metadata_complete:
            # Bound, to show the warnings (and any errors) of the saved metadata.
            form = MetadataForm(initial_metadata(analysis), summary=analysis.summary)
            form.is_valid()
        else:
            form = MetadataForm(initial=initial_metadata(analysis), summary=analysis.summary)
    return render(request, "stations/load.html", load_context(request, analysis, form))


@require_POST
def validate(request, analysis_id):
    """htmx: one group of fields checked as it changes, returned on its own."""
    analysis = get_analysis(request, analysis_id)
    unit = request.POST.get("group", "")
    if unit not in MetadataForm.UNITS:
        return HttpResponseBadRequest()
    form = MetadataForm(request.POST, summary=analysis.summary)
    form.is_valid()
    context = {"form": form, "group": unit, "analysis": analysis}
    return render(request, "stations/_unit.html", context)


@require_safe
def series(request, analysis_id):
    """The daily series as CSV (date, prcp, tmax, tmin; empty when missing): the CSV
    download of the preview, and the data for the interactive chart (#75)."""
    analysis = get_analysis(request, analysis_id)
    from climpact.io.station import merged_rows, read_station_file

    if not analysis.station_file.is_file():
        raise Http404
    rows = merged_rows(read_station_file(analysis.station_file))
    rows = rows.drop_duplicates(subset="date", keep="last")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    name = analysis.station_name or "station"
    response["Content-Disposition"] = f'attachment; filename="{name}_daily.csv"'
    writer = csv.writer(response)
    writer.writerow(["date", "prcp", "tmax", "tmin"])
    for date, *values in rows[["date", "prcp", "tmax", "tmin"]].itertuples(index=False):
        writer.writerow([date.date().isoformat(), *("" if v != v else f"{v:g}" for v in values)])
    return response


@require_POST
def delete(request, analysis_id):
    """Delete the analysis and its file now, rather than at the end of the retention."""
    analysis = get_analysis(request, analysis_id)
    analysis.delete_files()
    analysis.delete()
    messages.success(request, _("The station data were deleted."))
    return redirect("stations:upload")


# ---- Step 2: quality control (#77) ----------------------------------------------------


def qc_job_params(analysis: StationAnalysis) -> dict:
    return {
        "station_file": STATION_FILE,
        "metadata": analysis.metadata,
        "qc": QCParamsForm.initial_for(analysis.qc_params),
    }


def queue_qc(request, analysis: StationAnalysis) -> Job:
    """Queue the quality checks of the analysis's file with its thresholds, replacing a
    check still waiting or running."""
    old = analysis.qc_job
    if old is not None and old.can_cancel:
        old.request_cancel()
    with analysis.station_file.open("rb") as handle:
        job = create_job(
            request,
            "qc",
            qc_job_params(analysis),
            {STATION_FILE: File(handle)},
            title=_("%(name)s: quality checks") % {"name": analysis.station_name},
        )
    analysis.qc_job = job
    analysis.touch()
    analysis.save()
    return job


def step_two_ready(analysis: StationAnalysis) -> bool:
    return (
        analysis.reached(Step.QC) and analysis.metadata_complete and analysis.station_file.is_file()
    )


def table_pages(request, review) -> dict[str, object]:
    """The page of each table on the screen, by its ``table_id``: ``?<table_id>_page=``
    (the pager without htmx)."""
    pages = {}
    for table in review.tables:
        try:
            number = int(request.GET.get(f"{table.table_id}_page", 1))
        except ValueError:
            number = 1
        pages[table.table_id] = table.page(number)
    return pages


def qc_context(request, analysis: StationAnalysis, **extra) -> dict:
    from climpact_web.jobs.views import progress_context

    job = analysis.qc_job
    context = {
        "analysis": analysis,
        "steps": station_steps("qc", analysis.step_urls()),
        "qc_form": extra.pop("qc_form", None)
        or QCParamsForm(initial=QCParamsForm.initial_for(analysis.qc_params)),
        "replace_form": extra.pop("replace_form", None) or UploadForm(),
        "job": job,
    }
    if job is not None:
        context.update(progress_context(request, job))
    if job is not None and job.status == Status.SUCCEEDED:
        from climpact_web.stations import qc_plots, qc_review

        try:
            review = qc_review.review(job, analysis.station_file)
        except FileNotFoundError:
            review = None
        if review is not None:
            pages = table_pages(request, review)
            context.update(
                review=review,
                findings=[{"list": f, "page": pages[f.check.table_id]} for f in review.findings],
                groups=[{"group": g, "page": pages[g.check.table_id]} for g in review.groups],
                month_names=[date_format(dt.date(2001, m, 1), "M") for m in range(1, 13)],
                charts=[
                    {
                        "variable": v,
                        "id": qc_review.chart_id(v),
                        "label": qc_review.variable_labels()[v],
                    }
                    for v in qc_review.CHART_VARIABLES
                ],
                monthly=qc_plots.monthly_boxes(review.rows, review.params),
                annual=qc_plots.annual_boxes(review.rows),
                decimals=qc_plots.decimals(review.rows),
                histogram=qc_plots.precipitation_histogram(review.rows),
            )
    context.update(extra)
    return context


@never_cache
@require_safe
def qc(request, analysis_id):
    """Step 2, Check quality: the thresholds, the checks run as a job, and their results."""
    analysis = get_analysis(request, analysis_id)
    if not step_two_ready(analysis):
        return redirect("stations:load", analysis_id=analysis.pk)
    return render(request, "stations/qc.html", qc_context(request, analysis))


@require_POST
@human_required
def qc_run(request, analysis_id):
    """Save the thresholds and run the checks (again)."""
    analysis = get_analysis(request, analysis_id)
    if not step_two_ready(analysis):
        return redirect("stations:load", analysis_id=analysis.pk)
    form = QCParamsForm(request.POST)
    if not form.is_valid():
        return render(request, "stations/qc.html", qc_context(request, analysis, qc_form=form))
    values = {k: form.cleaned_data[k] for k in QC_DEFAULTS}
    changed = values != QCParamsForm.initial_for(analysis.qc_params)
    if changed:
        # The QC files of the full run must use the new thresholds too.
        analysis.qc_params = values
        if analysis.reached(Step.INDICES):
            analysis.step = Step.QC
    queue_qc(request, analysis)
    if changed:
        # The run of the old thresholds is replaced, with the same settings (#178).
        previous = calculation.previous_params(analysis)
        analysis.cancel_speculative()
        analysis.indices_job = analysis.sector_job = None
        calculation.speculate(request, analysis, previous)
        analysis.save()
    return redirect(reverse("stations:qc", args=[analysis.pk]) + "#qc-status")


@never_cache
@require_safe
def qc_progress(request, analysis_id):
    """The checks' progress, polled by htmx; once they have finished the page reloads to
    show the results."""
    analysis = get_analysis(request, analysis_id)
    job = analysis.qc_job
    if job is None:
        raise Http404
    if job.status == Status.RUNNING:
        from climpact_web.jobs.worker import reap_stale

        if reap_stale():
            job.refresh_from_db()
    if job.is_finished:
        if request.headers.get("HX-Request"):
            response = HttpResponse(status=204)
            response["HX-Refresh"] = "true"
            return response
        return redirect("stations:qc", analysis_id=analysis.pk)
    return render(request, "stations/_qc_progress.html", qc_context(request, analysis))


@never_cache
@require_safe
def qc_table(request, analysis_id, check):
    """One page of a table (htmx): a check's, or with ``?group=`` one of its groups;
    ``?page=``, or ``?date=`` for the page holding that date (a flag picked on a chart)."""
    from climpact_web.stations import qc_review

    analysis = get_analysis(request, analysis_id)
    job = analysis.qc_job
    if check not in qc_review.CHECK_KEYS or job is None or job.status != Status.SUCCEEDED:
        raise Http404
    review = qc_review.review(job, analysis.station_file)
    item = review.table(check, request.GET.get("group", ""))
    if item is None:
        raise Http404
    date = request.GET.get("date", "")
    if date:
        number = item.page_of(date)
    else:
        try:
            number = int(request.GET.get("page", 1))
        except ValueError:
            number = 1
    context = {"analysis": analysis, "check": item, "page": item.page(number), "selected": date}
    return render(request, "stations/_qc_table.html", context)


@require_POST
@human_required
def qc_replace(request, analysis_id):
    """Fix the file and upload it again: the station details and thresholds are kept and
    the checks run again on the new file."""
    analysis = get_analysis(request, analysis_id)
    if not analysis.metadata_complete:
        return redirect("stations:load", analysis_id=analysis.pk)
    form = UploadForm(request.POST, request.FILES)
    inspection = None
    if form.is_valid():
        uploaded = form.cleaned_data["station_file"]
        inspection = inspect_station_bytes(read_upload(uploaded))
        if inspection.ok:
            metadata = MetadataForm(initial_metadata(analysis), summary=inspection.summary)
            analysis.source = Source.UPLOAD
            apply_inspection(analysis, inspection, uploaded.name)
            if not metadata.is_valid():
                # The base period no longer fits the data: back to step 1 to change it.
                messages.warning(
                    request,
                    _(
                        "The new file is loaded, but the station details need a change "
                        "before the checks can run."
                    ),
                )
                return redirect("stations:load", analysis_id=analysis.pk)
            analysis.advance_to(Step.QC)
            queue_qc(request, analysis)
            calculation.speculate(request, analysis)  # the old file's run was cancelled
            analysis.save()
            messages.success(request, _("The new file is loaded. The checks are running again."))
            return redirect(reverse("stations:qc", args=[analysis.pk]) + "#qc-status")
    context = qc_context(request, analysis, replace_form=form, inspection=inspection)
    return render(request, "stations/qc.html", context)


@require_POST
def qc_continue(request, analysis_id):
    """ "Use this data", whatever the checks found (the user decides): straight to the
    results, calculated with the default settings while the user looked at the checks
    (#178), or their progress. Without a speculative run, one is queued now."""
    analysis = get_analysis(request, analysis_id)
    job = analysis.qc_job
    if job is None or job.status != Status.SUCCEEDED or not step_two_ready(analysis):
        return redirect("stations:qc", analysis_id=analysis.pk)
    calculation.commit(request, analysis)
    analysis.advance_to(Step.RESULTS)
    analysis.touch()
    analysis.save()
    return redirect("stations:results", analysis_id=analysis.pk)

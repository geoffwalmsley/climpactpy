"""The single-station workspace (#179, #198): upload the station file, or the sample, and
confirm the station's details on the first visit (``load``, until #201's setup page);
Quality (#77), the quality checks, run as a ``qc`` job, their results (:mod:`.qc_review`,
:mod:`.qc_plots`) and what is in the file ("Your data", Data's summary before #198).
Results and Files (#78, #79, #90, #176) add their pages to the same analysis
(``/station/<id>/...``, :mod:`.views_indices`, :mod:`.views_downloads`). Each section's
page shows the section tabs and the Inputs panel (:mod:`.workspace`), whose Edit opens a
side sheet, or without JavaScript a page, with that input's form (:func:`edit_input`).

Confirming the details also queues the indices with the default settings (#178,
:mod:`.calculation`), so they are calculated while the user looks at the quality checks.
A later change to the file, the details or the thresholds keeps the results, shown as
out of date, and queues their replacement (``calculation.bring_up_to_date``).

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
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from climpact_web.core.limits import disk_required, human_required
from climpact_web.jobs.forms import safe_station_name
from climpact_web.jobs.models import Status
from climpact_web.jobs.views import OWNER_KEY, owner_token
from climpact_web.stations import calculation, preview, workspace
from climpact_web.stations.calculation import queue_qc
from climpact_web.stations.forms import (
    QC_DEFAULTS,
    BasePeriodForm,
    MetadataForm,
    QCParamsForm,
    StationForm,
    UploadForm,
)
from climpact_web.stations.forms_indices import IndexParamsForm
from climpact_web.stations.models import Source, StationAnalysis, Step
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
    """Keep a new file in the analysis. Its checks and results are kept too, out of date
    (#179); what was still queued for the old file is cancelled."""
    analysis.file_name = file_name[:255]
    analysis.summary = inspection.summary
    analysis.warnings = inspection.warnings
    analysis.save_station_text(inspection.text)
    workspace.settle(analysis)
    analysis.touch()
    analysis.save()


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
            if workspace.set_up(analysis):
                # Already in use: the checks and the run of the new file (#179, #198).
                calculation.bring_up_to_date(request, analysis)
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
        "details_saved": workspace.committed(analysis),
        **workspace.context(analysis, "setup"),
        **summary_context(analysis),
    }


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def load(request, analysis_id):
    """The first visit's details (Data before #198): what is in the file, and the station
    metadata. Confirming the details runs the checks with the thresholds kept (R's
    defaults at first) and the indices with the default settings behind them (#178).
    Once the details are confirmed and fit the data the station is set up, and this
    address, Data's, leads to Quality's "Your data" (#198); a later change is made in the
    Inputs panel (:func:`edit_input`), and only what depends on it runs again, the results
    of the old details staying, out of date, until then (#179)."""
    analysis = get_analysis(request, analysis_id)
    if request.method != "POST" and workspace.set_up(analysis):
        return redirect(reverse("stations:qc", args=[analysis.pk]) + "#your-data")
    if request.method == "POST":
        form = MetadataForm(request.POST, summary=analysis.summary)
        if form.is_valid():
            for name, value in form.cleaned_data.items():
                setattr(analysis, name, value)
            analysis.advance_to(Step.QC)
            queued_qc, _run = calculation.bring_up_to_date(request, analysis)
            if workspace.committed(analysis) and not queued_qc:
                # The checks are unchanged: the results are what the change affects.
                return redirect("stations:results", analysis_id=analysis.pk)
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

    job, shown = analysis.qc_job, workspace.shown_qc(analysis)
    changes = workspace.qc_changes(analysis, shown)
    context = {
        "analysis": analysis,
        **workspace.context(analysis, "quality", request.path),
        **summary_context(analysis),  # "Your data", Data's summary before #198
        "thresholds_changed": workspace.thresholds_changed(analysis),
        "job": job,
        "shown": shown,
        # The checks shown are not of the current inputs, or newer ones are on the way
        # (#179): the banner says so, and the decision waits for the new checks.
        "stale": {
            "changes": workspace.change_sentences(analysis, shown, changes),
            "replacing": shown is not None and job != shown,
        }
        if shown is not None and (changes or job != shown)
        else None,
    }
    if job is not None:
        context.update(progress_context(request, job))
    if shown is not None:
        from climpact_web.stations import qc_plots, qc_review

        try:
            review = qc_review.review(shown, analysis.station_file)
        except FileNotFoundError:
            review = None
        if review is not None:
            remember_verdict(shown, review.verdict.level)
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


def remember_verdict(job, level: str) -> None:
    """Keep the verdict's level with the checks, for the Quality tab's state (#179)."""
    if (job.result or {}).get("verdict") != level:
        job.result = {**(job.result or {}), "verdict": level}
        type(job).objects.filter(pk=job.pk).update(result=job.result)


@never_cache
@require_safe
def qc(request, analysis_id):
    """Quality: the checks run as a job and their results. The thresholds are in the
    Inputs panel (#199)."""
    analysis = get_analysis(request, analysis_id)
    if not step_two_ready(analysis):
        return redirect("stations:load", analysis_id=analysis.pk)
    return render(request, "stations/qc.html", qc_context(request, analysis))


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
    job = workspace.shown_qc(analysis)
    if check not in qc_review.CHECK_KEYS or job is None:
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
def qc_continue(request, analysis_id):
    """ "Use this data", whatever the checks found (the user decides): straight to the
    results, calculated with the default settings while the user looked at the checks
    (#178), or their progress. Without a speculative run, one is queued now."""
    analysis = get_analysis(request, analysis_id)
    job = analysis.qc_job
    if (
        job is None
        or job.status != Status.SUCCEEDED
        or not step_two_ready(analysis)
        or workspace.qc_changes(analysis, job)  # out of date: the new checks come first
    ):
        return redirect("stations:qc", analysis_id=analysis.pk)
    calculation.commit(request, analysis)
    analysis.advance_to(Step.RESULTS)
    analysis.touch()
    analysis.save()
    return redirect("stations:results", analysis_id=analysis.pk)


@require_safe
def workspace_home(request, analysis_id):
    """``/station/<id>/``: the furthest section the workspace has reached (#179)."""
    return redirect(workspace.home_url(get_analysis(request, analysis_id)))


# ---- the Inputs panel's sheets (#198) ----------------------------------------------------

# Each sheet's title and the line under it (stations/_input_form.html).
INPUT_SHEETS = {
    "file": (
        _lazy("Replace the file"),
        _lazy("Load a corrected or longer file of this station."),
    ),
    "station": (
        _lazy("Station"),
        _lazy(
            "The name titles the results and names their files. The latitude decides the "
            "seasons of the growing season length and heatwaves."
        ),
    ),
    "base-period": (
        _lazy("Base period"),
        _lazy("The years the percentile indices are compared with."),
    ),
    "thresholds": (
        _lazy("Quality thresholds"),
        _lazy("The limits the quality checks flag values beyond. R's defaults suit most data."),
    ),
    "settings": (
        _lazy("Index settings"),
        _lazy("The choices some indices depend on, and the files a run writes."),
    ),
}


def next_url(request, analysis: StationAnalysis) -> str:
    """Where an edit returns: the page it was opened from (``next``), one of this station's,
    else the workspace's home."""
    from django.utils.http import url_has_allowed_host_and_scheme

    target = request.POST.get("next") or request.GET.get("next") or ""
    own = f"/station/{analysis.pk}/"
    if (
        target.startswith(own)
        and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()})
        and not target.startswith(own + "inputs/")
    ):
        return target
    return workspace.home_url(analysis)


def input_form(analysis: StationAnalysis, key: str, data=None, files=None):
    """The form of the sheet ``key``: unbound with the saved values, or bound to ``data``."""
    if key == "file":
        # Its own ids, apart from the first visit's file field.
        return UploadForm(data, files, auto_id="sheet_%s")
    if key == "thresholds":
        if data is not None:
            return QCParamsForm(data)
        return QCParamsForm(initial=QCParamsForm.initial_for(analysis.qc_params))
    if key == "settings":
        if data is not None:
            return IndexParamsForm(data, station_title=calculation.station_title(analysis))
        return calculation.settings_form(analysis)
    form_class = StationForm if key == "station" else BasePeriodForm
    if data is not None:
        return form_class(data, summary=analysis.summary)
    values = {k: v for k, v in initial_metadata(analysis).items() if k in form_class.FIELDS}
    form = form_class(values, summary=analysis.summary)
    form.is_valid()  # bound, to show the saved values' warnings
    return form


def sheet_context(analysis: StationAnalysis, key: str, form=None) -> dict:
    """One sheet's context: its key, title, form and what applying it will update; for the
    index settings, where they come from (``settings_source``: a batch's line, say)."""
    context = {
        "key": key,
        "title": INPUT_SHEETS[key][0],
        "intro": INPUT_SHEETS[key][1],
        "form": form if form is not None else input_form(analysis, key),
        "impact": workspace.impact(key),
    }
    if key == "settings":
        context["settings_source"] = calculation.previous_params(analysis)[5]
    return context


def apply_thresholds(request, analysis: StationAnalysis, form: QCParamsForm) -> None:
    """Apply the Quality thresholds sheet. New thresholds replace the checks and the run
    (the run's QC files use them too), whose results stay, out of date, until then (#179).
    The same thresholds run the checks again when the shown ones failed, were stopped or
    never ran: Apply is how the user runs them again since the form left Quality (#199)."""
    values = {k: form.cleaned_data[k] for k in QC_DEFAULTS}
    if values != QCParamsForm.initial_for(analysis.qc_params):
        analysis.qc_params = values
        calculation.bring_up_to_date(request, analysis)
        return
    job = analysis.qc_job
    if job is None or job.status in (Status.FAILED, Status.CANCELLED):
        queue_qc(request, analysis)


def apply_settings(request, analysis: StationAnalysis, form) -> None:
    """Apply the Index settings sheet: queue a run with them, which replaces the results
    shown when it has finished (#178, "Adjust and recalculate" on Results until #199)."""
    workspace.restore_if_cancelled(analysis)
    calculation.queue_station_run(request, analysis, form)
    analysis.advance_to(Step.RESULTS)
    analysis.touch()
    analysis.save()


def apply_file(request, analysis: StationAnalysis, form: UploadForm):
    """Replace the file from the File sheet. Returns (inspection, response): a redirect
    when the file was loaded, else the inspection whose problems the page shows."""
    uploaded = form.cleaned_data["station_file"]
    inspection = inspect_station_bytes(read_upload(uploaded))
    if not inspection.ok:
        return inspection, None
    analysis.source = Source.UPLOAD  # the station details are kept, its name too
    apply_inspection(analysis, inspection, uploaded.name)
    if not workspace.details_valid(analysis):
        # The base period no longer fits the data: the details page asks for a new one.
        messages.warning(
            request,
            _(
                "The new file is loaded, but the station details need a change before the "
                "checks can run."
            ),
        )
        return inspection, redirect("stations:load", analysis_id=analysis.pk)
    calculation.bring_up_to_date(request, analysis)
    messages.success(request, _("The new file is loaded. The checks and results are updated."))
    return inspection, redirect(next_url(request, analysis))


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def edit_input(request, analysis_id, key):
    """An input of the Inputs panel (#198, #199): the file, the station, the base period,
    the quality thresholds or the index settings. The panel's Edit opens this form in a
    side sheet; without JavaScript, or when the sheet's form has errors, it is this page.
    Applying keeps what depends on the input, marked out of date, and queues its
    replacement (#179); then back to the page it was opened from. The index settings only
    once the data is in use ("Use this data"): before, only the results use them."""
    analysis = get_analysis(request, analysis_id)
    if key not in INPUT_SHEETS:
        raise Http404
    if not workspace.set_up(analysis):
        return redirect("stations:load", analysis_id=analysis.pk)
    if key not in workspace.sheet_keys(analysis):
        return redirect("stations:qc", analysis_id=analysis.pk)
    inspection = None
    if request.method == "POST":
        form = input_form(analysis, key, request.POST, request.FILES)
        if form.is_valid():
            if key == "file":
                inspection, response = apply_file(request, analysis, form)
                if response is not None:
                    return response
            elif key == "thresholds":
                apply_thresholds(request, analysis, form)
                return redirect(next_url(request, analysis))
            elif key == "settings":
                apply_settings(request, analysis, form)
                return redirect(next_url(request, analysis))
            else:
                for name, value in form.cleaned_data.items():
                    setattr(analysis, name, value)
                calculation.bring_up_to_date(request, analysis)
                return redirect(next_url(request, analysis))
    else:
        form = None
    context = {
        "analysis": analysis,
        **workspace.context(analysis, "setup"),
        "sheet": sheet_context(analysis, key, form),
        "next": next_url(request, analysis),
        "inspection": inspection,
        "file_name": request.FILES["station_file"].name if "station_file" in request.FILES else "",
    }
    return render(request, "stations/input_edit.html", context)


@never_cache
@require_safe
def inputs_progress(request, analysis_id):
    """The Inputs panel's runs (#198), polled by htmx while the checks or a run of new
    inputs are under way; once they have all finished the page reloads to show them."""
    analysis = get_analysis(request, analysis_id)
    if not workspace.set_up(analysis):
        raise Http404
    panel = workspace.inputs_panel(analysis)
    if not panel["input_runs"]:
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"
        return response
    return render(request, "stations/_input_runs.html", {"analysis": analysis, **panel})

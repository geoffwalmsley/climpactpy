"""The single-station workspace (#179, #198): a New station page (#201) takes the station
file, or the sample, and the station's details, then checks and calculates at once;
Quality (#77), the quality checks, run as a ``qc`` job, their results (:mod:`.qc_review`,
:mod:`.qc_plots`) and what is in the file ("Your data", Data's summary before #198).
Results and Files (#78, #79, #90, #176) add their pages to the same analysis
(``/station/<id>/...``, :mod:`.views_indices`, :mod:`.views_downloads`). Each section's
page shows the section tabs and the Inputs panel (:mod:`.workspace`), whose Edit opens a
side sheet, or without JavaScript a page, with that input's form (:func:`edit_input`).

Confirming the details also queues the indices with the default settings (#178,
:mod:`.calculation`), so they are calculated while the user looks at the quality checks.
A later change to the file or the details keeps the results, shown as out of date, and
queues their replacement (``calculation.bring_up_to_date``). The base period, thresholds and
index settings are the workspace's (#254): their sheets change them for every station of
the workspace (``calculation.change_settings``), and "Undo the change" (:func:`undo`) puts
them back while the recalculation is on the way.

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
from django.utils.translation import ngettext
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
from climpact_web.stations.models import Source, Station, Step
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
# A year with more days missing than this, in any variable, has no annual index values
# (climdex.pcic's max.missing.days; climpact.missing.MAX_MISSING_DAYS["annual"], checked by
# a test: the web server does not import the core). The New station page's strip marks it.
MAX_MISSING_YEAR_DAYS = 15


def sample_bytes() -> bytes:
    return gzip.decompress((SAMPLE_DIR / f"{SAMPLE_NAME}.gz").read_bytes())


def get_analysis(request, analysis_id) -> Station:
    owner = request.session.get(OWNER_KEY) or "-"
    return get_object_or_404(Station, pk=analysis_id, owner=owner)


def default_name(file_name: str) -> str:
    """The station name from the file name without its extension, as the command line
    and the R app do, keeping only the characters allowed in result file names."""
    return safe_station_name(Path(file_name).stem)


# ---- Step 1: the file --------------------------------------------------------------------


def apply_inspection(analysis: Station, inspection: Inspection, file_name: str):
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


# ---- the New station page (#201) ----------------------------------------------------------

# The details a read file keeps when they were typed before it (MetadataForm's fields).
DETAIL_FIELDS = ("station_name", "latitude", "longitude", "base_start", "base_end")


def recent_analyses(request):
    owner = request.session.get(OWNER_KEY) or "-"
    return Station.objects.filter(owner=owner)[:RECENT_ANALYSES]


def year_strip(summary: dict) -> dict:
    """The New station page's days-with-data strip: one bar a year, as tall as its
    emptiest variable's share of the year's days, amber when that variable misses more
    than :data:`MAX_MISSING_YEAR_DAYS` days; and its text alternative, which names those
    years."""
    bars, gaps = [], []
    for year in summary.get("years", []):
        present = min(year[k] for k in ("prcp", "tmax", "tmin"))
        percent = round(100 * present / year["days"]) if year["days"] else 0
        gap = year["days"] - present > MAX_MISSING_YEAR_DAYS
        if gap:
            gaps.append(year["year"])
        height = max(percent, 4)  # a year with almost nothing still shows
        bars.append({"year": year["year"], "percent": height, "y": 100 - height, "gap": gap})
    for x, bar in enumerate(bars):
        bar["x"] = 10 * x
    shown = ", ".join(str(y) for y in gaps[:10])
    if len(gaps) > 10:
        shown = _("%(years)s and %(count)d more") % {"years": shown, "count": len(gaps) - 10}
    if gaps:
        label = ngettext(
            "Days with data in each year: %(count)d of %(total)d years misses more than "
            "15 days (%(years)s).",
            "Days with data in each year: %(count)d of %(total)d years miss more than "
            "15 days (%(years)s).",
            len(gaps),
        ) % {"total": len(bars), "count": len(gaps), "years": shown}
    else:
        label = _("Days with data in each year: no year misses more than 15 days.")
    # Ten units a year, the bar eight of them: a gap of a fifth between bars.
    return {
        "bars": bars,
        "label": label,
        "gaps": len(gaps),
        "width": 10 * len(bars) - 2,
        "bar_width": 8,
    }


def setup_context(request, analysis, form, **extra) -> dict:
    """The New station page: ``analysis`` is None until a file is read. Before, the name
    may be left empty: it is then the file's (:func:`default_name`)."""
    if analysis is None:
        name = form.fields["station_name"]
        name.required = False
        name.help_text = _("Leave it empty to use the file name.")
    summary = analysis.summary if analysis is not None else {}
    context = {
        "analysis": analysis,
        "form": form,
        "upload_form": UploadForm(),
        "inspection": None,
        "file_name": "",
        "recent": [] if analysis is not None or "recent" in extra else recent_analyses(request),
        "sample_name": SAMPLE_NAME,
        "max_upload_mb": settings.MAX_UPLOAD_MB,
        "strip": year_strip(summary) if summary else None,
        # Back on this page after the file of a station in use stopped fitting its details.
        "returning": analysis is not None and analysis.reached(Step.QC),
        "focus_file": False,
    }
    context.update(extra)
    return context


def keep_typed_details(analysis: Station, form: MetadataForm) -> None:
    """Keep the details typed beside a file that was only read ("Read the file", Replace),
    those that are valid on their own, so the page they come back to still has them."""
    form.is_valid()
    data = form.cleaned_data
    for name in ("station_name", "latitude", "longitude"):
        if data.get(name) not in (None, "") and not form[name].errors:
            setattr(analysis, name, data[name])
    if not (form["base_start"].errors or form["base_end"].errors) and None not in (
        data.get("base_start"),
        data.get("base_end"),
    ):
        set_base_period(analysis, data["base_start"], data["base_end"])


def set_base_period(analysis: Station, start: int, end: int) -> None:
    """Set the base period of the station's workspace from its first visit's details (the
    New station page), where the workspace is still the station's own."""
    space = analysis.workspace
    if (space.base_start, space.base_end) != (start, end):
        space.base_start, space.base_end = start, end
        space.touch()
        space.save()


def read_file(request, analysis: Station | None):
    """Read the file sent with the New station form, into ``analysis`` or a new one.
    Returns (analysis, upload form, inspection); the analysis is None when nothing was
    read and the page has none yet."""
    upload_form = UploadForm(request.POST, request.FILES)
    if not upload_form.is_valid():
        return analysis, upload_form, None
    uploaded = upload_form.cleaned_data["station_file"]
    inspection = inspect_station_bytes(read_upload(uploaded))
    if not inspection.ok:
        return analysis, upload_form, inspection
    with transaction.atomic():
        if analysis is None:
            analysis = Station(
                owner=owner_token(request),
                source=Source.UPLOAD,
                station_name=default_name(uploaded.name),
            )
        else:
            # Replace: a name that is still the old file's follows the new file.
            old_default = default_name(analysis.file_name)
            if not analysis.station_name or analysis.station_name == old_default:
                analysis.station_name = default_name(uploaded.name)
            analysis.source = Source.UPLOAD
        apply_inspection(analysis, inspection, uploaded.name)
    return analysis, upload_form, inspection


def check_and_calculate(request, analysis: Station, form: MetadataForm):
    """Save valid details and start the checks and the speculative run together (#178);
    then to Quality, or to Results when only they are affected (a station already in use
    whose new file needed new details)."""
    data = dict(form.cleaned_data)
    set_base_period(analysis, data.pop("base_start"), data.pop("base_end"))
    for name, value in data.items():
        setattr(analysis, name, value)
    analysis.advance_to(Step.QC)
    queued_qc, _run = calculation.bring_up_to_date(request, analysis)
    if workspace.committed(analysis) and not queued_qc:
        return redirect("stations:results", analysis_id=analysis.pk)
    return redirect("stations:qc", analysis_id=analysis.pk)


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def new_station(request, analysis_id=None):
    """New station (#201): the file, then the station details, on one page, and one
    button, "Check and calculate", that runs the checks and the indices with the default
    thresholds and settings and opens Quality.

    ``/station/new`` has no analysis yet; reading a file makes one, and the page is then
    ``/station/<id>/setup``, the file read and shown, with the same form. With JavaScript
    a chosen or dropped file is sent at once (``intent=read``, a redirect back here) and
    the details typed beside it are kept; without, the file and the details can go
    together, or the file first with "Read the file". The details are checked against
    the file. A station already set up has no setup page: its address leads to Quality's
    "Your data", and later changes are made in the Inputs panel (#198)."""
    analysis = get_analysis(request, analysis_id) if analysis_id else None
    if analysis is not None and request.method != "POST" and workspace.set_up(analysis):
        return redirect(reverse("stations:qc", args=[analysis.pk]) + "#your-data")
    if request.method != "POST":
        if analysis is None:
            form = MetadataForm(initial={"base_start": 1971, "base_end": 2000})
        elif analysis.metadata_complete and analysis.reached(Step.QC):
            # Back after a new file: bound, to show why the details no longer fit.
            form = MetadataForm(initial_metadata(analysis), summary=analysis.summary)
            form.is_valid()
        else:
            form = MetadataForm(initial=initial_metadata(analysis), summary=analysis.summary)
        focus = analysis is not None and request.session.pop("setup_read", None) == str(analysis.pk)
        context = setup_context(request, analysis, form, focus_file=focus)
        return render(request, "stations/new.html", context)

    intent = request.POST.get("intent", "go")
    inspection, upload_form = None, None
    if "station_file" in request.FILES or analysis is None:
        analysis, upload_form, inspection = read_file(request, analysis)
        read = inspection is not None and inspection.ok
        if not read:
            # The file's problems, in its step; the details stay as typed.
            data = request.POST
            form = MetadataForm(
                initial={k: data.get(k) for k in DETAIL_FIELDS if data.get(k)}
                or (initial_metadata(analysis) if analysis else None),
                summary=analysis.summary if analysis else None,
            )
            context = setup_context(
                request,
                analysis,
                form,
                upload_form=upload_form,
                inspection=inspection,
                file_name=request.FILES["station_file"].name
                if "station_file" in request.FILES
                else "",
            )
            return render(request, "stations/new.html", context)
        if intent == "read":
            keep_typed_details(analysis, MetadataForm(request.POST, summary=analysis.summary))
            analysis.save()
            if workspace.set_up(analysis):
                # In use already (a new file from the setup page of a station whose old one
                # needed new details): the checks and the run of the new file (#179).
                calculation.bring_up_to_date(request, analysis)
            request.session["setup_read"] = str(analysis.pk)
            return redirect("stations:setup", analysis_id=analysis.pk)

    if intent == "read" and inspection is None:
        # "Read the file" with no file chosen (without JavaScript): nothing to read.
        keep_typed_details(analysis, MetadataForm(request.POST, summary=analysis.summary))
        analysis.save()
        return redirect("stations:setup", analysis_id=analysis.pk)
    data = request.POST.copy()
    if not data.get("station_name") and analysis.station_name:
        data["station_name"] = analysis.station_name  # the file's name, as R does
    form = MetadataForm(data, summary=analysis.summary)
    if form.is_valid():
        return check_and_calculate(request, analysis, form)
    keep_typed_details(analysis, MetadataForm(data, summary=analysis.summary))
    analysis.save()
    if inspection is not None and workspace.set_up(analysis):
        calculation.bring_up_to_date(request, analysis)  # a new file, as for "read"
    return render(request, "stations/new.html", setup_context(request, analysis, form))


@require_http_methods(["GET", "HEAD", "POST"])
def upload(request):
    """The upload page's old address (before #201): to the New station page."""
    return redirect("stations:new")


@require_http_methods(["GET", "HEAD", "POST"])
def load(request, analysis_id):
    """The first visit's details' old address (Data before #198, Load before #201): the
    station's setup page, or once it is set up Quality's "Your data"."""
    analysis = get_analysis(request, analysis_id)
    if workspace.set_up(analysis):
        return redirect(reverse("stations:qc", args=[analysis.pk]) + "#your-data")
    return redirect("stations:setup", analysis_id=analysis.pk)


@require_http_methods(["GET", "HEAD", "POST"])
@disk_required
def sample(request):
    """One click: an analysis of the Sydney sample with its metadata filled in, on its
    setup page, to check and calculate."""
    if request.method != "POST":
        return redirect("stations:new")
    inspection = inspect_station_bytes(sample_bytes())
    with transaction.atomic():
        analysis = Station(owner=owner_token(request), source=Source.SAMPLE)
        apply_inspection(analysis, inspection, SAMPLE_NAME)
        for name, value in SAMPLE_METADATA.items():
            setattr(analysis, name, value)
        analysis.save()
    request.session["setup_read"] = str(analysis.pk)
    return redirect("stations:setup", analysis_id=analysis.pk)


@require_safe
def sample_file(request):
    """The sample station file, to look at or to use as a template (R links to it)."""
    response = HttpResponse(sample_bytes(), content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{SAMPLE_NAME}"'
    return response


def initial_metadata(analysis: Station) -> dict:
    """The station's details, with its workspace's base period."""
    return {
        "station_name": analysis.station_name,
        "latitude": analysis.latitude,
        "longitude": analysis.longitude,
        "base_start": analysis.workspace.base_start,
        "base_end": analysis.workspace.base_end,
    }


def percent_text(variable: dict) -> str:
    if variable["missing"] and variable["percent_missing"] < 0.1:
        return _("under 0.1%")
    return _("%(value)s%%") % {"value": f"{variable['percent_missing']:.1f}"}


def summary_context(analysis: Station) -> dict:
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


@require_POST
def validate(request, analysis_id=None):
    """htmx: one group of fields checked as it changes, returned on its own; against the
    file once one is read."""
    analysis = get_analysis(request, analysis_id) if analysis_id else None
    unit = request.POST.get("group", "")
    if unit not in MetadataForm.UNITS:
        return HttpResponseBadRequest()
    form = MetadataForm(request.POST, summary=analysis.summary if analysis else None)
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
    return redirect("stations:new")


# ---- Step 2: quality control (#77) ----------------------------------------------------


def step_two_ready(analysis: Station) -> bool:
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


def selected_item(request, review) -> str:
    """The item of the list shown in detail (#202): ``?show=``, or without it the table
    whose page the address asks for (a pager's link), or none (the first)."""
    show = request.GET.get("show", "")
    if show:
        return show
    for table in review.tables:
        if f"{table.table_id}_page" in request.GET:
            return table.table_id
    return ""


def qc_context(request, analysis: Station, **extra) -> dict:
    from climpact_web.jobs.views import progress_context

    job, shown = analysis.qc_job, workspace.shown_qc(analysis)
    changes = workspace.qc_changes(analysis, shown)
    from climpact_web.stations import qc_review

    review = None
    if shown is not None:
        try:
            review = qc_review.review(shown, analysis.station_file)
        except FileNotFoundError:
            pass
        if review is not None:
            # Before the tabs, so that Quality's shows this verdict (#222).
            workspace.remember_verdict(shown, review.verdict.level, review.verdict.wrong)
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
    if review is not None:
        from climpact_web.stations import qc_plots

        pages = table_pages(request, review)
        selected = review.item(selected_item(request, review))
        items = [
            {
                "item": item,
                "page": pages.get(item.check.table_id) if not item.finding else None,
                "selected": item.id == selected.id,
            }
            for item in review.items
        ]
        context.update(
            review=review,
            items=items,
            wrong_items=[i for i in items if i["item"].wrong],
            # "Look wrong" by check (#235): each check's findings, then its every row.
            wrong_groups=[
                {
                    "check": found.check,
                    "entries": [
                        i for i in items if i["item"].wrong and i["item"].check is found.check
                    ],
                }
                for found in review.findings
            ],
            worth_items=[i for i in items if not i["item"].wrong],
            selected=selected,
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
    """Quality: the checks run as a job and their results. The thresholds are in the
    Inputs panel (#199)."""
    analysis = get_analysis(request, analysis_id)
    if not step_two_ready(analysis):
        return redirect("stations:setup", analysis_id=analysis.pk)
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


@never_cache
@require_safe
def qc_flagged(request, analysis_id):
    """Every value the checks shown flagged, as one CSV (#235): the verdict strip's
    "Flagged values (CSV)" (``qc_review.flagged_rows``)."""
    from climpact_web.stations import qc_review

    analysis = get_analysis(request, analysis_id)
    job = workspace.shown_qc(analysis)
    if job is None:
        raise Http404
    try:
        review = qc_review.review(job, analysis.station_file)
    except FileNotFoundError as exc:
        raise Http404 from exc
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    name = safe_station_name(analysis.station_name or "station") or "station"
    response["Content-Disposition"] = f'attachment; filename="{name}_flagged_values.csv"'
    writer = csv.writer(response)
    writer.writerow(qc_review.FLAGGED_COLUMNS)
    writer.writerows(qc_review.flagged_rows(review))
    return response


@require_POST
def qc_continue(request, analysis_id):
    """ "See results", whatever the checks found (the user decides): straight to the
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


def next_url(request, analysis: Station) -> str:
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


def input_form(analysis: Station, key: str, data=None, files=None):
    """The form of the sheet ``key``: unbound with the saved values, or bound to ``data``."""
    if key == "file":
        # Its own ids, apart from the first visit's file field.
        return UploadForm(data, files, auto_id="sheet_%s")
    if key == "thresholds":
        if data is not None:
            return QCParamsForm(data)
        return QCParamsForm(initial=QCParamsForm.initial_for(analysis.workspace.qc_params))
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


def sheet_context(analysis: Station, key: str, form=None) -> dict:
    """One sheet's context: its key, title, form and what applying it will update; for the
    index settings, where they come from (``settings_source``: a batch's line, say)."""
    context = {
        "key": key,
        "title": INPUT_SHEETS[key][0],
        "intro": INPUT_SHEETS[key][1],
        "form": form if form is not None else input_form(analysis, key),
        "impact": workspace.impact(key, analysis),
    }
    if key == "settings":
        context["settings_source"] = calculation.previous_params(analysis)[5]
    return context


def apply_thresholds(request, analysis: Station, form: QCParamsForm) -> None:
    """Apply the Quality thresholds sheet: the workspace's thresholds (#254). New ones
    replace every station's checks and run (the run's QC files use them too), whose
    results stay, out of date, until then (#179). The same thresholds run this station's
    checks again when the shown ones failed, were stopped or never ran: Apply is how the
    user runs them again since the form left Quality (#199)."""
    values = {k: form.cleaned_data[k] for k in QC_DEFAULTS}
    if values != QCParamsForm.initial_for(analysis.workspace.qc_params):
        calculation.change_settings(request, analysis, qc_params=values)
        return
    job = analysis.qc_job
    if job is None or job.status in (Status.FAILED, Status.CANCELLED):
        queue_qc(request, analysis)


def apply_settings(request, analysis: Station, form) -> None:
    """Apply the Index settings sheet: the workspace's index settings and output options
    (#254), except the index values that are the station's own (a batch's metadata line),
    which change for this station only. A change recalculates every station of the
    workspace; the results shown are replaced when their runs have finished (#178). The
    same settings queue this station's run again ("Adjust and recalculate" on Results until
    #199)."""
    chosen = workspace.settings_of(calculation.station_params(analysis, form))
    own = workspace.own_params(analysis)
    shared = workspace.workspace_settings(analysis.workspace)["params"]
    # The station's own values change for it alone: the workspace's stay as they were.
    chosen["params"].update({name: shared[name] for name in own})
    index_settings = {} if chosen == workspace.default_settings() else chosen
    new_own = {name: form.job_params()[name] for name in own}
    workspace.restore_if_cancelled(analysis)
    if not calculation.change_settings(
        request, analysis, own=new_own, index_settings=index_settings
    ):
        calculation.queue_station_run(request, analysis, form)
    analysis.advance_to(Step.RESULTS)
    analysis.touch()
    analysis.save()


def apply_file(request, analysis: Station, form: UploadForm):
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
        return inspection, redirect("stations:setup", analysis_id=analysis.pk)
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
    once the data is in use ("See results"): before, only the results use them."""
    analysis = get_analysis(request, analysis_id)
    if key not in INPUT_SHEETS:
        raise Http404
    if not workspace.set_up(analysis):
        return redirect("stations:setup", analysis_id=analysis.pk)
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
            elif key == "base-period":
                data = form.cleaned_data
                calculation.change_settings(
                    request, analysis, base_start=data["base_start"], base_end=data["base_end"]
                )
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


@require_POST
def undo(request, analysis_id):
    """ "Undo the change" (#254): put back the workspace's settings as they were before its
    last change, while the recalculation it started is still on the way, and show the
    earlier checks and results again (``calculation.undo``). A plain form, so it works
    without JavaScript; then back to the page it was sent from."""
    analysis = get_analysis(request, analysis_id)
    if calculation.undo(analysis.workspace):
        messages.success(
            request, _("The change was undone. The earlier settings and results are back.")
        )
    else:
        messages.warning(
            request,
            _(
                "The recalculation has finished, so the change can no longer be undone. "
                "Change the settings back instead."
            ),
        )
    return redirect(next_url(request, analysis))


@never_cache
@require_safe
def inputs_progress(request, analysis_id):
    """The Inputs panel's runs (#198), polled by htmx while the checks or a run of new
    inputs are under way; once they have all finished the page reloads to show them."""
    analysis = get_analysis(request, analysis_id)
    if not workspace.set_up(analysis):
        raise Http404
    # The page polling, where "Undo the change" returns (htmx sends its address).
    from urllib.parse import urlsplit

    page = urlsplit(request.headers.get("HX-Current-URL", "")).path
    panel = workspace.inputs_panel(analysis, page)
    if not panel["input_runs"]:
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"
        return response
    return render(request, "stations/_input_runs.html", {"analysis": analysis, **panel})

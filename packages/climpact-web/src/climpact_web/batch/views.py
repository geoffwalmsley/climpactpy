"""The batch page (#80), replacing the R app's batch screen (``batchStep1UI.R``).

1. ``batch:start``: upload the metadata file and the station files (or a zip), or try
   the sample batch.
2. ``batch:check``: every station listed as ready, missing or invalid with the reasons,
   before anything runs; add or replace files; choose the options; start.
3. ``batch:results``: one job runs the ready stations, with each station's progress;
   then each station's status, errors and downloads, and one zip of everything.

A batch is visible only to the browser session that created it, like a job: any other
session gets 404.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from climpact_web.batch import check
from climpact_web.batch.forms import AddFilesForm, OptionsForm, UploadForm, cpu_count
from climpact_web.batch.models import BatchRun, Source
from climpact_web.core.limits import disk_required, human_required
from climpact_web.core.navigation import batch_steps
from climpact_web.jobs.models import Status
from climpact_web.jobs.runners import STATIONS_FILE
from climpact_web.jobs.stages import stage_label
from climpact_web.jobs.views import (
    OWNER_KEY,
    create_job,
    format_duration,
    owner_token,
    poll_delay,
)
from climpact_web.jobs.worker import worker_running
from climpact_web.stations.forms import MIN_BASE_DAYS
from climpact_web.stations.station_file import base_period_days, decode

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"
SAMPLE_METADATA = "climpact.sample.batch.metadata.txt"
RECENT_BATCHES = 5
# A rough guide for the time estimate, measured on a laptop: seconds per station.
SECONDS_PER_STATION = {True: 13, False: 4}  # with plots and the PDF report (#79), without
JOB_METADATA = "batch_metadata.txt"
JOB_STATIONS = "stations"


def sample_files() -> dict[str, bytes]:
    """R's sample batch: two copies of the Sydney file under the names its metadata file
    gives (R ships the same file twice; the package keeps one, gzipped)."""
    from climpact_web.stations.views import sample_bytes

    data = sample_bytes()
    return {
        "sydney_observatory_hill_1936-2015.txt": data,
        "sydney_observatory_hill_batch_file_2.txt": data,
    }


def sample_metadata() -> bytes:
    return (SAMPLE_DIR / SAMPLE_METADATA).read_bytes()


def get_run(request, run_id) -> BatchRun:
    owner = request.session.get(OWNER_KEY) or "-"
    return get_object_or_404(BatchRun, pk=run_id, owner=owner)


def read(uploaded) -> bytes:
    return b"".join(uploaded.chunks())


def run_urls(run: BatchRun) -> dict[str, str]:
    """Links for the step indicator."""
    urls = {"upload": reverse("batch:start"), "check": reverse("batch:check", args=[run.pk])}
    if run.job_id:
        urls["results"] = reverse("batch:results", args=[run.pk])
    return urls


def recheck(run: BatchRun, upload_problems: list[str] | None = None) -> None:
    """Check the batch's files again (after any change) and save the result."""
    metadata = run.metadata_path.read_bytes() if run.metadata_path.is_file() else None
    result = check.check_batch(metadata, run.station_files())
    result.upload_problems = list(upload_problems or [])
    run.report = result.to_json()
    run.touch()
    run.save()


# ---- Step 1: the files -------------------------------------------------------------------


def start_context(request, form) -> dict:
    owner = request.session.get(OWNER_KEY) or "-"
    return {
        "form": form,
        "steps": batch_steps("upload"),
        "recent": BatchRun.objects.filter(owner=owner)[:RECENT_BATCHES],
        "max_upload_mb": settings.MAX_UPLOAD_MB,
        "sample_metadata": SAMPLE_METADATA,
        "columns": column_rows(),
    }


def column_rows() -> list[dict]:
    """The metadata columns for the format help: name and meaning."""
    return [{"name": c, "label": check.column_label(c)} for c in check.COLUMNS]


def default_workers(stations: int) -> int:
    """Stations at a time: R's default is 1 core; here up to 4, leaving a core free for
    the rest of the computer, and never more than there are stations. Always 1 when
    hosted, where the option is not offered (as in R)."""
    if settings.IS_HOSTED:
        return 1
    return max(1, min(4, cpu_count() - 1, stations))


@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def start(request):
    """Upload the metadata file and the station files."""
    if request.method == "POST":
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            run = create_run(
                request,
                metadata=form.cleaned_data["metadata_file"],
                station_files=form.cleaned_data["station_files"],
            )
            return redirect("batch:check", run_id=run.pk)
    else:
        form = UploadForm()
    return render(request, "batch/start.html", start_context(request, form))


def create_run(request, metadata, station_files) -> BatchRun:
    uploads = [(f.name, read(f)) for f in station_files]
    metadata_name, metadata_bytes = "", None
    if metadata is not None:
        if metadata.name.lower().endswith(".zip"):
            uploads.insert(0, (metadata.name, read(metadata)))
        else:
            metadata_name, metadata_bytes = metadata.name, read(metadata)
    unpacked = check.unpack(uploads)
    if metadata_bytes is None and unpacked.metadata:
        metadata_name, metadata_bytes = unpacked.metadata
    with transaction.atomic():
        run = BatchRun(owner=owner_token(request), metadata_name=(metadata_name or "")[:255])
        run.save()
        if metadata_bytes is not None:
            run.save_metadata(metadata_bytes)
        run.save_files(unpacked.files)
        run.workers = default_workers(len(unpacked.files))
        recheck(run, unpacked.problems)
    return run


@require_http_methods(["GET", "HEAD", "POST"])
@disk_required
def sample(request):
    """One click: R's sample batch (two Sydney stations), checked and ready to start."""
    if request.method != "POST":
        return redirect("batch:start")
    with transaction.atomic():
        run = BatchRun(
            owner=owner_token(request), source=Source.SAMPLE, metadata_name=SAMPLE_METADATA
        )
        run.save()
        run.save_metadata(sample_metadata())
        run.save_files(sample_files())
        run.workers = default_workers(2)
        recheck(run)
    return redirect("batch:check", run_id=run.pk)


@require_safe
def sample_metadata_file(request):
    """R's sample metadata file, to use as a template (R links to it too)."""
    response = HttpResponse(sample_metadata(), content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{SAMPLE_METADATA}"'
    return response


# ---- Step 2: the check ---------------------------------------------------------------------


def initial_options(run: BatchRun) -> dict:
    return {
        "base_start": run.base_start,
        "base_end": run.base_end,
        "workers": run.workers,
        "plots": run.plots,
    }


def coverage_notes(run: BatchRun, start: int | None, end: int | None) -> list[dict]:
    """Ready stations whose data barely cover the base period: their percentile indices
    (TX90p, WSDI, R95p and others) cannot be calculated, as in R."""
    if start is None or end is None or start > end:
        return []
    notes = []
    for station in check.ready_stations(run.report):
        summary = station.get("summary")
        if not summary:
            continue
        if base_period_days(summary, start, end) <= MIN_BASE_DAYS:
            notes.append(
                {
                    "name": station["name"],
                    "first": summary["first_year"],
                    "last": summary["last_year"],
                }
            )
    return notes


def estimate(run: BatchRun, form: OptionsForm) -> str:
    data = form.cleaned_data if form.is_bound and form.is_valid() else initial_options(run)
    count = run.ready_count
    if not count:
        return ""
    workers = data.get("workers") or 1
    seconds = SECONDS_PER_STATION[bool(data.get("plots"))] * math.ceil(count / workers)
    minutes = max(1, round(seconds / 60))
    return ngettext("about %(n)d minute", "about %(n)d minutes", minutes) % {"n": minutes}


def options_context(run: BatchRun, form: OptionsForm) -> dict:
    if form.is_bound and form.is_valid():
        start, end = form.cleaned_data["base_start"], form.cleaned_data["base_end"]
    elif form.is_bound:
        start = end = None
    else:
        start, end = run.base_start, run.base_end
    return {
        "run": run,
        "options": form,
        "coverage": coverage_notes(run, start, end),
        "estimate": estimate(run, form),
    }


def check_context(request, run: BatchRun, options=None, add_form=None) -> dict:
    report = run.report
    stations = report.get("stations", [])
    return {
        "run": run,
        "report": report,
        "stations": stations,
        "counts": {
            "listed": len(stations),
            "ready": run.count("ready"),
            "missing": run.count("missing"),
            "invalid": run.count("invalid"),
        },
        "not_ready": len(stations) - run.ready_count,
        "add_form": add_form or AddFilesForm(),
        "steps": batch_steps("check", run_urls(run)),
        "max_upload_mb": settings.MAX_UPLOAD_MB,
        "job_active": bool(run.job and not run.job.is_finished),
        **options_context(run, options or OptionsForm(initial=initial_options(run))),
    }


@never_cache
@require_safe
def check_page(request, run_id):
    run = get_run(request, run_id)
    return render(request, "batch/check.html", check_context(request, run))


@require_POST
@human_required
def add_files(request, run_id):
    """Add or replace station files, or replace the metadata file, then check again."""
    run = get_run(request, run_id)
    form = AddFilesForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "batch/check.html", check_context(request, run, add_form=form))
    uploads = [(f.name, read(f)) for f in form.cleaned_data["station_files"]]
    unpacked = check.unpack(uploads)
    metadata = form.cleaned_data["metadata_file"]
    if metadata is not None:
        run.metadata_name = metadata.name[:255]
        run.save_metadata(read(metadata))
    elif unpacked.metadata:
        run.metadata_name, data = unpacked.metadata
        run.save_metadata(data)
    run.save_files(unpacked.files)
    recheck(run, unpacked.problems)
    count = len(unpacked.files) + (1 if metadata or unpacked.metadata else 0)
    messages.success(
        request,
        ngettext(
            "%(count)d file loaded. The stations were checked again.",
            "%(count)d files loaded. The stations were checked again.",
            count,
        )
        % {"count": count},
    )
    return redirect("batch:check", run_id=run.pk)


@require_POST
def options(request, run_id):
    """htmx: the options checked as they change (base period coverage, the estimate),
    returned on their own."""
    run = get_run(request, run_id)
    if not request.headers.get("HX-Request"):
        return HttpResponseBadRequest()
    form = OptionsForm(request.POST)
    form.is_valid()
    return render(request, "batch/_options.html", options_context(run, form))


@require_POST
@human_required
def run_batch(request, run_id):
    """Queue the batch: one job for the ready stations."""
    run = get_run(request, run_id)
    form = OptionsForm(request.POST)
    if not form.is_valid() or not run.ready_count:
        return render(request, "batch/check.html", check_context(request, run, options=form))
    if run.job and not run.job.is_finished:
        return redirect("batch:results", run_id=run.pk)
    data = form.cleaned_data
    run.base_start, run.base_end = data["base_start"], data["base_end"]
    run.workers = data.get("workers") or 1
    run.plots = data["plots"]

    ready = check.ready_stations(run.report)
    skipped = [
        {"name": s["name"], "station_file": s["station_file"], "error": skip_reason(s)}
        for s in run.report.get("stations", [])
        if s["status"] != "ready"
    ]
    files = {JOB_METADATA: ContentFile(check.metadata_text(ready).encode("utf-8"))}
    for station in ready:
        path = run.files_dir / station["station_file"]
        # Stored as uploaded; the check accepted it, so it is text. Into the job as the
        # station step stores files: UTF-8 without a byte-order mark.
        text = decode(path.read_bytes())
        files[f"{JOB_STATIONS}/{station['station_file']}"] = ContentFile(text.encode("utf-8"))
    params = {
        "metadata_file": JOB_METADATA,
        "data_dir": JOB_STATIONS,
        "base_start": run.base_start,
        "base_end": run.base_end,
        "workers": run.workers,
        "plots": run.plots,
        "zip": True,
        "station_zips": True,
        "report": run.plots,  # each station's PDF report, with the plots (#79)
        "folder": run.folder_name,
        "skipped": skipped,
    }
    title = ngettext(
        "Batch: %(name)s (%(count)d station)", "Batch: %(name)s (%(count)d stations)", len(ready)
    ) % {"name": run.metadata_name or _("stations"), "count": len(ready)}
    job = create_job(request, "batch", params, files, title=title)
    run.job = job
    run.touch()
    run.save()
    return redirect("batch:results", run_id=run.pk)


def skip_reason(station: dict) -> str:
    """Why a station was left out, in the station's error file."""
    lines = [p["message"] for p in station.get("problems", [])]
    hidden = station.get("problem_count", 0) - len(lines)
    if hidden > 0:
        lines.append(_("And %(count)d more problems like these.") % {"count": hidden})
    head = (
        _("Not calculated: the station file is missing.")
        if station["status"] == "missing"
        else _("Not calculated: the station has problems.")
    )
    return "\n".join([head, *lines])


@require_POST
def delete(request, run_id):
    run = get_run(request, run_id)
    run.delete_files()
    run.delete()
    messages.success(request, _("The batch files were deleted."))
    return redirect("batch:start")


# ---- Step 3: the run and the results ---------------------------------------------------------


STATE_ORDER = {"failed": 0, "running": 1, "waiting": 2, "done": 3, "skipped": 4}


def station_status(job) -> list[dict]:
    """Each station's progress, from the runner's ``stations.json`` (written as it goes)
    or, once the job has finished, from its result."""
    if job.status == Status.SUCCEEDED and job.result.get("stations") is not None:
        rows = []
        for s in job.result["stations"]:
            rows.append({**s, "state": "done" if s["ok"] else "failed"})
        for s in job.result.get("skipped", []):
            rows.append({**s, "state": "skipped", "ok": False})
        return rows
    path = job.output_dir / STATIONS_FILE
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    return data.get("stations", [])


def plain_error(text: str | None, job) -> str:
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


def results_context(request, run: BatchRun) -> dict:
    from django.utils import timezone

    job = run.job
    now = timezone.now()
    rows = []
    opened = opened_analyses(run) if job.status == Status.SUCCEEDED else {}
    for s in station_status(job):
        state = s.get("state", "waiting")
        rows.append(
            {
                **s,
                "state": state,
                "error_text": plain_error(s.get("error"), job) if state == "failed" else "",
                "skip_lines": (s.get("error") or "").split("\n")[1:] if state == "skipped" else [],
                "stage_label": stage_label(s.get("stage", "")) if state == "running" else "",
                "percent": int(100 * s["step"] / s["total"]) if s.get("total") else 0,
                "opened_url": opened.get(s["name"]),
                "zip_size": _size(job, s.get("zip")),
                "report_size": _size(job, s.get("report")),
            }
        )
    finished = job.status == Status.SUCCEEDED
    counts = {
        k: sum(1 for r in rows if r["state"] == k)
        for k in ("done", "failed", "skipped", "running", "waiting")
    }
    if finished:  # failures first, so they are not missed
        rows.sort(key=lambda r: STATE_ORDER.get(r["state"], 9))
    remaining = job.remaining(now)
    return {
        "run": run,
        "job": job,
        "rows": rows,
        "counts": counts,
        "total_stations": len(rows) - counts["skipped"],
        "stage_label": stage_label(job.stage),
        "elapsed": format_duration(job.elapsed(now)),
        "remaining": format_duration(remaining) if remaining is not None else "",
        "delay": poll_delay(job, request.GET.get("hidden") == "true", now),
        "worker_missing": job.status == Status.QUEUED and not worker_running(now),
        "zip_file": job.result.get("zip") if finished else None,
        "zip_size": _size(job, job.result.get("zip")) if finished else 0,
    }


def _size(job, relative: str | None) -> int:
    """The size of a file of the job's output (0 when there is none), for the buttons."""
    if not relative:
        return 0
    path = job.output_dir / relative
    return path.stat().st_size if path.is_file() else 0


def opened_analyses(run: BatchRun) -> dict[str, str]:
    """Stations of this batch already opened as single-station analyses: name -> URL."""
    from climpact_web.stations.models import StationAnalysis

    out = {}
    for analysis in StationAnalysis.objects.filter(owner=run.owner, origin__batch=str(run.pk)).only(
        "id", "origin"
    ):
        out[analysis.origin.get("station", "")] = reverse("stations:results", args=[analysis.pk])
    return out


@never_cache
@require_safe
def results(request, run_id):
    run = get_run(request, run_id)
    if run.job is None:
        return redirect("batch:check", run_id=run.pk)
    context = results_context(request, run)
    context["steps"] = batch_steps("results", run_urls(run))
    return render(request, "batch/results.html", context)


@never_cache
@require_safe
def progress(request, run_id):
    """The progress and results fragment, polled by htmx while the job runs."""
    run = get_run(request, run_id)
    if run.job is None:
        raise Http404
    if run.job.status == Status.RUNNING:
        from climpact_web.jobs.worker import reap_stale

        if reap_stale():
            run.job.refresh_from_db()
    return render(request, "batch/_progress.html", results_context(request, run))


@require_POST
def open_station(request, run_id, name):
    """Open a finished station of the batch as a single-station analysis: its file and
    metadata (name, location, base period) are filled in, and the index parameters of its
    metadata line are kept in ``origin`` for the indices step (#78)."""
    from climpact_web.stations.models import Source as StationSource
    from climpact_web.stations.models import StationAnalysis, Step
    from climpact_web.stations.station_file import inspect_station_bytes

    run = get_run(request, run_id)
    job = run.job
    if job is None or job.status != Status.SUCCEEDED:
        raise Http404
    result = next((s for s in job.result.get("stations", []) if s["name"] == name), None)
    station = next((s for s in run.report.get("stations", []) if s["name"] == name), None)
    if result is None or not result["ok"] or station is None:
        raise Http404
    existing = StationAnalysis.objects.filter(
        owner=run.owner, origin__batch=str(run.pk), origin__station=name
    ).first()
    if existing:
        return redirect("stations:results", analysis_id=existing.pk)
    path = job.input_dir / JOB_STATIONS / station["station_file"]
    if not path.is_file():
        raise Http404
    inspection = inspect_station_bytes(path.read_bytes())
    if not inspection.ok:
        raise Http404
    with transaction.atomic():
        analysis = StationAnalysis(
            owner=run.owner,
            source=StationSource.BATCH,
            file_name=station["station_file"][:255],
            summary=inspection.summary,
            warnings=inspection.warnings,
            station_name=name,
            latitude=station["latitude"],
            longitude=station["longitude"],
            base_start=job.params.get("base_start", run.base_start),
            base_end=job.params.get("base_end", run.base_end),
            step=Step.QC,
            origin={
                "batch": str(run.pk),
                "job": str(job.pk),
                "station": name,
                "params": station["params"],
                "outputs": result.get("folder"),
            },
        )
        analysis.save()
        analysis.save_station_text(inspection.text)
    messages.success(
        request,
        _("%(name)s is open as a single station, with its data and details from the batch.")
        % {"name": name},
    )
    return redirect("stations:results", analysis_id=analysis.pk)

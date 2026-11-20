"""The gridded pages (#85), replacing the R app's two gridded screens
(``griddedStep1UI.R``, indices, and ``griddedStep2UI.R``, thresholds). A run is a place
of its own, like a workspace (#289, the Grid boards):

- ``gridded:start`` (``/gridded/``): Gridded, the browser's runs in a table
  (:func:`climpact_web.gridded.runs.entries`), New gridded run, and the sample grid.
- ``gridded:new``: choose the netCDF files: on this computer from a folder listing that
  shows each file's variables and dates, or by path and pattern (local mode, read in
  place; :mod:`climpact_web.gridded.listing`), by upload (size-limited, hosted), or the
  sample grid.
- ``gridded:setup`` (``<run>/setup/``, the GridSetup board, #293): one page of sections
  (the files, each with its header; which variable is TX, TN and precipitation, their
  units and how they are read; what to calculate; the base period; the indices; the
  output files; computing) beside a summary panel that is the check, updated as the form
  changes (``gridded:checks``) and again with the core's own reader before anything runs.
  Before a run it has a breadcrumb; after, it is the run's Set-up tab, and starting again
  keeps the results until the new ones are ready.
- ``gridded:run`` (``<run>/``), the run's Map tab: the thresholds and indices jobs with
  their progress (the rechunking stage included) while they run, then a map of an index
  at one time step and the time series of a chosen cell, each with a table. The old
  ``<run>/results`` address redirects here.
- ``gridded:files`` (``<run>/files/``), the Files tab: the index files grouped by theme,
  variable needed or frequency, each group with its zip; Download all, the links for
  ``wget -i`` and the run's record (``run.json``, the log).

Gridded runs are offered in local mode, and in hosted mode only with
``CLIMPACT_WEB_GRIDDED_HOSTED`` (``settings.GRIDDED_ENABLED``); otherwise every page is
404. Paths on the server's disk are only ever accepted in local mode. A run is visible
only to the browser session that created it, like a job.
"""

from __future__ import annotations

import csv
import datetime as dt
import functools
import io
import os
import re
import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.gzip import gzip_page
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from climpact_web.core.limits import disk_required, human_required
from climpact_web.gridded import inspection, listing, maps, runs, setup_page
from climpact_web.gridded.forms import (
    MAX_FILES,
    SLOW_INDICES,
    PathsForm,
    RenameForm,
    SetupForm,
    UploadForm,
    all_indices,
    default_base,
    default_template,
    default_thresholds_name,
    expand,
    expand_pattern,
    has_pattern,
    path_lines,
)
from climpact_web.gridded.models import GriddedRun, Source
from climpact_web.jobs.models import Status
from climpact_web.jobs.stages import stage_label
from climpact_web.jobs.views import OWNER_KEY, create_job, format_duration, owner_token, poll_delay
from climpact_web.jobs.worker import worker_running

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"
SAMPLE_FILE = "climpact.sampledata.gridded.3x4.1991-2010.nc"
SAMPLE_INSTITUTION = ("Climpact sample", "CPS")
SAFE_NAME = re.compile(r"[^A-Za-z0-9._+-]")


def gridded_enabled(view):
    """404 unless gridded runs are offered in this mode."""

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        if not settings.GRIDDED_ENABLED:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapper


def get_run(request, run_id) -> GriddedRun:
    owner = request.session.get(OWNER_KEY) or "-"
    run = get_object_or_404(GriddedRun, pk=run_id, owner=owner)
    run.settle()  # a new start that has finished takes the old results' place (#293)
    return run


# ---- Gridded: the runs ----------------------------------------------------------------------


@never_cache
@gridded_enabled
@require_safe
def start(request):
    """``/gridded/``: the browser's runs (the computer's, locally), most recently changed
    first (the GridList board); with none, one line and the sample grid."""
    owner = request.session.get(OWNER_KEY) or "-"
    return render(
        request,
        "gridded/start.html",
        {
            "entries": runs.entries(owner),
            "local": not settings.IS_HOSTED,
            "sample_name": SAMPLE_FILE,
        },
    )


# ---- New run: the files ----------------------------------------------------------------------


FOLDER_KEY = "gridded_folder"  # the session's last folder listed by the chooser (#292)


def chooser_folder(request, wanted: str | None, fallback: str | None = None) -> tuple[Path, str]:
    """The folder the chooser lists: ``wanted`` when it is one, else ``fallback``, the
    folder listed last in this session or the home folder; with an error when ``wanted``
    is not a folder."""
    error = ""
    if wanted:
        path = expand(wanted)
        if path.is_absolute() and path.is_dir():
            return path.resolve(), ""
        error = _("There is no folder %(path)s.") % {"path": wanted}
    for candidate in (fallback, request.session.get(FOLDER_KEY)):
        if candidate and Path(candidate).is_absolute() and Path(candidate).is_dir():
            return Path(candidate).resolve(), error
    return Path.home().resolve(), error


def chosen_paths(ticked: list[str], text: str) -> list[str]:
    """The files chosen so far, for the line under the chooser: those ticked, then those
    typed (patterns expanded), each once; paths that are not files left out quietly (the
    form says why when the files are read)."""
    out: list[str] = []
    for line in [*ticked, *path_lines(text)]:
        found = expand_pattern(line) if has_pattern(line) else [str(expand(line))]
        for path in found:
            if len(out) > MAX_FILES:
                return out
            if os.path.isabs(path) and os.path.isfile(path) and path not in out:
                out.append(path)
    return out


def new_context(
    request, data=None, paths_form=None, upload_form=None, folder=None, folder_error="", typed=None
) -> dict:
    """New gridded run (#292, the GridNew board). Locally: the folder listing (``folder``),
    the files ticked so far (``data``, the form posted, kept across folders), the paths box
    and what is chosen; ``paths_form`` with its errors once the files have been read."""
    local = not settings.IS_HOSTED
    context = {
        "upload_form": upload_form or UploadForm(),
        "max_upload_mb": settings.GRIDDED_MAX_UPLOAD_MB,
        "max_upload_bytes": settings.GRIDDED_MAX_UPLOAD_MB * 1024 * 1024,
        "max_files": MAX_FILES,
        "sample_name": SAMPLE_FILE,
        "sample_size": (SAMPLE_DIR / SAMPLE_FILE).stat().st_size,
        "local": local,
    }
    if not local:
        return context
    ticked = [p for p in data.getlist("file") if p] if data else []
    text = data.get("paths", "") if data else ""
    if folder is None:
        folder, folder_error = chooser_folder(request, None)
    request.session[FOLDER_KEY] = str(folder)
    context.update(
        paths_form=paths_form or PathsForm(),
        paths_value=text,
        browse=listing.listing(folder, ticked),
        folder_value=typed if folder_error and typed else str(folder),
        folder_error=folder_error,
        chosen=listing.summary(chosen_paths(ticked, text)),
    )
    return context


@gridded_enabled
@require_http_methods(["GET", "HEAD", "POST"])
def new(request):
    """New gridded run: choose the files. Hosted: an upload (posted to ``gridded:upload``).
    Locally: a folder listing, each netCDF file with a checkbox and what its header says,
    and a box for paths and patterns. The listing's folder links post the same form
    (``action=browse:<folder>``; the folder field, ``action=open``), so it works without
    JavaScript and keeps what is ticked; htmx swaps only the listing, and puts what is
    chosen in the line under it as files are ticked (``?tick=1``)."""
    if request.method != "POST" or settings.IS_HOSTED:
        if request.method == "POST":
            return redirect("gridded:new")
        folder = folder_error = None
        if not settings.IS_HOSTED and request.GET.get("dir"):
            folder, folder_error = chooser_folder(request, request.GET["dir"])
        context = new_context(request, folder=folder, folder_error=folder_error or "")
        return render(request, "gridded/new.html", context)
    # htmx asks for what is chosen with ?tick=1 (an hx-vals would reach the listing's
    # buttons too: htmx merges them from every ancestor).
    action = "tick" if request.GET.get("tick") else request.POST.get("action", "use")
    current = request.POST.get("current")
    typed = None
    if action.startswith("browse:"):
        folder, error = chooser_folder(request, action[7:], current)
    elif action == "open":
        typed = request.POST.get("folder", "").strip()
        folder, error = chooser_folder(request, typed, current)
    else:
        folder, error = chooser_folder(request, None, current)
    htmx = request.headers.get("HX-Request")
    form = None
    if action == "use":
        form = PathsForm(request.POST)
        if form.is_valid():
            run = create_run(request, Source.PATH, form.cleaned_data["paths"])
            return redirect("gridded:setup", run_id=run.pk)
        htmx = False  # the errors are shown with the whole page
    context = new_context(
        request, request.POST, form, folder=folder, folder_error=error, typed=typed
    )
    if htmx and action == "tick":
        return render(request, "gridded/_chosen.html", context)
    if htmx:
        return render(request, "gridded/_listing.html", context)
    return render(request, "gridded/new.html", context)


def create_run(request, source: str, paths: list[str]) -> GriddedRun:
    infos = [inspection.inspect_file(p) for p in paths]
    run = GriddedRun(owner=owner_token(request), source=source)
    run.files = [i.to_json() for i in infos]
    run.names = inspection.guess_names(infos)
    run.save()
    return run


@gridded_enabled
@require_POST
@human_required
def upload(request):
    """Uploaded netCDF files, kept in the run's own folder."""
    form = UploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "gridded/new.html", new_context(request, upload_form=form))
    with transaction.atomic():
        run = GriddedRun(owner=owner_token(request), source=Source.UPLOAD)
        run.save()
        run.uploads_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for uploaded in form.cleaned_data["files"]:
            name = SAFE_NAME.sub("_", Path(uploaded.name).name).lstrip(".") or "input.nc"
            target = run.uploads_dir / name
            n = 1
            while target.exists():
                n += 1
                target = run.uploads_dir / f"{Path(name).stem}_{n}{Path(name).suffix}"
            with target.open("wb") as out:
                for chunk in uploaded.chunks():
                    out.write(chunk)
            paths.append(str(target))
        infos = [inspection.inspect_file(p) for p in paths]
        for info, uploaded in zip(infos, form.cleaned_data["files"], strict=True):
            info.name = Path(uploaded.name).name
        run.files = [i.to_json() for i in infos]
        run.names = inspection.guess_names(infos)
        run.save()
    return redirect("gridded:setup", run_id=run.pk)


@gridded_enabled
@require_http_methods(["GET", "HEAD", "POST"])
@disk_required
def sample(request):
    """One click: a 3 x 4 cut of Climpact's sample grid (south-eastern Australia,
    1991-2010), read in place from the package."""
    if request.method != "POST":
        return redirect("gridded:new")
    run = create_run(request, Source.SAMPLE, [str(SAMPLE_DIR / SAMPLE_FILE)])
    run.files[0]["name"] = SAMPLE_FILE
    run.save()
    return redirect("gridded:setup", run_id=run.pk)


@gridded_enabled
@require_safe
def sample_file(request):
    path = SAMPLE_DIR / SAMPLE_FILE
    return FileResponse(path.open("rb"), as_attachment=True, filename=SAMPLE_FILE)


# ---- Set-up ----------------------------------------------------------------------------------


def base_days(summary: inspection.Summary, start: int, end: int) -> int:
    """Days of the files' time axis in the base period's years, assuming every day from
    the first to the last date is present (the core counts the actual days; the final
    check before a run uses its reader)."""
    if not summary.first or start > end:
        return 0
    calendar = (summary.calendar or "standard").lower()

    def ordinal(year: int, month: int, day: int) -> int:
        if calendar == "360_day":
            return year * 360 + (month - 1) * 30 + min(day, 30)
        if calendar in ("noleap", "365_day"):
            return (
                year * 365
                + dt.date(2001, month, min(day, 28) if month == 2 else day).timetuple().tm_yday
            )
        return dt.date(year, month, day).toordinal()

    first = ordinal(*(int(p) for p in summary.first.split("-")))
    last = ordinal(*(int(p) for p in summary.last.split("-")))
    lo = max(first, ordinal(start, 1, 1))
    hi = min(last, ordinal(end, 12, 30 if calendar == "360_day" else 31))
    return max(0, hi - lo + 1)


def run_summary(run: GriddedRun, names: dict | None = None):
    infos = run.file_infos()
    problems, summary = inspection.check_names(infos, names or run.names)
    return infos, problems, summary


def initial_setup(run: GriddedRun, summary: inspection.Summary) -> dict:
    from climpact.gridded.indices import WRAPPER_PARAMS
    from climpact.gridded.io import DEFAULT_MAX_VALUES
    from climpact_web.batch.forms import cpu_count

    if run.options:
        return {**run.options, **run.names}
    start, end = default_base(summary.first_year, summary.last_year)
    institution, institution_id = SAMPLE_INSTITUTION if run.source == Source.SAMPLE else ("", "")
    return {
        **run.names,
        "task": "indices",
        "thresholds_source": "compute",
        "base_start": start,
        "base_end": end,
        "template": default_template(summary.first_year, summary.last_year),
        "thresholds_name": default_thresholds_name(run.files, start, end),
        "institution": institution,
        "institution_id": institution_id,
        "indices": all_indices(),
        **{k: getattr(WRAPPER_PARAMS, k) for k in SetupForm.PARAMS},
        "workers": max(1, min(4, cpu_count() - 1)),
        "max_values": default_max_values(summary, DEFAULT_MAX_VALUES),
        "rechunk": "auto",
    }


PROGRESS_BLOCKS = 20  # aim for about this many blocks, so progress moves in small steps


def default_max_values(summary: inspection.Summary, core_default: int) -> float:
    """Values read at once, in millions: the core's default (5 million), or less for a
    small grid, so that it is read in about :data:`PROGRESS_BLOCKS` blocks. Progress is
    reported after each block, so a grid of one or two blocks would show none for most
    of the run."""
    total = summary.days * summary.cells * 3
    value = min(core_default, total / PROGRESS_BLOCKS) if total else core_default
    return max(0.1, round(value / 1e6, 1))


def setup_form(run: GriddedRun, data=None, files=None) -> SetupForm:
    infos, _problems, summary = run_summary(run, _names_from(data) if data else None)
    return SetupForm(
        data,
        files,
        choices=inspection.variable_choices(infos),
        summary=summary,
        initial=None if data else initial_setup(run, summary),
        thresholds_uploaded=run.options.get("thresholds_uploaded", ""),
    )


def _names_from(data) -> dict:
    return {role: (data.get(role) or "") for role in inspection.ROLES}


def outputs_preview(form: SetupForm, summary: inspection.Summary) -> dict:
    """What the run will write: the number of index files and a few of their names."""
    from dataclasses import replace

    from climpact.gridded.indices import WRAPPER_PARAMS, index_files

    data = form.cleaned_data if form.is_bound and hasattr(form, "cleaned_data") else form.initial
    values = {}
    for key in SetupForm.PARAMS:
        value = data.get(key) if data else None
        if value is not None:
            values[key] = value
    try:
        params = replace(WRAPPER_PARAMS, **values)
        specs = index_files(params)
    except (TypeError, ValueError):
        return {}
    chosen = set(data.get("indices") or []) if data else set()
    if chosen or form.is_bound:
        specs = [s for s in specs if s.index in chosen]
    template = (data.get("template") if data else "") or default_template(
        summary.first_year, summary.last_year
    )
    try:
        examples = [s.filename(template) for s in specs[:3]]
    except ValueError:
        examples = []
    slow = sorted({s.index for s in specs if s.index in SLOW_INDICES})
    return {"count": len(specs), "examples": examples, "slow": slow, "specs": specs}


def setup_context(request, run: GriddedRun, form: SetupForm, preflight_error: str = "") -> dict:
    """The set-up page (the GridSetup board, #293): the Files table, the form's sections
    and the summary panel (setup_page.build)."""
    from climpact_web.batch.forms import cpu_count

    names = _names_from(form.data) if form.is_bound else run.names
    infos, problems, summary = run_summary(run, names)
    local = not settings.IS_HOSTED
    outputs = outputs_preview(form, summary)
    page = setup_page.build(
        run,
        form,
        infos,
        problems,
        summary,
        outputs,
        local=local,
        folder=Path(settings.RUNS_DIR),
        cores=cpu_count() if local else None,
        preflight_error=preflight_error,
    )
    groups = inspection.group_files(infos)
    paths = [f.path for f in infos]
    for group in groups:  # each row's Header opens its first file's
        group.number = paths.index(group.head.path)
    breadcrumb = [
        {"label": _("Gridded"), "url": reverse("gridded:start")},
        {"label": _("New run"), "url": reverse("gridded:new")},
        {"label": _("set-up")},
    ]
    return {
        "run": run,
        "form": form,
        "files": infos,
        "file_groups": groups,
        "setup_breadcrumb": breadcrumb,
        "names": names,
        "problems": problems,
        "summary": summary,
        "outputs": outputs,
        "preflight_error": preflight_error,
        "local": local,
        "job_active": run.job_active,
        "max_upload_mb": settings.GRIDDED_MAX_UPLOAD_MB,
        **page,
        **(bar_context(run, "setup") if run.jobs else {"run_name": run.display_name}),
        "data_page": True,  # the sections and the summary panel use the whole window
    }


@never_cache
@gridded_enabled
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def setup(request, run_id):
    run = get_run(request, run_id)
    if request.method != "POST":
        return render(request, "gridded/setup.html", setup_context(request, run, setup_form(run)))
    form = setup_form(run, request.POST, request.FILES)
    valid = form.is_valid()
    names = _names_from(request.POST)
    _infos, problems, _summary = run_summary(run, names)
    for role, message in problems.items():
        if role in form.fields and not form.errors.get(role):
            form.add_error(role, message)
    if not valid or problems:
        save_thresholds_upload(run, form)
        return render(request, "gridded/setup.html", setup_context(request, run, form))
    data = form.cleaned_data
    save_thresholds_upload(run, form)
    try:
        checked = inspection.preflight(run.paths, names, int(data["max_values"] * 1e6))
    except (ValueError, NotImplementedError, OSError) as exc:
        message = _("The files cannot be read together: %(error)s") % {"error": exc}
        return render(request, "gridded/setup.html", setup_context(request, run, form, message))
    if run.job_active:
        return redirect(run)
    options = {**options_json(run, data, checked), **_kept(run.options)}
    if runs.all_done(run):
        # Starting a finished run again (#293): the results stay until the new ones are
        # ready (GriddedRun.settle), so the new jobs and settings wait beside them.
        queue_jobs(request, run, options, names, pending=True)
        return redirect("gridded:setup", run.pk)
    run.names, run.options = names, options
    queue_jobs(request, run, options, names)
    return redirect(run)


def _kept(options: dict) -> dict:
    """What the run worked out once and keeps across a new start: the inputs' checksums
    (the cells with data belong to the old results, so they go)."""
    return {k: options[k] for k in ("checksums",) if k in options}


def save_thresholds_upload(run: GriddedRun, form: SetupForm) -> None:
    """Hosted mode: keep an uploaded thresholds file, so it survives a form error."""
    uploaded = form.files.get("thresholds_upload") if form.files else None
    if not uploaded:
        return
    run.thresholds_dir.mkdir(parents=True, exist_ok=True)
    for old in run.thresholds_dir.iterdir():
        old.unlink()
    name = SAFE_NAME.sub("_", Path(uploaded.name).name).lstrip(".") or "thresholds.nc"
    with (run.thresholds_dir / name).open("wb") as out:
        for chunk in uploaded.chunks():
            out.write(chunk)
    run.options = {**run.options, "thresholds_uploaded": name}
    form.thresholds_uploaded = name
    run.save(update_fields=["options"])


def options_json(run: GriddedRun, data: dict, checked: dict) -> dict:
    out = {k: v for k, v in data.items() if k != "thresholds_upload"}
    out["indices"] = list(data.get("indices") or [])
    if out.get("task") == "indices" and out.get("thresholds_source") == "file":
        if settings.IS_HOSTED:
            out["thresholds_file"] = str(run.thresholds_dir / run.options["thresholds_uploaded"])
            out["thresholds_uploaded"] = run.options["thresholds_uploaded"]
        else:
            out["thresholds_file"] = data["thresholds_path"]
    out["checked"] = checked
    return out


def queue_jobs(request, run: GriddedRun, options: dict, names: dict, pending: bool = False) -> None:
    """The thresholds job, the indices job, or both (thresholds first: the worker runs
    the oldest queued job first). Both read the input files in place. ``pending``: a new
    start of a finished run, whose jobs and settings wait beside the results shown until
    they have finished (#293)."""
    o = options
    common = {
        "input_files": run.paths,
        "names": names,
        "base_start": o["base_start"],
        "base_end": o["base_end"],
        "institution": o["institution"],
        "institution_id": o["institution_id"],
        "workers": o.get("workers") or 1,
        "max_values": int(o["max_values"] * 1e6),
        "rechunk": o.get("rechunk", "auto"),
        "tmp_dir": o.get("tmp_dir") or "",
        "copy_to": o.get("copy_to") or "",
    }
    label = str(run)
    task = o["task"]
    thresholds_job = indices_job = None
    with transaction.atomic():
        if task in ("thresholds", "both"):
            name = o.get("thresholds_name") or default_thresholds_name(
                run.files, o["base_start"], o["base_end"]
            )
            thresholds_job = create_job(
                request,
                "gridded-thresholds",
                {**common, "out_file": name},
                title=_("Gridded thresholds: %(files)s") % {"files": label},
            )
        if task in ("indices", "both"):
            chosen = o.get("indices") or []
            params = {k: o[k] for k in SetupForm.PARAMS}
            indices_job = create_job(
                request,
                "gridded-indices",
                {
                    **common,
                    "template": o.get("template") or "",
                    "indices": None if set(chosen) >= set(all_indices()) else chosen,
                    "thresholds_file": o.get("thresholds_file") or None,
                    "params": params,
                },
                title=_("Gridded indices: %(files)s") % {"files": label},
            )
        if pending:
            for job in run.next_jobs:  # an earlier new start that failed or was cancelled
                if job.is_finished:
                    job.delete()
            run.next_thresholds_job, run.next_indices_job = thresholds_job, indices_job
            run.next_settings = {"options": options, "names": names}
        else:
            run.thresholds_job, run.indices_job = thresholds_job, indices_job
            run.next_thresholds_job = run.next_indices_job = None
            run.next_settings = {}
        run.touch()
        run.save()


@gridded_enabled
@require_POST
def checks(request, run_id):
    """htmx: the summary panel as the set-up form changes (#293), with the parts of the
    form that follow it swapped out of band (the variables' units and checks, the
    Together line, the base period's timeline and coverage, the indices' count, the file
    names and the Computing line)."""
    run = get_run(request, run_id)
    if not request.headers.get("HX-Request"):
        return HttpResponseBadRequest()
    form = setup_form(run, request.POST)
    form.is_valid()
    return render(
        request, "gridded/_summary.html", {**setup_context(request, run, form), "oob": True}
    )


@never_cache
@gridded_enabled
@require_safe
def file_header(request, run_id, number):
    """A file's header as ``ncdump -h`` prints it (#293, the Files table's Header): a page
    of its own, or the text alone (``?format=text``) for the dialog that opens it."""
    run = get_run(request, run_id)
    infos = run.file_infos()
    if not 0 <= number < len(infos) or not infos[number].ok:
        raise Http404
    info = infos[number]
    try:
        text = setup_page.header_text(info.path)
    except OSError as exc:
        raise Http404 from exc
    if request.GET.get("format") == "text":
        return HttpResponse(text, content_type="text/plain; charset=utf-8")
    context = {
        "run": run,
        "run_name": run.display_name,
        "info": info,
        "header": text,
        "setup_url": reverse("gridded:setup", args=[run.pk]),
    }
    return render(request, "gridded/header.html", context)


@gridded_enabled
@require_http_methods(["GET", "HEAD", "POST"])
def delete(request, run_id):
    """Forget this run: GET asks first, POST deletes the run, its results and its uploaded
    files (never a file read in place)."""
    run = get_run(request, run_id)
    if request.method != "POST":
        return render(request, "gridded/delete.html", {"run": run, "run_name": run.display_name})
    run.delete_files()
    run.delete()
    messages.success(
        request,
        _("The gridded run was deleted.")
        if run.source == Source.PATH
        else _("The gridded run and its uploaded files were deleted."),
    )
    return redirect("gridded:start")


@never_cache
@gridded_enabled
@require_http_methods(["GET", "HEAD", "POST"])
def rename(request, run_id):
    """Rename the run: a name of its own, or empty for the one made from its files."""
    run = get_run(request, run_id)
    form = RenameForm(request.POST or None, initial={"name": run.display_name})
    if request.method == "POST" and form.is_valid():
        name = form.cleaned_data["name"].strip()
        run.name = "" if name == runs.default_name(run) else name
        run.touch()
        run.save(update_fields=["name", "updated_at"])
        messages.success(request, _("The run is now called %(name)s.") % {"name": run.display_name})
        return redirect(run)
    context = {**bar_context(run, "rename", heading=False), "form": form}
    return render(request, "gridded/rename.html", context)


# ---- The run's context bar -------------------------------------------------------------------


def bar_context(run: GriddedRun, current: str, heading: bool = True) -> dict:
    """The run's context bar (gridded/_run_bar.html; the GridFiles board): "Gridded / run",
    the name, the provenance line with Rename and Forget this run, the actions, then the
    tabs Map, Files and Set-up."""
    tabs = [
        ("map", _("Map"), reverse("gridded:run", args=[run.pk])),
        ("files", _("Files"), reverse("gridded:files", args=[run.pk])),
        ("setup", _("Set-up"), reverse("gridded:setup", args=[run.pk])),
    ]
    state = runs.state(run)
    done = runs.all_done(run)
    return {
        "run": run,
        "run_name": run.display_name,
        "run_heading": heading,
        "run_breadcrumb": [
            {"label": _("Gridded"), "url": reverse("gridded:start")},
            {"label": _("run")},
        ],
        "run_provenance": runs.provenance(run),
        "run_tabs": [
            {"key": key, "label": label, "url": url, "current": key == current}
            for key, label, url in tabs
        ],
        "run_state": state,
        "run_done": done,
        "run_size": runs.total_size(run) if done else 0,
        "data_page": True,  # base.html: the page uses the whole window
    }


# ---- Map: the jobs and the results ------------------------------------------------------------


def job_rows(request, run: GriddedRun) -> list[dict]:
    now = timezone.now()
    rows = []
    for kind, job in (("thresholds", run.thresholds_job), ("indices", run.indices_job)):
        if job is None:
            continue
        remaining = job.remaining(now)
        rows.append(
            {
                "kind": kind,
                "job": job,
                "stage_label": stage_label(job.stage),
                "elapsed": format_duration(job.elapsed(now)),
                "remaining": format_duration(remaining) if remaining is not None else "",
                "worker_missing": job.status == Status.QUEUED and not worker_running(now),
                "files": len(maps.output_files(job)) if job.status == Status.SUCCEEDED else 0,
            }
        )
    return rows


def progress_context(request, run: GriddedRun) -> dict:
    rows = job_rows(request, run)
    active = [r["job"] for r in rows if not r["job"].is_finished]
    hidden = request.GET.get("hidden") == "true"
    delay = min((poll_delay(j, hidden) for j in active), default=0)
    return {
        "run": run,
        "rows": rows,
        "active": bool(active),
        "delay": delay,
        "all_done": bool(rows) and all(r["job"].status == Status.SUCCEEDED for r in rows),
    }


def explore_context(request, run: GriddedRun) -> dict:
    """The map and the cell's time series, from the query string: ``file`` (an index file
    of the indices job), ``var``, ``t`` (time step), ``scale`` (SPI/SPEI), ``cell``
    (``y,x``)."""
    job = run.indices_job
    if job is None or job.status != Status.SUCCEEDED:
        return {}
    files = [f for f in maps.output_files(job) if f.index]
    if not files:
        return {}
    q = request.GET
    chosen = next((f for f in files if f.path == q.get("file")), None)
    if chosen is None:  # default: the first annual file, txx if there is one
        annual = [f for f in files if f.freq == "ANN"]
        chosen = next((f for f in annual if f.index == "txx"), annual[0] if annual else files[0])
    path = job.output_dir / chosen.path
    try:
        layer = maps.open_layer(path, chosen.path, q.get("var"))
    except (OSError, ValueError, KeyError):
        return {"explore_error": _("This file could not be read."), "explore_files": files}
    scale = _int(q.get("scale"), 0, len(layer.scales) or 1)
    if q.get("t") is None:  # default: the last time step with a value
        t = maps.last_step_with_values(path, layer, scale)
    else:
        t = _int(q.get("t"), len(layer.times) - 1, len(layer.times))
    values = maps.grid_values(path, layer, t, scale)
    ny, nx = values.shape
    cell = _cell(q.get("cell"), ny, nx)
    if cell is None and q.get("cell_y") is not None:
        cell = _cell(f"{q.get('cell_y')},{q.get('cell_x')}", ny, nx)
    if cell is None:  # default: the cell nearest the middle with a value
        import numpy as np

        finite = np.argwhere(np.isfinite(values))
        if finite.size:
            mid = np.array([ny / 2, nx / 2])
            y, x = finite[np.argmin(((finite - mid) ** 2).sum(axis=1))]
            cell = (int(y), int(x))
        else:
            cell = (ny // 2, nx // 2)
    drawing = maps.draw_map(values, layer.lat, layer.lon, cell)
    series_values = maps.cell_series(path, layer, cell[0], cell[1], scale)
    series = maps.draw_series(series_values, layer.times)
    state = {"file": chosen.path, "var": layer.variable, "t": t, "scale": scale}
    base = reverse("gridded:explore", args=[run.pk])
    page = reverse("gridded:run", args=[run.pk])
    for c in drawing.cells:
        query = urlencode({**state, "cell": f"{c.y},{c.x}"})
        c.href = f"{page}?{query}#explore"
        c.hx = f"{base}?{query}"
    lat = layer.lat[cell[0]] if cell[0] < len(layer.lat) else cell[0]
    lon = layer.lon[cell[1]] if cell[1] < len(layer.lon) else cell[1]
    from climpact_web.help.topics import index_topic_for_output

    return {
        "explore_files": files,
        "chosen": chosen,
        "index_topic": index_topic_for_output(f"{chosen.index}_{chosen.freq}"),
        "layer": layer,
        "t": t,
        "time_label": layer.times[t] if layer.times else "",
        "scale": scale,
        "scale_label": layer.scales[scale] if layer.scales else "",
        "map": drawing,
        "cell": cell,
        "cell_label": f"{maps.coord_label(lat, 'N')}, {maps.coord_label(lon, 'E')}",
        "lat_options": [
            {"value": y, "label": maps.coord_label(v, "N")} for y, v in enumerate(layer.lat)
        ],
        "lon_options": [
            {"value": x, "label": maps.coord_label(v, "E")} for x, v in enumerate(layer.lon)
        ],
        "series": series,
        "map_csv": reverse("gridded:map_csv", args=[run.pk]) + "?" + urlencode(state),
        "series_csv": reverse("gridded:series_csv", args=[run.pk])
        + "?"
        + urlencode({**state, "cell": f"{cell[0]},{cell[1]}"}),
        "series_json": reverse("gridded:series_json", args=[run.pk])
        + "?"
        + urlencode({**state, "cell": f"{cell[0]},{cell[1]}"}),
    }


def _int(value, default: int, limit: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return max(default, 0)
    return n if 0 <= n < limit else max(default, 0)


def _cell(value, ny: int, nx: int) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        y, x = (int(v) for v in str(value).split(","))
    except ValueError:
        return None
    return (y, x) if 0 <= y < ny and 0 <= x < nx else None


@never_cache
@gridded_enabled
@require_safe
def run_page(request, run_id):
    """The run's Map tab: the jobs while they run (or why one failed), then the map and a
    cell's series (the explorer, until the map of #295). A run not started yet opens its
    set-up."""
    run = get_run(request, run_id)
    if not run.jobs:
        return redirect("gridded:setup", run_id=run.pk)
    context = progress_context(request, run)
    context.update(explore_context(request, run))
    context.update(bar_context(run, "map"))
    return render(request, "gridded/run.html", context)


@gridded_enabled
@require_safe
def results(request, run_id):
    """The results page's old address: the run, with the explorer's query string."""
    run = get_run(request, run_id)
    query = request.META.get("QUERY_STRING", "")
    return redirect(run.get_absolute_url() + (f"?{query}" if query else ""), permanent=True)


@never_cache
@gridded_enabled
@require_safe
def progress(request, run_id):
    """The jobs' progress and files, polled by htmx while a job runs."""
    run = get_run(request, run_id)
    if not run.jobs:
        raise Http404
    if any(j.status == Status.RUNNING for j in run.jobs):
        from climpact_web.jobs.worker import reap_stale

        if reap_stale():
            run.refresh_from_db()
    context = progress_context(request, run)
    if context["all_done"] and request.GET.get("was_active") == "1":
        # The run has just finished: reload the page so the map appears.
        response = HttpResponse()
        response["HX-Refresh"] = "true"
        return response
    return render(request, "gridded/_progress.html", context)


@never_cache
@gridded_enabled
@require_safe
def explore(request, run_id):
    """htmx: the map and series for the query string."""
    run = get_run(request, run_id)
    context = explore_context(request, run)
    if not context:
        raise Http404
    context["run"] = run
    response = render(request, "gridded/_explore.html", context)
    state = {k: request.GET[k] for k in ("file", "var", "t", "scale") if k in request.GET}
    state["cell"] = f"{context['cell'][0]},{context['cell'][1]}" if "cell" in context else ""
    response["HX-Push-Url"] = run.get_absolute_url() + "?" + urlencode(state) + "#explore"
    return response


def _csv_response(rows: list[list], filename: str) -> HttpResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@gridded_enabled
@require_safe
def map_csv(request, run_id):
    run = get_run(request, run_id)
    context = explore_context(request, run)
    if not context.get("map"):
        raise Http404
    layer, t, scale = context["layer"], context["t"], context["scale"]
    path = run.indices_job.output_dir / context["chosen"].path
    values = maps.grid_values(path, layer, t, scale)
    rows = [["latitude", "longitude", layer.variable]]
    for y, lat in enumerate(layer.lat):
        for x, lon in enumerate(layer.lon):
            rows.append([lat, lon, maps.format_value(float(values[y, x]), 6)])
    suffix = f"_{context['scale_label']}months" if layer.scales else ""
    name = f"{layer.variable}_{context['time_label']}{suffix}.csv"
    return _csv_response(rows, SAFE_NAME.sub("_", name))


@gridded_enabled
@require_safe
def series_csv(request, run_id):
    run = get_run(request, run_id)
    context = explore_context(request, run)
    if not context.get("map"):
        raise Http404
    layer, cell, scale = context["layer"], context["cell"], context["scale"]
    path = run.indices_job.output_dir / context["chosen"].path
    values = maps.cell_series(path, layer, cell[0], cell[1], scale)
    rows = [["time", layer.variable]]
    rows += [
        [label, maps.format_value(float(v), 6)]
        for label, v in zip(layer.times, values, strict=False)
    ]
    lat = layer.lat[cell[0]] if cell[0] < len(layer.lat) else cell[0]
    lon = layer.lon[cell[1]] if cell[1] < len(layer.lon) else cell[1]
    name = f"{layer.variable}_{lat}_{lon}.csv"
    return _csv_response(rows, SAFE_NAME.sub("_", name))


@gzip_page
@gridded_enabled
@require_safe
def series_json(request, run_id):
    """The chosen cell's series for the interactive chart (#75), in the charts app's
    ``index`` format, for the query string of :func:`explore` (no trend: R's gridded
    outputs have none)."""
    from climpact_web.charts import data
    from climpact_web.charts.views import json_response

    run = get_run(request, run_id)
    context = explore_context(request, run)
    if not context.get("map"):
        raise Http404
    layer, cell, scale, chosen = (
        context["layer"],
        context["cell"],
        context["scale"],
        context["chosen"],
    )
    path = run.indices_job.output_dir / chosen.path
    step = {"MON": "month", "DAY": "day"}.get(chosen.freq, "year")

    def build():
        values = maps.cell_series(path, layer, cell[0], cell[1], scale)
        title = _("%(name)s at %(where)s") % {
            "name": layer.variable,
            "where": context["cell_label"],
        }
        payload = data.series_payload(
            layer.variable, title, layer.units, step, layer.times, values, bars=bool(layer.scales)
        )
        payload["csv"] = context["series_csv"]
        return payload

    key = ("gridded", str(run.pk), chosen.path, layer.variable, scale, cell)
    return json_response(request, key, [path], build)


def _zip_response(run: GriddedRun, files: list, suffix: str = "") -> FileResponse:
    """The files in one zip (stored: netCDF is compressed already), built in a temporary
    file."""
    spool = tempfile.TemporaryFile()
    with zipfile.ZipFile(spool, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path, name in files:
            archive.write(path, f"climpact_gridded/{name}")
    spool.seek(0)
    institution = SAFE_NAME.sub("_", run.options.get("institution_id") or "climpact")
    return FileResponse(spool, as_attachment=True, filename=f"{institution}_gridded{suffix}.zip")


@gridded_enabled
@require_safe
def download_all(request, run_id):
    """Every file the run's jobs wrote, in one zip."""
    run = get_run(request, run_id)
    files = [(job.output_dir / f.path, f.name) for job, f in runs.output_files(run)]
    if not files:
        raise Http404
    return _zip_response(run, files)


# ---- Files: the index files and the run's record ----------------------------------------------


def files_context(request, run: GriddedRun) -> dict:
    by = request.GET.get("by")
    if by not in runs.GROUPS:
        by = "theme"
    rows = runs.file_rows(run) if runs.all_done(run) else []
    thresholds = runs.thresholds_file(run)
    copied = next((j.result.get("copied_to") for j in run.jobs if j.result.get("copied_to")), "")
    outputs = runs.output_files(run)
    trends = next((f for _job, f in outputs if f.name == "trends.nc"), None)
    return {
        "by": by,
        "groupings": runs.GROUPINGS,
        "groups": runs.file_groups(run, by, rows),
        "index_count": len(rows),
        "index_size": sum(r.file.size for r in rows),
        "file_count": len(outputs),
        "trends_file": trends,
        "thresholds_path": thresholds,
        "thresholds_size": thresholds.stat().st_size if thresholds and thresholds.exists() else 0,
        "copied_to": copied if not settings.IS_HOSTED else "",
        "thresholds_read": Path(str(run.options.get("thresholds_file") or "")).name,
        "local": not settings.IS_HOSTED,
    }


@never_cache
@gridded_enabled
@require_safe
def files(request, run_id):
    """The run's Files tab (the GridFiles board)."""
    run = get_run(request, run_id)
    if not run.jobs:
        return redirect("gridded:setup", run_id=run.pk)
    context = {**bar_context(run, "files"), **files_context(request, run)}
    return render(request, "gridded/files.html", context)


@gridded_enabled
@require_safe
def download_group(request, run_id, by, group):
    """One group of the Files tab (a theme, a variable or a frequency) in one zip."""
    run = get_run(request, run_id)
    if by not in runs.GROUPS or not runs.all_done(run):
        raise Http404
    found = next((g for g in runs.file_groups(run, by) if g.key == group), None)
    if found is None:
        raise Http404
    job = run.indices_job
    files = [(job.output_dir / r.file.path, r.file.name) for r in found.rows]
    return _zip_response(run, files, f"_{SAFE_NAME.sub('_', group)}")


FILE_LINK_SALT = "climpact_web.gridded.file"


def file_key(run: GriddedRun) -> str:
    """The key in the links for ``wget -i``: it lets a download tool without this
    browser's session fetch the run's files (and nothing else) while the run is kept."""
    return signing.dumps(str(run.pk), salt=FILE_LINK_SALT, compress=True)


def _key_allows(key: str | None, run_id) -> bool:
    if not key:
        return False
    max_age = dt.timedelta(days=settings.JOB_RETENTION_DAYS + 1)
    try:
        return signing.loads(key, salt=FILE_LINK_SALT, max_age=max_age) == str(run_id)
    except signing.BadSignature:
        return False


@gridded_enabled
@require_safe
def run_file(request, run_id, relative):
    """One file a run's job wrote: for this browser's session, or with the key of the
    run's link list (:func:`file_key`)."""
    if _key_allows(request.GET.get("k"), run_id):
        run = get_object_or_404(GriddedRun, pk=run_id)
    else:
        run = get_run(request, run_id)
    for job, f in runs.output_files(run):
        if f.path == relative:
            path = job.output_dir / f.path
            return FileResponse(path.open("rb"), as_attachment=True, filename=f.name)
    raise Http404


@gridded_enabled
@require_safe
def links(request, run_id):
    """Every file of the run as a link, one per line, for ``wget -i`` (big runs: a
    download tool can resume where a zip in the browser cannot)."""
    run = get_run(request, run_id)
    files = runs.output_files(run)
    if not files:
        raise Http404
    key = file_key(run)
    lines = [
        request.build_absolute_uri(reverse("gridded:file", args=[run.pk, f.path]))
        + "?"
        + urlencode({"k": key})
        for _job, f in files
    ]
    response = HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="climpact_gridded_links.txt"'
    return response


@gridded_enabled
@require_safe
def run_record(request, run_id):
    """``run.json``: the settings, versions and the inputs' checksums."""
    run = get_run(request, run_id)
    response = HttpResponse(runs.record_text(run), content_type="application/json")
    response["Content-Disposition"] = 'attachment; filename="run.json"'
    return response


@gridded_enabled
@require_safe
def run_log(request, run_id):
    """``climpact.log``: when each job started and finished, and why one failed."""
    run = get_run(request, run_id)
    if not run.jobs:
        raise Http404
    response = HttpResponse(runs.log_text(run), content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="climpact.log"'
    return response

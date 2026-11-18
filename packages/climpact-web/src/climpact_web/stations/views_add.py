"""Add stations (#233), the one way into a workspace: one file or many, reviewed in one
table (:mod:`.add_stations`), then added and checked.

- ``stations:add`` (``/add/``): starting a workspace. An empty drop zone (the drop zone
  of Get started, ``Start.dc.html``; its other parts are #242's), the file format and the
  settings every station will share; "Use the sample station" adds the Sydney sample and
  opens its Quality at once.
- ``stations:add_to`` (``/w/<id>/add/``): adding stations to a workspace.
- ``stations:add_review`` (``/w/<id>/add/<run>/``): the files dropped, reviewed
  (``AddStations.dc.html``). One form holds the drop zone, the table and the settings,
  so whatever is sent keeps what was typed: more files (``intent=files``), the sample
  (``sample``), the settings (``settings``), Cancel (``cancel``) and "Add N stations and
  check them" (``add``). ``add_check`` checks the table as it is typed (JavaScript) and
  keeps what was typed.

The files wait in a :class:`~climpact_web.batch.models.BatchRun` of the workspace until
they are added (:mod:`.add_stations`). One station is added as a station of its own and
opens on its Quality, checked and calculated with ``station`` jobs; several become the
batch's stations (:mod:`climpact_web.batch.fill`) and the workspace's address shows them,
each with its quality checks queued beside the batch. New station (``/station/new``) and
the batch's first page (``/batch/``) lead here.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from climpact_web.batch import check
from climpact_web.batch.fill import ADDED, JOB_METADATA, JOB_STATIONS, add_stations
from climpact_web.batch.forms import OptionsForm, cpu_count
from climpact_web.batch.models import BatchRun
from climpact_web.core.limits import Refused, disk_required, human_required
from climpact_web.jobs.forms import safe_station_name
from climpact_web.jobs.views import OWNER_KEY, create_job, owner_token
from climpact_web.stations import add_stations as review_module
from climpact_web.stations import calculation, workspace
from climpact_web.stations.models import Source, Station, Step, Workspace
from climpact_web.stations.station_file import decode, inspect_station_bytes

FILE_FIELD = "files"
# Two lines of a station file, for the format note (Start.dc.html).
FILE_SAMPLE = "1936  1  1    0.0   24.3   15.1\n1936  1  2  -99.9   22.8   16.0"


def _owner(request) -> str:
    return request.session.get(OWNER_KEY) or "-"


def get_workspace(request, workspace_id) -> Workspace:
    return get_object_or_404(Workspace, pk=workspace_id, owner=_owner(request))


def get_staged(request, workspace_id, run_id) -> BatchRun:
    """The files waiting to be added, if they are this session's and not yet a batch."""
    owner = _owner(request)
    run = get_object_or_404(
        BatchRun, pk=run_id, workspace_id=workspace_id, owner=owner, workspace__owner=owner
    )
    if run.job_id:
        raise Http404  # added already: a batch now
    return run


def read_uploads(request) -> list[tuple[str, bytes]]:
    return [(f.name, b"".join(f.chunks())) for f in request.FILES.getlist(FILE_FIELD)]


# ---- the settings every station shares -----------------------------------------------------


def settings_rows(space: Workspace) -> list[dict]:
    """The panel "Applies to every station": the base period, the thresholds, the index
    settings and the plots, as the board lists them."""
    from climpact_web.stations.forms import QC_DEFAULTS, QCParamsForm
    from climpact_web.stations.workspace import default_settings, workspace_settings

    chosen = workspace_settings(space)
    defaults = default_settings()
    thresholds = QCParamsForm.initial_for(space.qc_params)
    changed_qc = sum(1 for k in QC_DEFAULTS if thresholds.get(k) != QC_DEFAULTS[k])
    changed_params = sum(1 for k, v in chosen["params"].items() if v != defaults["params"].get(k))

    def changed(count: int, default: str) -> str:
        if not count:
            return default
        return ngettext("%(count)d changed", "%(count)d changed", count) % {"count": count}

    return [
        {
            "label": _("Base period"),
            "value": f"{space.base_start}–{space.base_end}",
            "mono": True,
        },
        {"label": _("Quality thresholds"), "value": changed(changed_qc, _("Defaults"))},
        {"label": _("Index settings"), "value": changed(changed_params, _("ET-SCI defaults"))},
        {
            "label": _("Plots and PDF reports"),
            "value": _("On") if chosen["plots"] else _("Off"),
        },
    ]


def settings_form(space: Workspace, run: BatchRun | None, data=None) -> OptionsForm:
    from climpact_web.stations.workspace import workspace_settings

    initial = {
        "base_start": space.base_start,
        "base_end": space.base_end,
        "plots": workspace_settings(space)["plots"],
        "workers": run.workers if run is not None else default_workers(2),
    }
    form = OptionsForm(data, initial=initial) if data is not None else OptionsForm(initial=initial)
    for field in form.fields.values():
        field.widget.attrs["form"] = "add-form"  # the panel's fields, outside the form
    return form


def default_workers(stations: int) -> int:
    if settings.IS_HOSTED:
        return 1
    return max(1, min(4, cpu_count() - 1, stations))


def settings_editable(space: Workspace) -> bool:
    """The settings change here only before anything is calculated: while the workspace
    has no station. Afterwards a change recalculates every station, from a station's
    Inputs (the workspace's own settings sheet is #234's)."""
    return not space.stations.exists()


def apply_settings(space: Workspace, run: BatchRun | None, form: OptionsForm) -> bool:
    """Keep the settings of a workspace with no station yet. Returns whether they
    changed."""
    from climpact_web.stations.workspace import default_settings, workspace_settings

    data = form.cleaned_data
    chosen = workspace_settings(space)
    before = (space.base_start, space.base_end, chosen["plots"])
    chosen["plots"] = chosen["report"] = bool(data["plots"])
    space.base_start, space.base_end = data["base_start"], data["base_end"]
    space.index_settings = {} if chosen == default_settings() else chosen
    space.touch()
    space.save()
    if run is not None and data.get("workers"):
        run.workers = data["workers"]
        run.save()
    return before != (space.base_start, space.base_end, chosen["plots"])


# ---- the pages ------------------------------------------------------------------------------


def page_context(request, space: Workspace | None, run: BatchRun | None, **extra) -> dict:
    review = review_module.review(run.report, space) if run is not None else None
    editable = space is None or settings_editable(space)
    existing = space is not None and space.stations.exists()
    context = {
        "data_page": run is not None or space is not None,  # the review uses the width
        "space": space if existing else None,
        "run": run,
        "review": review,
        "rows": review.rows if review else [],
        "ready_count": len(review.addable) if review else 0,
        "button_label": review_module.button_label(len(review.addable) if review else 0),
        "summary": review.summary() if review else "",
        "settings_rows": settings_rows(space or Workspace()),
        "settings_form": settings_form(space or Workspace(), run) if editable else None,
        "settings_editable": editable,
        "max_upload_mb": settings.MAX_UPLOAD_MB,
        "accept": check_accept(),
        "sample_file": review_module.SAMPLE_FILE,
        "file_sample": FILE_SAMPLE,
        "action": review_url(run) if run is not None else add_url(space if existing else None),
        "labels": {
            "one": review_module.button_label(1),
            "many": review_module.button_label(2).replace("2", "{n}"),
            "none": review_module.button_label(0),
        },
    }
    context.update(extra)
    return context


def check_accept() -> str:
    from climpact_web.batch.forms import ACCEPT_FILES

    return ACCEPT_FILES


def add_url(space: Workspace | None) -> str:
    if space is None:
        return reverse("stations:add")
    return reverse("stations:add_to", args=[space.pk])


def review_url(run: BatchRun) -> str:
    return reverse("stations:add_review", args=[run.workspace_id, run.pk])


def stage(request, space: Workspace | None, uploads, sample: bool = False) -> BatchRun:
    """A new set of files waiting to be added to ``space`` (a new workspace when None)."""
    with transaction.atomic():
        if space is None:
            space = Workspace.objects.create(owner=owner_token(request))
        run = BatchRun(workspace=space, owner=owner_token(request))
        run.workers = default_workers(2)
        run.save()
    take(run, uploads, sample=sample)
    return run


def take(run: BatchRun, uploads, sample: bool = False) -> None:
    """Add uploaded files (or the sample) to those waiting, read once."""
    if sample:
        from climpact_web.stations.views import sample_bytes

        uploads = [(review_module.SAMPLE_FILE, sample_bytes())]
    report, files, metadata = review_module.read_files(run.report, uploads)
    if sample:
        report["sample"] = True
    run.save_files(files)
    if metadata is not None:
        run.metadata_name = metadata[0][:255]
        run.save_metadata(metadata[1])
    run.report = report
    run.touch()
    run.save()


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def start(request):
    """``/add/``: start a workspace with files."""
    if request.method == "POST":
        uploads = read_uploads(request)
        if uploads:
            run = stage(request, None, uploads)
            return redirect(review_url(run))
        context = start_context(request, upload_error=_("Choose the station files."))
        return render(request, "stations/add.html", context, status=400)
    return render(request, "stations/add.html", start_context(request))


# Get started's "Or continue a workspace": the workspaces changed last (the Start board).
RECENT = 3


def start_context(request, **extra) -> dict:
    """``/add/`` before any file: Get started, with the workspaces changed last for a
    returning visitor."""
    from climpact_web.stations import workspace_list

    context = page_context(request, None, None, **extra)
    context["recent"] = workspace_list.entries(_owner(request), limit=RECENT)
    return context


@require_http_methods(["GET", "HEAD", "POST"])
@disk_required
def sample(request):
    """ "Use the sample station" on an empty Add stations: the Sydney sample with its
    details, added to a new workspace and checked at once; its Quality opens. The landing
    page's "See an example" (``show=indices``, #242) opens its Indices instead: the run
    is the user's at once, as "Go to indices" would make it, and the Indices show its
    progress until it has finished."""
    if request.method != "POST":
        return redirect("stations:add")
    from climpact_web.stations.views import SAMPLE_NAME as FILE
    from climpact_web.stations.views import sample_bytes

    inspection = inspect_station_bytes(sample_bytes())
    lat, lon = review_module.SAMPLE_COORDINATES
    with transaction.atomic():
        station = Station(
            owner=owner_token(request),
            source=Source.SAMPLE,
            station_name=review_module.SAMPLE_NAME,
            latitude=lat,
            longitude=lon,
        )
        _keep_file(station, inspection, FILE)
        station.advance_to(Step.QC)
        station.save()
        calculation.bring_up_to_date(request, station)
        if request.POST.get("show") == "indices":
            try:
                calculation.commit(request, station)
            except Refused:
                pass  # the Indices then offer to calculate it
            station.advance_to(Step.RESULTS)
            station.touch()
            station.save()
            return redirect(station.url("results"))
    return redirect(station.url("qc"))


@require_http_methods(["GET", "HEAD", "POST"])
@disk_required
def sample_batch(request):
    """The sample batch (the help's "Use the sample batch"): Climpact for R's, two copies of
    the Sydney file and their metadata file, waiting on Add stations to be reviewed."""
    if request.method != "POST":
        return redirect("stations:add")
    from climpact_web.batch.views import SAMPLE_METADATA, sample_files, sample_metadata

    uploads = [(SAMPLE_METADATA, sample_metadata()), *sample_files().items()]
    run = stage(request, None, uploads)
    return redirect(review_url(run))


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def add_to(request, workspace_id):
    """``/w/<id>/add/``: add stations to a workspace."""
    space = get_workspace(request, workspace_id)
    if request.method == "POST":
        sample = request.POST.get("intent") == "sample"
        uploads = read_uploads(request)
        if uploads or sample:
            run = stage(request, space, uploads, sample=sample)
            return redirect(review_url(run))
        context = page_context(request, space, None, upload_error=_("Choose the station files."))
        return render(request, "stations/add.html", context, status=400)
    return render(request, "stations/add.html", page_context(request, space, None))


def typed(request, run: BatchRun) -> dict:
    """What was typed in the table, by file (``file-<i>``, ``name-<i>``, ``lat-<i>``,
    ``lon-<i>``), kept in the report: the review starts from it next time."""
    edits = dict(run.report.get("edits") or {})
    files = run.report.get("files") or {}
    for key, value in request.POST.items():
        match = re.fullmatch(r"file-(\d+)", key)
        if not match or value not in files:
            continue
        i = match[1]
        entry = dict(edits.get(value) or {})
        for field, name in (("name", "name"), ("latitude", "lat"), ("longitude", "lon")):
            if f"{name}-{i}" in request.POST:
                entry[field] = request.POST[f"{name}-{i}"].strip()[:100]
        edits[value] = entry
    return edits


def keep_typed(request, run: BatchRun) -> None:
    report = dict(run.report)
    report["edits"] = typed(request, run)
    run.report = report
    run.touch()
    run.save()


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def review_page(request, workspace_id, run_id):
    """The review table, and what its form sends."""
    run = get_staged(request, workspace_id, run_id)
    space = run.workspace
    if request.method != "POST":
        return render(request, "stations/add.html", page_context(request, space, run))
    intent = request.POST.get("intent", "add")
    if intent == "cancel":
        return cancel(request, run)
    keep_typed(request, run)
    form = None
    if settings_editable(space) and "base_start" in request.POST:
        form = settings_form(space, run, request.POST)
        if form.is_valid():
            if apply_settings(space, run, form):
                messages.success(request, _("The settings are changed for every station."))
        elif intent in ("settings", "add"):
            context = page_context(request, space, run, settings_form=form, settings_open=True)
            return render(request, "stations/add.html", context, status=400)
    if intent in ("files", "sample"):
        uploads = read_uploads(request)
        if uploads or intent == "sample":
            take(run, uploads, sample=intent == "sample")
        return redirect(review_url(run))
    if intent == "settings":
        return redirect(review_url(run))
    review = review_module.review(run.report, space)
    rows = review.addable
    if not rows:
        context = page_context(
            request,
            space,
            run,
            add_error=_("Nothing can be added yet. Fix the problems in the table first."),
        )
        return render(request, "stations/add.html", context, status=400)
    if len(rows) == 1:
        station = add_one(request, run, rows[0])
        if space.stations.count() == 1:
            return redirect(station.url("qc"))
        messages.success(request, _("%(name)s was added and is being checked.") % {"name": station})
        return redirect(space.get_absolute_url())
    add_many(request, run, rows)
    return redirect(space.get_absolute_url())


@require_POST
def add_check(request, workspace_id, run_id):
    """The table checked as it is typed (JavaScript): what was typed is kept, and each
    row's state, the line under the table and the button's label come back as JSON."""
    run = get_staged(request, workspace_id, run_id)
    keep_typed(request, run)
    review = review_module.review(run.report, run.workspace)
    return JsonResponse(
        {
            "rows": [
                {
                    "file": r.file,
                    "state": r.state,
                    "status": r.status,
                    "status_kind": r.status_kind,
                    "name_error": r.name_error,
                    "latitude_error": r.latitude_error,
                    "longitude_error": r.longitude_error,
                }
                for r in review.rows
            ],
            "count": len(review.addable),
            "button": review_module.button_label(len(review.addable)),
            "summary": review.summary(),
        }
    )


def cancel(request, run: BatchRun):
    """Cancel: the files waiting are deleted, with a workspace that holds nothing else."""
    space = run.workspace
    existing = space.stations.exists()
    run.delete_files()
    run.delete()
    if existing:
        return redirect(space.get_absolute_url())
    return redirect("stations:add")


# ---- adding ---------------------------------------------------------------------------------


def _keep_file(station: Station, inspection, file_name: str) -> None:
    station.file_name = file_name[:255]
    station.summary = inspection.summary
    station.warnings = inspection.warnings
    station.save_station_text(inspection.text)


def add_one(request, run: BatchRun, row) -> Station:
    """One station: a station of the workspace, checked and calculated with its own jobs
    (Quality opens), as New station did (#201). The waiting files go."""
    space = run.workspace
    inspection = inspect_station_bytes((run.files_dir / row.file).read_bytes())
    sample = row.file == review_module.SAMPLE_FILE and run.report.get("sample")
    with transaction.atomic():
        station = Station(
            workspace=space,
            owner=run.owner,
            source=Source.SAMPLE if sample else Source.UPLOAD,
            station_name=row.values["station_name"],
            latitude=row.values["latitude"],
            longitude=row.values["longitude"],
        )
        if row.params:
            station.origin = {"params": row.params}  # the metadata line's own values
        _keep_file(station, inspection, row.file)
        station.advance_to(Step.QC)
        several = space.stations.exists()
        if several:
            # A workspace of several stations has chosen to calculate (#277): the run is
            # the user's own at once, as a batch's stations are, not speculative.
            station.advance_to(Step.INDICES)
        station.save()
        run.delete_files()
        run.delete()
    calculation.bring_up_to_date(request, station)
    if several:
        calculation.commit_workspace(request, space)  # the first station, if not yet
    return station


def batch_names(rows) -> dict[str, str]:
    """Each file's name in the batch: its stem, as Climpact for R names a batch's stations
    and their folders, made safe (letters, digits and ``.()-_``, no spaces, as the metadata
    file separates its columns with them) and unique."""
    from climpact.batch import strip_file_extension

    names, taken = {}, set()
    for row in rows:
        base = safe_station_name(strip_file_extension(row.file)).replace(" ", "_")
        name, n = base, 1
        while name.casefold() in taken:
            n += 1
            name = f"{base}_{n}"
        taken.add(name.casefold())
        names[row.file] = name
    return names


def add_many(request, run: BatchRun, rows) -> str:
    """Several stations: one batch job runs them (the workspace's base period, custom index
    and plots), each a station of the workspace from now on (``batch.fill``), and each
    station's quality checks are queued beside it, as one change for the hosted limits.
    Returns the change's id (opening a workspace file adds to it, ``workspace_file``)."""
    from climpact_web.batch.views import set_base_period
    from climpact_web.stations.workspace import workspace_settings

    space = run.workspace
    chosen = workspace_settings(space)
    shared = {k: chosen["params"][k] for k in check.PARAM_FIELDS.values()}
    names = batch_names(rows)
    stations = []
    for i, row in enumerate(rows, start=1):
        summary = (run.report["files"][row.file].get("summary")) or None
        stations.append(
            {
                "name": names[row.file],
                "station_file": row.file,
                "job_file": f"{names[row.file]}.txt",
                "station_name": row.values["station_name"],
                "line": i,
                "latitude": row.values["latitude"],
                "longitude": row.values["longitude"],
                "params": {**shared, **row.params},
                "own_params": row.params,
                "status": "ready",
                "problems": [],
                "problem_count": 0,
                "warnings": row.warnings,
                "summary": summary,
            }
        )
    report = dict(run.report)
    report["stations"] = stations
    run.report = report
    run.plots = bool(chosen["plots"])
    set_base_period(run, space.base_start, space.base_end)
    metadata = check.metadata_text([{**s, "station_file": s["job_file"]} for s in stations])
    files = {JOB_METADATA: ContentFile(metadata.encode("utf-8"))}
    for s in stations:
        text = decode((run.files_dir / s["station_file"]).read_bytes())
        files[f"{JOB_STATIONS}/{s['job_file']}"] = ContentFile(text.encode("utf-8"))
    change = calculation.new_change()
    params = {
        "metadata_file": JOB_METADATA,
        "data_dir": JOB_STATIONS,
        "base_start": space.base_start,
        "base_end": space.base_end,
        "custom": chosen["params"]["custom"],
        "workers": run.workers,
        "plots": run.plots,
        "zip": True,
        "station_zips": True,
        "report": run.plots,
        "folder": run.folder_name,
        "skipped": [],
        "names": {s["name"]: s["station_name"] for s in stations},
        ADDED: True,
    }
    title = ngettext(
        "Add stations: %(name)s (%(count)d station)",
        "Add stations: %(name)s (%(count)d stations)",
        len(stations),
    ) % {"name": space.display_name, "count": len(stations)}
    job = create_job(request, "batch", params, files, title=title, change=change)
    run.job = job
    run.touch()
    run.save()
    add_stations(run, job, [])
    for station in Station.objects.filter(workspace=space, origin__batch=str(run.pk)):
        if workspace.set_up(station):
            calculation.queue_qc(request, station, change)
    calculation.commit_workspace(request, space)  # a station there before, if not yet (#277)
    return change

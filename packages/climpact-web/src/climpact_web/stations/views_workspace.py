"""The workspace's own pages (#234): its overview at ``/w/<id>/``, the overview's
progress fragment, Compare an index (#238), Rename, Workspace settings and Undo.

A workspace of one station opens that station straight away (the Flow board: no
overview); one of two or more opens its overview (:mod:`.overview`), which replaced the
batch results page. Workspace settings are the base period, the quality thresholds and the
index settings every station shares (#254): each is edited on its own page here (the
Inputs panel's sheets as pages), and a change recalculates every station, with Undo on the
overview's run status line until it has finished.
"""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.utils.translation import ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from climpact_web.core.limits import human_required
from climpact_web.jobs.views import OWNER_KEY, poll_delay
from climpact_web.stations import calculation, overview, trend_grid, workspace, workspace_files
from climpact_web.stations.forms import BasePeriodForm, QCParamsForm
from climpact_web.stations.forms_indices import IndexParamsForm, initial_from_params
from climpact_web.stations.models import Workspace

HIDDEN_POLL_SECONDS = 30


def get_workspace(request, workspace_id) -> Workspace:
    """The workspace ``workspace_id``, if it is this session's; 404 otherwise (the page
    then says workspaces are deleted after a while, 404.html, without saying whether
    another session's exists)."""
    owner = request.session.get(OWNER_KEY) or "-"
    return get_object_or_404(Workspace, pk=workspace_id, owner=owner)


def _owner(request) -> str:
    return request.session.get(OWNER_KEY) or "-"


def _ran(space: Workspace, owner: str):
    """The workspace's batch that ran (files waiting on Add stations, #233, are a batch
    with no job), or None."""
    from climpact_web.batch.models import BatchRun

    return BatchRun.objects.filter(workspace=space, owner=owner).exclude(job=None).first()


# ---- the context bar ---------------------------------------------------------------------


class Tab:
    """One of the workspace's tabs: Overview, Compare an index (#238) and Files (#239)."""

    def __init__(self, key, label, url, current=False):
        self.key, self.label, self.url, self.current = key, label, url, current


def settings_text(space: Workspace) -> str:
    """ "ET-SCI defaults", or how many settings of the workspace are not the default."""
    custom = workspace.thresholds_count(
        QCParamsForm.initial_for(space.qc_params)
    ) + workspace.settings_count(workspace.workspace_settings(space))
    if not custom:
        return _("ET-SCI defaults")
    return ngettext(
        "%(count)s setting not the default", "%(count)s settings not the default", custom
    ) % {"count": custom}


def bar_context(request, space: Workspace, current: str = "overview") -> dict:
    """The workspace's context bar (the Workspace board): "Workspace", its name as the
    h1, the provenance line (stations, base period, settings, version, deletion date) with
    Workspace settings and Rename, Add stations, and the tabs."""
    from django.utils import timezone
    from django.utils.formats import date_format

    count = space.stations.filter(owner=_owner(request)).count()
    parts = [
        ngettext("%(count)s station", "%(count)s stations", count) % {"count": count},
        _("base %(start)s–%(end)s") % {"start": space.base_start, "end": space.base_end},
        settings_text(space),
    ]
    if found := workspace.core_version():
        parts.append(f"climpact {found}")
    if space.expires_at:
        when = date_format(timezone.localtime(space.expires_at), "j M Y")
        parts.append(_("kept until %(date)s") % {"date": when})
    return {
        "space": space,
        "space_name": space.display_name,
        "space_provenance": [{"text": p, "phone": i == 0} for i, p in enumerate(parts)],
        "space_tabs": [
            Tab(
                "overview",
                _("Overview"),
                reverse("stations:workspace", args=[space.pk]),
                current == "overview",
            ),
            Tab(
                "compare",
                _("Compare an index"),
                reverse("stations:workspace_compare", args=[space.pk]),
                current == "compare",
            ),
            Tab(
                "files",
                _("Files"),
                reverse("stations:workspace_files", args=[space.pk]),
                current == "files",
            ),
        ],
        "space_current": current,
        "data_page": True,
    }


# ---- trends across stations ----------------------------------------------------------------


def chosen_columns(request, space: Workspace) -> list[str] | None:
    """The indices the user chose for the trend grid: ``?cols=`` (remembered for the
    workspace in the session), else the ones chosen before, else None (the defaults).
    ``?cols=default`` forgets the choice."""
    key = trend_grid.SESSION_KEY.format(space.pk)
    wanted = [c for c in request.GET.getlist("cols") if c]
    if wanted == ["default"]:
        request.session.pop(key, None)
        return None
    if wanted:
        request.session[key] = wanted[:200]
        return wanted
    return request.session.get(key)


def trends_context(request, space: Workspace, table: list, page: str) -> dict:
    """The trend grid and the selected column's interval plot (the Workspace board's
    "Trends across stations"); none while a station is still being calculated."""
    if any(r.indices.state in overview.RUNNING for r in table):
        return {"trends": None, "trends_waiting": True}
    items = workspace_files.entries(space, _owner(request), table)
    found = trend_grid.grid(items, chosen_columns(request, space), request.GET.get("index"))
    csv_url = reverse("stations:workspace_compare_csv", args=[space.pk])
    query = "&".join(f"cols={c.code}" for c in found.columns)
    for plot in found.plots:
        plot.csv_url = f"{csv_url}?cols={plot.choice.code}"
    return {
        "trends": found,
        "trends_page": page,
        "trends_csv": f"{csv_url}?{query}",
        "trends_waiting": False,
    }


# ---- the overview ------------------------------------------------------------------------


def overview_context(request, space: Workspace) -> dict:
    owner = _owner(request)
    run = _ran(space, owner)
    page = reverse("stations:workspace", args=[space.pk])
    table = overview.rows(space, owner)
    active = overview.active(table)
    delay = 2
    if run is not None and run.job is not None and not run.job.is_finished:
        delay = poll_delay(run.job, request.GET.get("hidden") == "true")
    elif request.GET.get("hidden") == "true":
        delay = HIDDEN_POLL_SECONDS
    return {
        "space": space,
        "rows": table,
        "status": overview.status_line(space, table, run, page),
        # Export ▾ (#239): the workspace files, once every station has finished.
        "space_export": not any(r.indices.state in overview.RUNNING for r in table)
        and any(r.indices.state == overview.DONE for r in table),
        "polling": active,
        "delay": delay,
        "page": page,
        **trends_context(request, space, table, page),
    }


@never_cache
@require_safe
def workspace_page(request, workspace_id):
    """``/w/<id>/`` (#256). A workspace of one station opens it straight away (the Flow
    board: no overview), at its furthest section: Quality while it waits, Indices once
    calculated or failed (which say why), the New station page when the batch had no file
    for it. A workspace of two or more opens its overview (#234), after recording how a
    finished batch went (``batch.fill``). Without stations: files waiting on Add stations
    (#233) open their review; a batch the old batch page checked and never ran (its page
    went with #271), Add stations."""
    from climpact_web.batch.fill import fill_workspace
    from climpact_web.batch.models import BatchRun

    owner = _owner(request)
    space = get_workspace(request, workspace_id)
    run = _ran(space, owner)
    if run is not None:
        fill_workspace(run)
    stations = list(space.stations.filter(owner=owner)[:2])
    if len(stations) == 1:
        return redirect(workspace.home_url(stations[0]))
    if stations:
        context = {**bar_context(request, space), **overview_context(request, space)}
        return render(request, "stations/workspace.html", context)
    waiting = BatchRun.objects.filter(workspace=space, owner=owner, job=None).first()
    if waiting is None:
        raise Http404
    if waiting.report.get("files") is not None:  # files waiting on Add stations
        return redirect("stations:add_review", space.pk, waiting.pk)
    return redirect("stations:add")


@never_cache
@require_safe
def workspace_progress(request, workspace_id):
    """The run status line and the Stations table, polled by htmx while stations are
    checked or calculated (``stations/_overview.html``)."""
    from climpact_web.batch.fill import fill_workspace

    space = get_workspace(request, workspace_id)
    run = _ran(space, _owner(request))
    if run is not None:
        if run.job is not None and run.job.status == "running":
            from climpact_web.jobs.worker import reap_stale

            if reap_stale():
                run.job.refresh_from_db()
        fill_workspace(run)
    if space.stations.filter(owner=_owner(request)).count() < 2:
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"
        return response
    return render(request, "stations/_overview.html", overview_context(request, space))


# ---- Compare an index ----------------------------------------------------------------------


@never_cache
@require_safe
def compare_page(request, workspace_id):
    """Compare an index (#238): the trend grid and the selected index's interval plot on a
    page of their own, the overview's "Trends across stations" without the Stations table.
    A workspace of one station has nothing to compare: its Indices."""
    from climpact_web.stations.views_files import items_of

    space = get_workspace(request, workspace_id)
    items = items_of(request, space)
    if len(items) == 1:
        return redirect(items[0].station.url("results"))
    if not items:
        raise Http404
    page = reverse("stations:workspace_compare", args=[space.pk])
    table = [e.row for e in items]
    context = {
        **bar_context(request, space, "compare"),
        **trends_context(request, space, table, page),
        "space": space,
        # Export ▾ (#239), as on the overview: once every station has finished.
        "space_export": not workspace_files.busy(items)
        and any(e.source is not None for e in items),
    }
    return render(request, "stations/workspace_compare.html", context)


@never_cache
@require_safe
def compare_csv(request, workspace_id):
    """The trend grid as CSV (``?cols=`` the grid's indices, in its order; one for the
    interval plot's "CSV, all stations"): the rows of the workspace's Trends file
    (``workspace_files.trends_csv``) for those indices."""
    from climpact_web.stations.views_files import items_of

    space = get_workspace(request, workspace_id)
    items = items_of(request, space)
    codes = [c for c in request.GET.getlist("cols") if c][:200]
    if not codes:
        codes = [c.code for c in trend_grid.grid(items, None, None).columns]
    response = HttpResponse(
        trend_grid.grid_csv(items, codes), content_type="text/csv; charset=utf-8"
    )
    base = workspace_files.download_name(space, "trends").removesuffix("_trends.csv")
    code = workspace_files._UNSAFE.sub("_", codes[0])
    name = f"{base}_{code}_trend.csv" if len(codes) == 1 else f"{base}_trend_grid.csv"
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


# ---- Rename ------------------------------------------------------------------------------


class RenameForm(forms.Form):
    name = forms.CharField(
        label=_lazy("Workspace name"),
        max_length=100,
        required=False,
        help_text=_lazy("Leave it empty for the default name."),
    )


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def rename(request, workspace_id):
    """Rename the workspace (the Flow board: "Rename in the header at any time"). An empty
    name gives back the default ("6 stations, 17 Nov", or the station's name)."""
    space = get_workspace(request, workspace_id)
    if request.method == "POST":
        form = RenameForm(request.POST)
        if form.is_valid():
            space.name = form.cleaned_data["name"].strip()
            space.touch()
            space.save(update_fields=["name", "updated_at"])
            messages.success(
                request, _("The workspace is now called %(name)s.") % {"name": space.display_name}
            )
            return redirect(space.get_absolute_url())
    else:
        form = RenameForm(initial={"name": space.name or space.display_name})
    context = {**bar_context(request, space, current=""), "form": form}
    return render(request, "stations/workspace_rename.html", context)


# ---- Workspace settings ------------------------------------------------------------------

SETTINGS = workspace.WORKSPACE_SHEETS  # base-period, thresholds, settings


def _anchor(request, space: Workspace):
    """A station of the workspace for what the settings' forms need of one (their htmx
    checks, the change's record): the first one added. A change applies to them all."""
    station = overview.ordered(space, _owner(request)).first()
    if station is None:
        raise Http404
    return station


def setting_form(space: Workspace, key: str, data=None):
    if key == "base-period":
        values = {"base_start": space.base_start, "base_end": space.base_end}
        return BasePeriodForm(data if data is not None else values)
    if key == "thresholds":
        if data is not None:
            return QCParamsForm(data)
        return QCParamsForm(initial=QCParamsForm.initial_for(space.qc_params))
    if data is not None:
        return IndexParamsForm(data)
    chosen = workspace.workspace_settings(space)
    values = initial_from_params(
        chosen["params"], chosen["plot_title"], chosen["plots"], chosen["zip"], chosen["report"]
    )
    return IndexParamsForm(initial=values)


def settings_items(space: Workspace) -> list[workspace.PanelInput]:
    labels = {key: str(label) for key, label, _names in workspace.PANEL_INPUTS}
    values = {
        "base-period": workspace.base_period_text(space),
        "thresholds": workspace.changed_text(
            workspace.thresholds_count(QCParamsForm.initial_for(space.qc_params))
        ),
        "settings": workspace.changed_text(
            workspace.settings_count(workspace.workspace_settings(space))
        ),
    }
    return [
        workspace.PanelInput(
            key=key,
            label=labels[key],
            value=values[key],
            edit_url=reverse("stations:workspace_setting", args=[space.pk, key]),
            edit_label=_("Edit"),
            changed=False,
        )
        for key in SETTINGS
    ]


@never_cache
@require_safe
def settings_page(request, workspace_id):
    """Workspace settings: the base period, the quality thresholds and the index settings
    every station shares, each with Edit."""
    space = get_workspace(request, workspace_id)
    _anchor(request, space)
    context = {
        **bar_context(request, space, current=""),
        "inputs": settings_items(space),
        "can_undo": workspace.undo_available(space),
    }
    return render(request, "stations/workspace_settings.html", context)


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def setting(request, workspace_id, key):
    """One of the workspace's settings on its own page (the Inputs panel's sheet, #198):
    applying changes it for every station (``calculation.change_settings``: one change,
    which can be undone while its recalculation is on the way), then back to the
    overview."""
    from climpact_web.stations.views import INPUT_SHEETS

    space = get_workspace(request, workspace_id)
    if key not in SETTINGS:
        raise Http404
    anchor = _anchor(request, space)
    form = None
    if request.method == "POST":
        form = setting_form(space, key, request.POST)
        if form.is_valid():
            data = form.cleaned_data
            if key == "base-period":
                changed = calculation.change_settings(
                    request, anchor, base_start=data["base_start"], base_end=data["base_end"]
                )
            elif key == "thresholds":
                values = {k: data[k] for k in QCParamsForm.base_fields}
                changed = calculation.change_settings(request, anchor, qc_params=values)
            else:
                chosen = workspace.settings_of(
                    {
                        "params": form.job_params(),
                        "plot_title": data["plot_title"],
                        "plots": data["plots"],
                        "zip": data["zip"],
                        "report": data["report"],
                    }
                )
                index_settings = {} if chosen == workspace.default_settings() else chosen
                changed = calculation.change_settings(
                    request, anchor, index_settings=index_settings
                )
            if changed:
                messages.success(
                    request, _("The settings are changed. Every station is being recalculated.")
                )
            return redirect(space.get_absolute_url())
    title, intro = INPUT_SHEETS[key]
    impact = workspace.impact(key, anchor)
    context = {
        **bar_context(request, space, current=""),
        "analysis": anchor,
        "sheet": {
            "key": key,
            "title": title,
            "intro": intro,
            "form": form if form is not None else setting_form(space, key),
            "impact": impact,
            "settings_source": "workspace" if space.index_settings else "default",
        },
        "action": reverse("stations:workspace_setting", args=[space.pk, key]),
        "next": reverse("stations:workspace_settings", args=[space.pk]),
        "workspace_level": True,
    }
    return render(request, "stations/workspace_setting.html", context)


@require_POST
def undo(request, workspace_id):
    """ "Undo the change" on the overview's run status line (#254, #234): as a station's
    (``stations.views.undo``), then back to the overview."""
    space = get_workspace(request, workspace_id)
    if calculation.undo(space):
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
    return redirect(space.get_absolute_url())


# ---- Workspaces (#242) -------------------------------------------------------------------


@never_cache
@require_safe
def workspaces_page(request):
    """``/w/``: every workspace of this browser (hosted) or computer (local), which
    replaced "Your calculations" (the WorkspaceList board)."""
    from climpact_web.stations import workspace_list

    owner = _owner(request)
    return render(
        request,
        "stations/workspaces.html",
        {
            "entries": workspace_list.entries(owner),
            "gridded_runs": _gridded_runs(owner),
        },
    )


def _gridded_runs(owner: str) -> bool:
    """Whether the session has gridded runs, which Gridded lists (#289; gridded runs are
    not workspaces)."""
    from django.conf import settings

    if not settings.GRIDDED_ENABLED:
        return False
    from climpact_web.gridded.models import GriddedRun

    return GriddedRun.objects.filter(owner=owner).exists()


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def delete_workspace(request, workspace_id):
    """Delete a workspace now, with its stations, files and results (the WorkspaceList
    board's Delete; #274 shares it on the workspace's Files): a page that names the
    stations and says the files can't be recovered, then the POST. Calculations still
    queued or running for it are cancelled first."""
    from climpact_web.jobs.models import Job

    owner = _owner(request)
    space = get_workspace(request, workspace_id)
    stations = list(overview.ordered(space, owner))
    if request.method == "POST":
        name = space.display_name
        jobs = [
            pk
            for s in stations
            for pk in (s.qc_job_id, s.indices_job_id, s.sector_job_id)
            if pk is not None
        ]
        jobs += [pk for pk in space.batches.values_list("job_id", flat=True) if pk is not None]
        for job in Job.objects.filter(pk__in=jobs, owner=owner):
            if job.can_cancel:
                job.request_cancel()
        space.delete_files()
        Workspace.objects.filter(pk=space.pk).delete()
        messages.success(request, _("%(name)s was deleted.") % {"name": name})
        return redirect("stations:workspaces")
    # Cancel goes back where Delete was chosen: the workspace's Files (#274), or Workspaces.
    back = "stations:workspace_files" if request.GET.get("from") == "files" else None
    return render(
        request,
        "stations/workspace_delete.html",
        {
            "space": space,
            "space_name": space.display_name,
            "station_names": [str(s) for s in stations],
            "back_url": reverse(back, args=[space.pk]) if back else reverse("stations:workspaces"),
        },
    )


@require_POST
def keep(request, workspace_id):
    """ "Keep 7 more days" on the workspace's Files (#274): where workspaces expire, counts
    the workspace as changed now (``Workspace.touch``), so it is deleted
    ``JOB_RETENTION_DAYS`` from now; then back to Files, with the new date."""
    from django.utils import timezone
    from django.utils.formats import date_format

    space = get_workspace(request, workspace_id)
    if not space.expires_at:  # a local install: workspaces stay until deleted
        raise Http404
    space.touch()
    space.save(update_fields=["updated_at"])
    when = date_format(timezone.localtime(space.expires_at), "j M Y")
    messages.success(
        request,
        _("%(name)s is now kept until %(date)s.") % {"name": space.display_name, "date": when},
    )
    return redirect("stations:workspace_files", space.pk)

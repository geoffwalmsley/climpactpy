"""The workspace's Files tab (#239, the Files board): ``/w/<id>/files/``, and its downloads.

The page has the workspace files (Everything, Trends and Indices of all stations), each
station's R files in one table, the provenance file with "Copy methods text", and how long
the files are kept. The files are made from the results the stations show
(:mod:`.workspace_files`) when the page or a download first asks for them. A workspace of
one station has no Files of its own: its station's Files are the place.
"""

from __future__ import annotations

from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from climpact_web.stations import workspace_files as model
from climpact_web.stations.downloads import zip_path
from climpact_web.stations.views import get_analysis
from climpact_web.stations.views_indices import current_source
from climpact_web.stations.views_workspace import _owner, bar_context, get_workspace


def items_of(request, space) -> list[model.Entry]:
    """The workspace's stations for Files, after recording how a finished batch went
    (``batch.fill``, as the overview does)."""
    from climpact_web.batch.fill import fill_workspace
    from climpact_web.stations.views_workspace import _ran

    owner = _owner(request)
    run = _ran(space, owner)
    if run is not None:
        fill_workspace(run)
    return model.entries(space, owner)


def labels() -> dict:
    return {
        "folder": _("Folder (zip)"),
        "report": _("Report (PDF)"),
        "all_plots": _("All plots (PDF)"),
        "trends": _("Trends"),
        "thresholds": _("Thresholds"),
        "missing": _("Missing values"),
        "quality": _("Quality flags"),
    }


@never_cache
@require_safe
def files_page(request, workspace_id):
    space = get_workspace(request, workspace_id)
    items = items_of(request, space)
    if len(items) == 1:  # a workspace of one station: its Files
        return redirect(items[0].station.url("downloads"))
    built = model.build(space, items)
    names = labels()
    context = {
        **bar_context(request, space, "files"),
        "items": items,
        "built": built,
        "space_export": built is not None,
        "busy": model.busy(items),
        "has_results": any(e.source is not None for e in items),
        "out_of_date": any(e.out_of_date for e in items),
        "columns": [names[k] for k in model.COLUMNS],
        "rows": model.table(items, built, names),
        "trends_columns": ", ".join(
            (*model.TRENDS_COLUMNS, model.TRENDS_UNITS, model.TRENDS_OUT_OF_DATE)
        ),
        "indices_columns": ", ".join(model.INDICES_COLUMNS),
    }
    if built is not None:
        context |= {
            "provenance_text": model.provenance_text(built.provenance),
            "methods_text": model.methods_text(built.provenance),
            "everything_size": built.everything.stat().st_size,
            "trends_size": built.trends.stat().st_size,
            "indices_size": built.indices.stat().st_size,
        }
    return render(request, "stations/workspace_files.html", context)


@never_cache
@require_safe
def download(request, workspace_id, what):
    """Everything (``everything.zip``), or the Trends or Indices of all stations. While a
    station is still being calculated, Files, which says so."""
    space = get_workspace(request, workspace_id)
    built = model.build(space, items_of(request, space))
    if built is None:
        return redirect("stations:workspace_files", space.pk)
    path = {"everything": built.everything, "trends": built.trends, "indices": built.indices}
    return FileResponse(
        path[what].open("rb"),
        as_attachment=True,
        filename=model.download_name(space, what),
    )


@never_cache
@require_safe
def station_zip(request, workspace_id, slug):
    """A station's folder as a zip with its provenance file: R's station zip and
    ``climpact_run.json``. While another station of the workspace is still being
    calculated, R's zip as the run wrote it."""
    analysis = get_analysis(request, workspace_id, slug)
    job, source = current_source(analysis)
    if source is None:
        raise Http404
    built = model.build(analysis.workspace, items_of(request, analysis.workspace))
    path = built.stations.get(analysis.slug) if built is not None else None
    if path is not None and path.is_file():
        return FileResponse(path.open("rb"), as_attachment=True, filename=f"{source.station}.zip")
    made = zip_path(source)
    if made is None or not made.is_file():
        raise Http404
    return redirect(reverse("jobs:file", args=[job.pk, source.relative(made)]))

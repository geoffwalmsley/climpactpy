"""Copy to workspace… (#241): a station's page of its own, ``/w/<id>/<station>/copy``,
reached from the station's provenance line and from its row of the workspace's Stations
table. It chooses a workspace of the owner's or a new one, then copies the station there
(:mod:`.copy_station`) and opens where the copy is: the workspace's overview, or the copy
itself when it is alone in a new workspace. The station copied is not changed."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from climpact_web.core.limits import human_required
from climpact_web.stations import copy_station, workspace
from climpact_web.stations.views import get_analysis


def back_url(request, analysis) -> str:
    """Where Cancel leads: the page the copy was asked from (``next``, a path of this
    site), else the station."""
    wanted = request.POST.get("next") or request.GET.get("next") or ""
    if wanted.startswith("/") and not wanted.startswith("//"):
        return wanted
    return workspace.home_url(analysis)


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def copy(request, workspace_id, slug):
    analysis = get_analysis(request, workspace_id, slug)
    if not workspace.set_up(analysis):
        return redirect(workspace.home_url(analysis))
    if request.method == "POST":
        form = copy_station.CopyForm(analysis, request.POST)
        if form.is_valid():
            target = form.cleaned_data["target"]
            made = copy_station.copy_to(request, analysis, target)
            space = made.workspace
            if target is None:
                messages.success(
                    request,
                    _("%(name)s was copied to a new workspace.") % {"name": made},
                )
                return redirect(workspace.home_url(made))
            messages.success(
                request,
                _("%(name)s was copied to %(workspace)s and is being calculated with its settings.")
                % {"name": made, "workspace": space.display_name},
            )
            return redirect(space.get_absolute_url())
    else:
        form = copy_station.CopyForm(analysis)
    context = {
        "analysis": analysis,
        **workspace.context(analysis, ""),
        "form": form,
        "back": back_url(request, analysis),
    }
    return render(request, "stations/copy.html", context)

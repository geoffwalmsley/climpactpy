"""The workspace file (#240, the WorkspaceList and Start boards): Save file downloads a
workspace as ``climpact_workspace.zip``; Open a workspace file rebuilds one from it in
this browser (:mod:`.workspace_file`).

- ``stations:workspace_file`` (``/w/<id>/workspace.zip``): Save file, on each row of
  Workspaces.
- ``stations:workspace_open`` (``/w/open/``): Open a workspace file, from Workspaces and
  Get started. A page of its own with the file field and the human check: the hosted
  site's Turnstile widget needs a form to sit in, and the page works without JavaScript.
"""

from __future__ import annotations

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.utils.translation import ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from climpact_web.core.limits import human_required
from climpact_web.stations import workspace, workspace_file
from climpact_web.stations.views_workspace import _owner, get_workspace


@never_cache
@require_safe
def save(request, workspace_id):
    """Save file: the workspace's input files and settings as one zip."""
    from climpact_web.stations.views_files import items_of

    space = get_workspace(request, workspace_id)
    owner = _owner(request)
    if not workspace_file.saved_stations(space, owner):
        messages.info(
            request,
            _("%(name)s has no station to save yet.") % {"name": space.display_name},
        )
        return redirect("stations:workspaces")
    handle = workspace_file.saved_file(space, owner, items_of(request, space))
    return FileResponse(
        handle,
        as_attachment=True,
        filename=workspace_file.FILE_NAME,
        content_type="application/zip",
    )


class OpenForm(forms.Form):
    file = forms.FileField(
        label=_lazy("Workspace file"),
        error_messages={"required": _lazy("Choose a workspace file.")},
        widget=forms.FileInput(attrs={"accept": ".zip,application/zip"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].help_text = _(
            "climpact_workspace.zip, from Save file on Workspaces; up to %(mb)d MB."
        ) % {"mb": settings.MAX_UPLOAD_MB}

    def clean_file(self) -> workspace_file.Opened:
        try:
            return workspace_file.read_upload(self.cleaned_data["file"])
        except workspace_file.NotAWorkspaceFile as refused:
            raise forms.ValidationError(refused.message) from None


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def open_file(request):
    """Open a workspace file: a new workspace of this browser, its stations checked and
    calculated again. It opens on its overview, or on its one station."""
    status = 200
    if request.method == "POST":
        form = OpenForm(request.POST, request.FILES)
        if form.is_valid():
            opened = form.cleaned_data["file"]
            try:
                space = workspace_file.open_into(request, opened)
            except workspace_file.NotAWorkspaceFile as refused:
                form.add_error("file", refused.message)
            else:
                count = len(opened.stations)
                messages.success(
                    request,
                    ngettext(
                        "%(name)s was opened from the workspace file. Its station is being "
                        "checked and calculated again.",
                        "%(name)s was opened from the workspace file. Its %(count)d stations "
                        "are being checked and calculated again.",
                        count,
                    )
                    % {"name": space.display_name, "count": count},
                )
                if count == 1:  # its Quality, or its Indices when they were in use
                    return redirect(workspace.home_url(space.stations.get()))
                return redirect(space.get_absolute_url())
        status = 400
    else:
        form = OpenForm()
    return render(request, "stations/workspace_open.html", {"form": form}, status=status)

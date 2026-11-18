"""Copy a station to another workspace (#241; the Flow board's rules: "Copy to workspace…
from a station to put it in another; it is recalculated with that workspace's settings").

The copy is a new station of the workspace chosen, or of a new one: the station's file,
its name and location, and its own index values (a batch metadata line's,
``origin["params"]``). Nothing else goes with it: its checks and its run are queued again
with the settings of the workspace it goes to (:func:`calculation.bring_up_to_date`). The
station copied is not changed.

A new workspace starts from the settings of the station's workspace, so the copy gives the
same results until they are changed there. In a workspace of several stations the copy's
run is the user's own at once, as an added station's is (#277,
:func:`calculation.commit_workspace`); alone in a new workspace it is in use only if the
station copied was ("Go to indices").
"""

from __future__ import annotations

from django import forms
from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.utils.translation import ngettext

from climpact_web.stations import calculation, workspace
from climpact_web.stations.models import Source, Station, Step, Workspace

NEW = "new"


def targets(station: Station) -> list[Workspace]:
    """The workspaces the station can be copied to: the owner's others that hold a
    station, the one changed last first."""
    return list(
        Workspace.objects.filter(owner=station.owner, stations__isnull=False)
        .exclude(pk=station.workspace_id)
        .distinct()
        .order_by("-updated_at")
    )


def name_taken(space: Workspace, name: str) -> bool:
    """Whether ``space`` already has a station called ``name`` (any case)."""
    wanted = name.strip().casefold()
    names = space.stations.values_list("station_name", flat=True)
    return any(n.strip().casefold() == wanted for n in names)


def target_label(space: Workspace, name: str) -> str:
    """A workspace as a choice: its name, how many stations (unless its default name says
    so: "2 stations, 18 Nov"), its base period, and whether it has a station of this name
    already."""
    count = space.stations.count()
    parts = [space.display_name]
    if space.name or count < 2:  # a default name of several says how many already
        parts.append(ngettext("%(count)s station", "%(count)s stations", count) % {"count": count})
    parts.append(_("base %(period)s") % {"period": workspace.base_period_text(space)})
    if name_taken(space, name):
        parts.append(_("has a station of this name"))
    return " · ".join(parts)


class CopyForm(forms.Form):
    """Where the copy goes: a workspace of the owner's, or a new one."""

    target = forms.ChoiceField(
        label=_lazy("Copy to"),
        widget=forms.RadioSelect,
        error_messages={"required": _lazy("Choose a workspace.")},
    )

    def __init__(self, station: Station, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.station = station
        self.spaces = {str(s.pk): s for s in targets(station)}
        name = station.station_name
        choices = [(pk, target_label(s, name)) for pk, s in self.spaces.items()]
        choices.append((NEW, _("A new workspace, with this workspace's settings")))
        self.fields["target"].choices = choices
        if not self.spaces:
            self.fields["target"].initial = NEW

    def clean_target(self) -> Workspace | None:
        """The workspace chosen, or None for a new one."""
        value = self.cleaned_data["target"]
        if value == NEW:
            return None
        space = self.spaces[value]
        if name_taken(space, self.station.station_name):
            raise forms.ValidationError(
                _(
                    "%(workspace)s already has a station called %(name)s. Choose another "
                    "workspace, or rename this station first."
                )
                % {"workspace": space.display_name, "name": self.station.station_name}
            )
        return space


def new_workspace(station: Station) -> Workspace:
    """A workspace for the copy, with the settings of the station's workspace."""
    source = station.workspace
    return Workspace.objects.create(
        owner=station.owner,
        base_start=source.base_start,
        base_end=source.base_end,
        qc_params=dict(source.qc_params or {}),
        index_settings=dict(source.index_settings or {}),
    )


def copy_to(request, station: Station, target: Workspace | None) -> Station:
    """Copy ``station`` to ``target`` (None: a new workspace) and queue its checks and run
    with that workspace's settings. The hosted limits are checked first, so a refusal
    copies nothing. Returns the copy."""
    from climpact_web.core.limits import check_job_quotas

    check_job_quotas(request)
    text = station.station_file.read_text(encoding="utf-8")
    with transaction.atomic():
        space = target if target is not None else new_workspace(station)
        several = space.stations.exists()
        copy = Station(
            workspace=space,
            owner=station.owner,
            source=Source.SAMPLE if station.source == Source.SAMPLE else Source.UPLOAD,
            file_name=station.file_name,
            summary=dict(station.summary or {}),
            warnings=list(station.warnings or []),
            station_name=station.station_name,
            latitude=station.latitude,
            longitude=station.longitude,
        )
        own = (station.origin or {}).get("params")
        if own:
            copy.origin = {"params": dict(own)}
        copy.save_station_text(text)
        copy.advance_to(Step.QC)
        if several or workspace.committed(station):
            copy.advance_to(Step.INDICES)
        copy.save()
    calculation.bring_up_to_date(request, copy)
    if several:
        calculation.commit_workspace(request, space)
    return copy

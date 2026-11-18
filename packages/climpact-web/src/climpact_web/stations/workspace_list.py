"""The Workspaces page (#242, the WorkspaceList board), which replaced "Your calculations":
every workspace of this browser (hosted) or this computer (local), most recently changed
first, each with a hint of its stations, the station count, a summary of the stations'
states ("2 ready · 2 usable · 1 fix first"), its base period, when it last changed and,
where workspaces expire, when it is deleted (highlighted when that is under three days
away). The landing page's "Welcome back" bar and Get started's "Or continue a workspace"
use the same rows (:func:`entries`).

A workspace is this session's when its ``owner`` is the session's owner token
(``jobs.views.OWNER_KEY``); locally the one browser is the computer's only user, so the
list is every workspace on the computer.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from climpact_web.stations import workspace
from climpact_web.stations.models import Station, Workspace

# A deletion date this close is highlighted (the board: "19 Nov · in 2 days").
SOON = dt.timedelta(days=3)
# The station names a several-station workspace's hint names before "and 4 more".
HINT_NAMES = 2


@dataclass
class Status:
    """One pill of the status summary: ``state`` is a Quality verdict (``ready``,
    ``usable``, ``fix``), ``checking``, ``failed`` (indices that failed) or ``none``."""

    state: str
    label: str
    count_label: str = ""  # for screen readers, after the label (a verdict's count)


@dataclass
class Entry:
    space: Workspace
    name: str
    url: str
    hint: str
    stations: int
    statuses: list[Status] = field(default_factory=list)
    base_period: str = ""
    updated: str = ""
    updated_iso: str = ""
    deleted_on: str = ""  # "" where workspaces don't expire
    deleted_iso: str = ""
    deleted_soon: str = ""  # "in 2 days", "tomorrow", "today": under SOON away
    delete_url: str = ""


def owned(owner: str):
    """The workspaces of ``owner``, most recently changed first, with their station
    counts."""
    return (
        Workspace.objects.filter(owner=owner)
        .annotate(station_count=Count("stations", filter=Q(stations__owner=owner)))
        .order_by("-updated_at", "pk")
    )


def when_text(when: dt.datetime, now: dt.datetime | None = None) -> str:
    """ "today 09:42", "yesterday 16:10", "15 Nov", or "15 Nov 2025" in another year."""
    now = timezone.localtime(now or timezone.now())
    local = timezone.localtime(when)
    days = (now.date() - local.date()).days
    if days == 0:
        return _("today %(time)s") % {"time": date_format(local, "H:i")}
    if days == 1:
        return _("yesterday %(time)s") % {"time": date_format(local, "H:i")}
    if local.year == now.year:
        return date_format(local, "j M")
    return date_format(local, "j M Y")


def soon_text(when: dt.datetime, now: dt.datetime | None = None) -> str:
    """ "in 2 days", "tomorrow" or "today" when ``when`` is under :data:`SOON` away,
    else ""."""
    now = now or timezone.now()
    if when - now >= SOON:
        return ""
    days = (timezone.localtime(when).date() - timezone.localtime(now).date()).days
    if days <= 0:
        return _("today")
    if days == 1:
        return _("tomorrow")
    return ngettext("in %(n)d day", "in %(n)d days", days) % {"n": days}


def _committed_failure(station: Station, state) -> bool:
    """Whether the station's indices failed, as its Stations row would say (#234): a
    run not in use yet (speculative) is not the station's (#277)."""
    from climpact_web.batch.fill import FAILED

    if state is None or state.state != FAILED:
        return False
    if state.job is not None and state.job.kind == "station":
        return workspace.committed(station)
    return True


def statuses(stations: list[Station]) -> list[Status]:
    """The status summary: one station's Quality verdict as its tab shows it ("Usable ·
    5"); several stations' counts by verdict ("2 ready", "2 usable", "1 fix first", "1
    checking"); and the stations whose indices failed ("1 failed")."""
    from climpact_web.batch.fill import run_states
    from climpact_web.stations.overview import _quality

    runs = run_states(stations)
    qualities = [_quality(s, workspace.section_states(s)["quality"]) for s in stations]
    failed = sum(1 for s in stations if _committed_failure(s, runs.get(s.pk)))
    out: list[Status] = []
    if len(stations) == 1:
        quality = qualities[0]
        if quality.verdict or quality.state == "checking":
            out.append(
                Status(
                    quality.state, f"{quality.label} {quality.count}".strip(), quality.count_label
                )
            )
    else:
        words = {
            "ready": lambda n: ngettext("%(n)d ready", "%(n)d ready", n),
            "usable": lambda n: ngettext("%(n)d usable", "%(n)d usable", n),
            "fix": lambda n: ngettext("%(n)d fix first", "%(n)d fix first", n),
            "checking": lambda n: ngettext("%(n)d checking", "%(n)d checking", n),
        }
        for state, word in words.items():
            n = sum(1 for q in qualities if q.state == state)
            if n:
                out.append(Status(state, word(n) % {"n": n}))
    if failed:
        out.append(
            Status("failed", ngettext("%(n)d failed", "%(n)d failed", failed) % {"n": failed})
        )
    return out


def hint(space: Workspace, stations: list[Station], waiting: int) -> str:
    """Under the name: one station's years ("1936–2015"); several stations' first names
    ("Sydney Observatory Hill, Newcastle Nobbys and 4 more"); files not added yet."""
    if not stations:
        if waiting:
            return ngettext(
                "%(n)d file waiting to be added", "%(n)d files waiting to be added", waiting
            ) % {"n": waiting}
        return ""
    if len(stations) == 1:
        summary = stations[0].summary or {}
        first, last = summary.get("first_year"), summary.get("last_year")
        return workspace.years_text(first, last) if first and last else ""
    names = [str(s) for s in stations[:HINT_NAMES]]
    more = len(stations) - len(names)
    if more:
        return ngettext("%(names)s and %(n)d more", "%(names)s and %(n)d more", more) % {
            "names": ", ".join(names),
            "n": more,
        }
    return _("%(first)s and %(second)s") % {"first": names[0], "second": names[1]}


def _waiting_files(space: Workspace, owner: str) -> int:
    from climpact_web.batch.models import BatchRun

    run = BatchRun.objects.filter(workspace=space, owner=owner, job=None).first()
    return len((run.report or {}).get("files") or {}) if run is not None else 0


def entry(space: Workspace, owner: str, now: dt.datetime | None = None) -> Entry:
    """One row of the Workspaces table."""
    from django.urls import reverse

    from climpact_web.stations.overview import ordered

    now = now or timezone.now()
    stations = list(ordered(space, owner).select_related("qc_job", "indices_job", "workspace"))
    waiting = 0 if stations else _waiting_files(space, owner)
    expires = space.expires_at
    return Entry(
        space=space,
        name=space.display_name,
        url=space.get_absolute_url(),
        hint=hint(space, stations, waiting),
        stations=len(stations),
        statuses=statuses(stations) if stations else [],
        base_period=f"{space.base_start}–{space.base_end}",
        updated=when_text(space.updated_at, now),
        updated_iso=space.updated_at.isoformat(),
        deleted_on=date_format(timezone.localtime(expires), "j M") if expires else "",
        deleted_iso=expires.isoformat() if expires else "",
        deleted_soon=soon_text(expires, now) if expires else "",
        delete_url=reverse("stations:workspace_delete", args=[space.pk]),
    )


def entries(owner: str, limit: int | None = None) -> list[Entry]:
    """The rows of ``owner``'s workspaces, most recently changed first; ``limit`` the
    first few (Get started's "Or continue a workspace")."""
    now = timezone.now()
    spaces = owned(owner)
    if limit is not None:
        spaces = spaces[:limit]
    return [entry(space, owner, now) for space in spaces]


def latest(owner: str) -> Entry | None:
    """The workspace changed last, for the landing page's "Welcome back" bar."""
    space = owned(owner).first()
    return entry(space, owner) if space is not None else None

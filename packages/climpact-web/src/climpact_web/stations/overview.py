"""The workspace overview (#234, the Workspace and Calculate boards).

A workspace of two or more stations opens on its overview, ``/w/<id>/``: its context bar
(the name, the stations, base period, settings, version and deletion date, Workspace
settings and Rename, Add stations, then the tabs), the run status line and the Stations
table. While stations are checked and calculated it is the page that shows how they go
(``Calculate.dc.html``), polled by htmx; it replaced the batch results page and the batch
steps.

:func:`rows` gives each station's row of the Stations table: its name and page, its
coordinates, years and missing values, its Quality verdict with its count, its indices
state (``batch.fill.run_states``: Done, Calculating with its percentage, Waiting, Not run,
Failed, each with its fix) and how many of its indices have a significant trend.
:func:`status_line` sums them up in one line above the table.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from climpact_web.batch.fill import CALCULATING, DONE, FAILED, NOT_RUN, WAITING, run_states
from climpact_web.core import numbers
from climpact_web.jobs.models import Status
from climpact_web.jobs.views import format_duration
from climpact_web.stations import workspace
from climpact_web.stations.models import Station, Workspace

# The Quality column: a verdict pill in its tint, else the state in words (#222).
VERDICT_STATES = workspace.VERDICTS
RUNNING = (WAITING, CALCULATING)


def ordered(space: Workspace, owner: str):
    """The workspace's stations in the order they were added (a batch's in its metadata
    file's order), the order of the Stations table and of the previous and next station."""
    return space.stations.filter(owner=owner).order_by("created_at", "station_name", "pk")


@dataclass
class Quality:
    state: str  # workspace.section_states' Quality state: a verdict, checking, locked...
    label: str
    count: str = ""  # "· 296", after a verdict's word
    count_label: str = ""  # for screen readers: ", 296 values look wrong"

    @property
    def verdict(self) -> bool:
        return self.state in VERDICT_STATES


@dataclass
class Indices:
    state: str  # batch.fill's: waiting, calculating, done, not_run, failed; "" for none
    label: str
    percent: int | None = None
    error: str = ""
    fix_label: str = ""
    fix_url: str = ""
    job: object = None


@dataclass
class Row:
    station: Station
    name: str
    url: str
    coordinates: str
    period: str
    missing: str
    quality: Quality
    indices: Indices
    significant: str = ""
    significant_label: str = ""


def _quality(station: Station, state: str) -> Quality:
    if state in VERDICT_STATES:
        wrong = workspace.qc_verdict(station, workspace.shown_qc(station))[1]
        label = str(workspace.STATES[state][0])
        if not wrong:
            return Quality(state, label)
        count = _("· %(n)s") % {"n": numbers.grouped(wrong)}
        count_label = ngettext(", %(n)s value looks wrong", ", %(n)s values look wrong", wrong) % {
            "n": numbers.grouped(wrong)
        }
        return Quality(state, label, count, count_label)
    if state == "locked":  # no checks: a file the batch left out, say
        return Quality(state, "–")
    return Quality(state, str(workspace.STATES[state][0]))


def _sentence(text: str) -> str:
    """An error as a sentence: a capital first, a full stop last."""
    text = text.strip()
    if not text:
        return ""
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def not_run_reason(error: str) -> str:
    """The first line of why a station was not run, without "Not calculated: "."""
    head = (error or "").split("\n", 1)[0].strip()
    for prefix in (_("Not calculated:"), "Not calculated:"):
        if head.startswith(prefix):
            head = head[len(prefix) :].strip()
    return head


def base_period_problem(error: str) -> bool:
    """Whether a station's error is about the base period, which Workspace settings fix."""
    return "base period" in (error or "").lower()


def _indices(station: Station, state, quality: Quality, space: Workspace) -> Indices:
    """The Indices column: the station's run state in words, with its fix."""
    if state is None:
        # No run of a batch nor of its own: before its checks, or a file left out.
        section = workspace.section_states(station)["results"]
        if section == "running":
            return Indices(CALCULATING, _("Calculating"))
        return Indices("", "–")
    if state.state == DONE:
        return Indices(DONE, _("Done"), job=state.job)
    if state.state == CALCULATING:
        label = _("Calculating · %(percent)s%%") % {"percent": state.percent or 0}
        return Indices(CALCULATING, label, percent=state.percent or 0, job=state.job)
    if state.state == WAITING:
        return Indices(WAITING, _("Waiting"), job=state.job)
    if state.state == NOT_RUN:
        out = Indices(NOT_RUN, _("Not run"), error=not_run_reason(state.error), job=state.job)
        if quality.state == "fix":
            out.fix_label, out.fix_url = _("Fix quality first"), station.url("qc")
        elif not workspace.set_up(station):
            out.fix_label, out.fix_url = _("Fix the file"), station.url()
        return out
    error = _sentence(state.error)
    out = Indices(FAILED, _("Failed"), error=error, job=state.job)
    if base_period_problem(error):
        out.fix_label = _("Change base period")
        out.fix_url = reverse("stations:workspace_setting", args=[space.pk, "base-period"])
    return out


def _significant(station: Station, indices: Indices) -> tuple[str, str]:
    """How many of the station's indices have a significant trend: "22 of 80", and its
    words for screen readers; "–" without results."""
    if indices.state != DONE:
        return "–", _("no results")
    from climpact_web.stations import results as results_model

    job = workspace.shown_run(station)
    if job is None and station.indices_job is not None:
        job = station.indices_job if station.indices_job.status == Status.SUCCEEDED else None
    if job is None:
        return "–", _("no results")
    name = (station.origin or {}).get("station") if job.kind == "batch" else None
    source = results_model.run_source(job, name)
    if source is None:
        return "–", _("no results")
    space = station.workspace
    run = results_model.results_for(source, station.summary, (space.base_start, space.base_end))
    total = len(run.cards)
    if not total:
        return "–", _("no indices calculated")
    count = sum(1 for c in run.cards if c.significant)
    values = {"count": numbers.grouped(count), "total": numbers.grouped(total)}
    text = _("%(count)s of %(total)s") % values
    label = (
        ngettext(
            "%(count)s of %(total)s index with a significant trend",
            "%(count)s of %(total)s indices with a significant trend",
            total,
        )
        % values
    )
    return text, label


def _missing(summary: dict) -> str:
    """The share of all values missing over the three variables: "6.9%"."""
    variables = summary.get("variables") or []
    days = summary.get("days") or 0
    if not variables or not days:
        return "–"
    missing = sum(v.get("missing", 0) for v in variables)
    return f"{numbers.fixed(100 * missing / (days * len(variables)), 1)}%"


def rows(space: Workspace, owner: str) -> list[Row]:
    stations = list(ordered(space, owner).select_related("qc_job", "indices_job", "workspace"))
    states = run_states(stations)
    out = []
    for station in stations:
        summary = station.summary or {}
        first, last = summary.get("first_year"), summary.get("last_year")
        quality = _quality(station, workspace.section_states(station)["quality"])
        indices = _indices(station, states.get(station.pk), quality, space)
        significant, significant_label = _significant(station, indices)
        complete = station.latitude is not None and station.longitude is not None
        out.append(
            Row(
                station=station,
                name=station.station_name or station.file_name,
                url=workspace.home_url(station),
                coordinates=numbers.coordinates(station.latitude, station.longitude)
                if complete
                else "–",
                period=f"{first}–{last}" if first and last else "–",
                missing=_missing(summary),
                quality=quality,
                indices=indices,
                significant=significant,
                significant_label=significant_label,
            )
        )
    return out


# ---- the run status line -----------------------------------------------------------------


@dataclass
class Link:
    label: str
    url: str
    post: bool = False  # a form button (Cancel, Undo), not a link
    next: str = ""


@dataclass
class StatusLine:
    """One line above the Stations table (#234): ``tone`` is ``running`` (neutral, with a
    bar), ``done`` (quiet) or ``failed`` (red, naming the station and why)."""

    tone: str
    head: str
    rest: str = ""
    percent: int = 0
    links: list[Link] = field(default_factory=list)


def _elapsed(jobs: list, now: dt.datetime) -> dt.timedelta | None:
    """From the first of ``jobs`` to start to the last to finish (or now)."""
    starts = [j.started_at for j in jobs if j.started_at]
    if not starts:
        return None
    ends = [j.finished_at or now for j in jobs if j.started_at]
    return max(max(ends) - min(starts), dt.timedelta(0))


def _not_run_sentence(not_run: list[Row]) -> str:
    if not not_run:
        return ""
    if len(not_run) == 1:
        row = not_run[0]
        if row.indices.fix_label == _("Fix quality first"):
            return _("%(name)s was not run: fix its quality first.") % {"name": row.name}
        reason = row.indices.error
        if reason:
            return _("%(name)s was not run: %(reason)s") % {
                "name": row.name,
                "reason": reason[:1].lower() + reason[1:] if reason[1:2].islower() else reason,
            }
        return _("%(name)s was not run.") % {"name": row.name}
    return ngettext(
        "%(count)s station was not run; its row says how to fix it.",
        "%(count)s stations were not run; their rows say how to fix them.",
        len(not_run),
    ) % {"count": len(not_run)}


def status_line(
    space: Workspace, table: list[Row], batch=None, page: str = ""
) -> StatusLine | None:
    """The run status line (``Calculate.dc.html``): None when no station has been run.
    ``batch`` is the workspace's batch that ran (``BatchRun``), for its zip, its time left
    and Cancel; ``page`` the overview's address, where Cancel and Undo return."""
    run = [r for r in table if r.indices.state in (*RUNNING, DONE, FAILED)]
    not_run = [r for r in table if r.indices.state == NOT_RUN]
    if not run:
        return None
    now = timezone.now()
    total = len(run)
    done = [r for r in run if r.indices.state == DONE]
    failed = [r for r in run if r.indices.state == FAILED]
    going = [r for r in run if r.indices.state in RUNNING]
    jobs = list({id(r.indices.job): r.indices.job for r in run if r.indices.job}.values())
    batch_job = batch.job if batch is not None else None
    change = workspace.change_state(space)
    if going:
        finished = len(done) + len(failed)
        progress = finished + sum((r.indices.percent or 0) / 100 for r in going)
        head = ngettext(
            "Calculating indices: %(done)s of %(total)s station done.",
            "Calculating indices: %(done)s of %(total)s stations done.",
            total,
        ) % {"done": finished, "total": total}
        rest = []
        remaining = None
        if batch_job is not None and not batch_job.is_finished and batch_job in jobs:
            remaining = batch_job.remaining(now)
        if remaining is not None:
            rest.append(_("About %(time)s left.") % {"time": format_duration(remaining)})
        if finished:
            rest.append(_("Finished stations open now."))
        if sentence := _not_run_sentence(not_run):
            rest.append(sentence)
        links = []
        if change is not None and change.can_undo:
            links.append(
                Link(
                    _("Undo the change"), reverse("stations:workspace_undo", args=[space.pk]), True
                )
            )
        elif batch_job is not None and batch_job.can_cancel and batch_job in jobs:
            links.append(Link(_("Cancel"), reverse("jobs:cancel", args=[batch_job.pk]), True, page))
        return StatusLine("running", head, " ".join(rest), int(100 * progress / total), links)

    took = _elapsed(jobs, now)
    values = {"done": len(done), "total": total, "time": format_duration(took)}
    links = []
    # The batch's zip holds every station's results while they are the batch's.
    if (
        batch_job is not None
        and batch_job.status == Status.SUCCEEDED
        and batch_job.result.get("zip")
        and done
        and all(r.indices.job == batch_job for r in done)
    ):
        path = batch_job.output_dir / batch_job.result["zip"]
        size = path.stat().st_size if path.is_file() else 0
        from django.template.defaultfilters import filesizeformat

        label = _("Download all (zip, %(size)s)") % {"size": filesizeformat(size)}
        links.append(
            Link(label, reverse("jobs:file", args=[batch_job.pk, batch_job.result["zip"]]))
        )
    if failed:
        if took is not None:
            head = (
                ngettext(
                    "%(done)s of %(total)s station calculated in %(time)s.",
                    "%(done)s of %(total)s stations calculated in %(time)s.",
                    total,
                )
                % values
            )
        else:
            head = (
                ngettext(
                    "%(done)s of %(total)s station calculated.",
                    "%(done)s of %(total)s stations calculated.",
                    total,
                )
                % values
            )
        if len(failed) == 1:
            head += " " + _("%(name)s failed:") % {"name": failed[0].name}
            error = failed[0].indices.error or _("The station could not be calculated.")
            rest = [error[:1].lower() + error[1:] if error[1:2].islower() else error]
            if base_period_problem(error):
                rest.append(
                    _("Change the base period in Workspace settings, or remove the station.")
                )
        else:
            head += " " + ngettext("%(count)s failed:", "%(count)s failed:", len(failed)) % {
                "count": len(failed)
            }
            rest = [_("their rows say why.")]
        if sentence := _not_run_sentence(not_run):
            rest.append(sentence)
        settings_url = reverse("stations:workspace_settings", args=[space.pk])
        links.insert(0, Link(_("Workspace settings"), settings_url))
        return StatusLine("failed", head, " ".join(rest), 100, links)
    if took is not None:
        head = (
            ngettext(
                "%(done)s station calculated in %(time)s.",
                "%(done)s stations calculated in %(time)s.",
                len(done),
            )
            % values
        )
    else:
        head = (
            ngettext("%(done)s station calculated.", "%(done)s stations calculated.", len(done))
            % values
        )
    return StatusLine("done", head, _not_run_sentence(not_run), 100, links)


def active(table: list[Row]) -> bool:
    """Whether something is still on the way, so the page polls: a run, or checks."""
    return any(r.indices.state in RUNNING or r.quality.state == "checking" for r in table)

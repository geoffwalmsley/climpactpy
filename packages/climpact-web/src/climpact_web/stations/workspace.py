"""The station workspace (#179): what each section shows, and whether it is out of date.

A station's pages are three sections, Quality, Indices (Results before #236) and Files,
shown as tabs under the station's name, beside the Inputs panel (#198), which lists what
the user gave and opens each in a side sheet to change it (:func:`inputs_panel`). A change
to an input no longer resets the later sections. Each job records the inputs it was
produced from when it is queued (``Job.inputs``):

``file``      the SHA-256 of the station file (``Station.file_hash``)
``data``      what the provenance lines say about that file (#269, :func:`file_record`):
              its name, first and last year, days and the variables with values
``metadata``  the station details: name, latitude, longitude and base period
``qc``        the quality-control thresholds, with R's defaults filled in
``settings``  a station run's index settings and output options (:func:`settings_of`)

The base period, the thresholds and the index settings are the workspace's (#254,
``Workspace``): every station of the workspace has the same, except the index values a
batch's metadata file gives a station of its own (:func:`station_settings`). A change to
one of them is a change to every station's inputs, so every station's results go out of
date together and :mod:`.calculation` queues their replacements together (one change, one
id: ``params["change"]``), which :func:`undo_available` lets the user undo while they are
on the way.

A section is out of date ("stale") when the inputs its shown job was produced from differ
from the analysis's current ones. The comparison uses only what is stored, never the
browser session, so it holds in every browser tab open on the analysis and in hosted mode.
The quality checks depend on the file, the thresholds and the station name (their files
are named after it); a station run on all four inputs. A station opened from a batch
(``origin``) shows the batch's results, whose inputs are ``origin["inputs"]``.

The results of the old inputs stay on the page, marked out of date, while the run of the
new inputs is queued or running: that run's ``params["replaces"]`` names the finished job
it replaces (#178's recalculation, here for the checks too). When it has finished it is
shown and the section is current again. :func:`settle` goes back to the replaced job when
an input is changed back. Queueing the replacements is :mod:`.calculation`'s.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from climpact_web.core import numbers
from climpact_web.jobs.models import Job, Status
from climpact_web.stations.models import Station, Step

# The ``params`` key of a job that names the finished job of the same kind whose results
# stay on the page, out of date, until this one has finished.
REPLACES = "replaces"

# The inputs each kind of job depends on, by name (see :func:`differences`).
QC_INPUTS = ("file", "name", "qc")
RUN_INPUTS = ("file", "name", "location", "base_period", "qc", "settings")


# ---- inputs ------------------------------------------------------------------------------


def qc_values(analysis: Station) -> dict:
    """The quality-control thresholds of the analysis's workspace, with R's defaults for
    those not set."""
    from climpact_web.stations.forms import QCParamsForm

    return QCParamsForm.initial_for(analysis.workspace.qc_params)


def default_settings() -> dict:
    """The index settings and output options of a workspace that has none of its own, as
    :func:`settings_of` gives them: the settings form's defaults, read from its fields
    without importing the core."""
    from climpact_web.stations.forms_indices import PARAM_FIELDS, IndexParamsForm

    fields = IndexParamsForm.base_fields
    params = {name: fields[name].initial for name in PARAM_FIELDS}
    params["custom"] = {
        key: fields[f"custom_{key}"].initial for key in ("variable", "operator", "threshold")
    }
    return {"params": params, "plot_title": "", "plots": True, "zip": True, "report": True}


def own_params(analysis: Station) -> dict:
    """The index values that are the station's own, not the workspace's: those of its line
    in a batch's metadata file (``origin["params"]``: wsdin, csdin, Tb_HDD, Tb_CDD, Tb_GDD,
    rxnday, rnnmm, txtn and SPEI, as ``IndexParams`` fields)."""
    from climpact_web.stations.forms_indices import PARAM_FIELDS

    params = (analysis.origin or {}).get("params") or {}
    return {name: params[name] for name in PARAM_FIELDS if name in params}


def station_settings(analysis: Station) -> dict:
    """The index settings and output options a run of the station uses (:func:`settings_of`
    form): the workspace's (the defaults until set), with the station's own index values
    in place of the workspace's (:func:`own_params`). A batch's custom index is its
    workspace's too (#255): the workspace starts with none, as the batch calculates none."""
    out = workspace_settings(analysis.workspace)
    out["params"].update(own_params(analysis))
    return out


def workspace_settings(space) -> dict:
    """The workspace's index settings and output options (:func:`settings_of` form), with
    the defaults for what it has not set."""
    out = default_settings()
    if space.index_settings:
        chosen = settings_of(space.index_settings)
        out.update(chosen)
        out["params"] = {**default_settings()["params"], **chosen["params"]}
    return out


def settings_of(params: dict) -> dict:
    """The ``settings`` input of a ``station`` job's parameters: the index settings and the
    output options (plots, zip, report and plot title)."""
    p = params or {}
    return {
        "params": p.get("params") or {},
        "plot_title": p.get("plot_title") or "",
        "plots": bool(p.get("plots", True)),
        "zip": bool(p.get("zip", True)),
        "report": bool(p.get("report", True)),
    }


def file_record(file_name: str, summary: dict | None) -> dict:
    """What the provenance lines say about a station file (#269), from its name and its
    summary (:func:`.station_file.summarise`): recorded with each job beside the file's
    hash (``inputs["data"]``), so out-of-date checks and results are described by the file
    they read, not by the one that replaced it."""
    summary = summary or {}
    return {
        "name": file_name or "",
        "first_year": summary.get("first_year"),
        "last_year": summary.get("last_year"),
        "days": summary.get("days"),
        "variables": [v["key"] for v in summary.get("variables", []) if v.get("present", 0) > 0],
    }


def current_inputs(analysis: Station) -> dict:
    """The analysis's inputs now: its file (its hash, and what the provenance lines say
    about it) and station details, and its workspace's base period, thresholds and index
    settings (with the station's own values, #254)."""
    return {
        "file": analysis.file_hash,
        "data": file_record(analysis.file_name, analysis.summary),
        "metadata": analysis.metadata,
        "qc": qc_values(analysis),
        "settings": station_settings(analysis),
    }


def job_inputs(analysis: Station, kind: str, params: dict) -> dict:
    """The inputs to record on a job of ``kind`` queued now with ``params``: a ``qc`` job
    has no settings, a ``station`` job the settings it was given."""
    inputs = current_inputs(analysis)
    if kind == "station":
        inputs["settings"] = settings_of(params)
    else:
        del inputs["settings"]
    return inputs


def differences(recorded: dict | None, wanted: dict, names=RUN_INPUTS) -> list[str]:
    """The inputs among ``names`` that differ between what a job was produced from
    (``recorded``) and what is wanted now: ``file``, ``name``, ``location`` (latitude or
    longitude), ``base_period``, ``qc`` and ``settings``. An input the job did not record
    (a job from before #179, a batch's results without settings) never differs."""
    if not recorded:
        return []

    def meta(d, *keys):
        values = d.get("metadata") or {}
        return tuple(values.get(k) for k in keys)

    pairs = {
        "file": ("file", lambda d: d.get("file")),
        "name": ("metadata", lambda d: meta(d, "name")),
        "location": ("metadata", lambda d: meta(d, "latitude", "longitude")),
        "base_period": ("metadata", lambda d: meta(d, "base_start", "base_end")),
        "qc": ("qc", lambda d: d.get("qc")),
        "settings": ("settings", lambda d: d.get("settings")),
    }
    found = []
    for name in names:
        key, value = pairs[name]
        if key in recorded and key in wanted and value(recorded) != value(wanted):
            found.append(name)
    return found


# ---- the jobs each section shows ---------------------------------------------------------


def replaces_for(old: Job | None) -> str | None:
    """The ``replaces`` value of a job queued to replace ``old`` (same kind): ``old`` if it
    has finished, else the job ``old`` was itself replacing, which is still the one shown."""
    if old is None:
        return None
    if old.status == Status.SUCCEEDED:
        return str(old.pk)
    return (old.params or {}).get(REPLACES)


def replaced_job(analysis: Station, job: Job | None) -> Job | None:
    """The finished job of the same kind that ``job`` replaces, while it is still kept."""
    job_id = (job.params or {}).get(REPLACES) if job is not None else None
    if not job_id:
        return None
    return Job.objects.filter(
        pk=job_id, owner=analysis.owner, kind=job.kind, status=Status.SUCCEEDED
    ).first()


def shown_qc(analysis: Station) -> Job | None:
    """The finished checks Quality shows: the analysis's ``qc`` job, or, while a check of
    new inputs is queued, running or has failed, the one it replaces."""
    job = analysis.qc_job
    if job is None or job.status == Status.SUCCEEDED:
        return job
    return replaced_job(analysis, job)


def batch_results(analysis: Station) -> bool:
    """Whether the station shows a batch's results (``origin["job"]``). A batch's station
    that failed in its run, was left out of it or is still waiting has none (#255)."""
    return bool((analysis.origin or {}).get("job"))


def committed(analysis: Station) -> bool:
    """Whether the user has chosen to use the data ("See results"), or the station shows a
    batch's results. Before that, Results are not shown, nor is the speculative run
    (#178) anywhere, Files included."""
    return analysis.reached(Step.INDICES) or batch_results(analysis)


def batch_job(analysis: Station) -> Job | None:
    """The finished batch job an analysis was opened from, if it is still kept."""
    job_id = (analysis.origin or {}).get("job")
    if not job_id:
        return None
    return Job.objects.filter(pk=job_id, owner=analysis.owner, status=Status.SUCCEEDED).first()


def shown_run(analysis: Station) -> Job | None:
    """The finished run Results show: the analysis's own, or the one a newer run replaces,
    or the batch's; None before "See results", or while the first run is going on."""
    if not committed(analysis):
        return None
    job = analysis.indices_job
    if job is not None:
        if job.status == Status.SUCCEEDED:
            return job
        replaced = replaced_job(analysis, job)
        if replaced is not None:
            return replaced
    return batch_job(analysis)


def restore_if_cancelled(analysis: Station) -> None:
    """A cancelled run leaves the results it would have replaced in place: the replaced
    run, or the batch's results (no run of its own)."""
    job = analysis.indices_job
    if job is None or job.status != Status.CANCELLED:
        return
    replaced = replaced_job(analysis, job)
    if replaced is not None:
        analysis.indices_job = replaced
    elif batch_job(analysis) is not None:
        analysis.indices_job = None
    else:
        return
    analysis.save(update_fields=["indices_job"])


# ---- staleness ---------------------------------------------------------------------------


def recorded_inputs(analysis: Station, job: Job | None) -> dict:
    """What ``job`` was produced from: its own record, or a batch's ``origin["inputs"]``."""
    if job is None:
        return {}
    if job.kind == "batch":
        return (analysis.origin or {}).get("inputs") or {}
    return job.inputs or {}


def qc_changes(analysis: Station, job: Job | None) -> list[str]:
    """The inputs that changed since the checks ``job`` ran."""
    return differences(recorded_inputs(analysis, job), current_inputs(analysis), QC_INPUTS)


def run_changes(analysis: Station, job: Job | None) -> list[str]:
    """The inputs that changed since the run ``job`` (the shown results) was made."""
    return differences(recorded_inputs(analysis, job), current_inputs(analysis), RUN_INPUTS)


def pending_changes(analysis: Station, job: Job | None, kind: str) -> list[str]:
    """For the job a section links to (the latest asked for): the inputs it is not of, so
    a new one must be queued. The settings are compared too since they are the
    workspace's (#254)."""
    if job is None:
        return []
    names = QC_INPUTS if kind == "qc" else RUN_INPUTS
    return differences(recorded_inputs(analysis, job), current_inputs(analysis), names)


def settle(analysis: Station) -> None:
    """After an input changed: cancel the checks and runs still waiting or running for the
    old inputs, as nobody will see them; and where an input was changed back, link the
    finished job of these inputs again rather than calculate it twice. The caller saves."""
    for field in ("qc_job", "indices_job"):
        job = getattr(analysis, field)
        if job is None or not pending_changes(analysis, job, job.kind):
            continue
        replaced = replaced_job(analysis, job)
        if job.can_cancel:
            job.request_cancel()
        if (
            replaced is not None
            and replaced.inputs  # known to be of these inputs, not just never recorded
            and not pending_changes(analysis, replaced, replaced.kind)
        ):
            setattr(analysis, field, replaced)


# ---- undo (#254) --------------------------------------------------------------------------


def change_jobs(change: str):
    """The jobs queued for the change ``change`` (``params["change"]``)."""
    from climpact_web.jobs.models import CHANGE

    return Job.objects.filter(**{f"params__{CHANGE}": change})


def undo_available(workspace_) -> bool:
    """Whether the workspace's last change to its settings can still be undone: until the
    recalculation it queued has finished, while one of its jobs still waits or runs."""
    change = (workspace_.undo or {}).get("change")
    if not change:
        return False
    return (
        change_jobs(change)
        .filter(status__in=(Status.QUEUED, Status.RUNNING), cancel_requested=False)
        .exists()
    )


@dataclass(frozen=True)
class ChangeState:
    """Where the workspace's last change to its settings stands, for a view to show (the
    run status line of #234): its jobs (the checks and runs of every station), how many
    of them have finished, failed or been cancelled, and whether it can still be undone."""

    change: str
    jobs: list
    total: int
    done: int
    failed: int
    cancelled: int
    can_undo: bool

    @property
    def finished(self) -> bool:
        return self.done + self.failed + self.cancelled == self.total


def change_state(workspace_) -> ChangeState | None:
    """The state of the workspace's last change to its settings (``Workspace.undo``), or
    None when there is none to show: none was made, it was undone, or a station's own
    change has replaced it since (``calculation.forget_undo``)."""
    change = (workspace_.undo or {}).get("change")
    if not change:
        return None
    jobs = list(change_jobs(change).order_by("created_at"))
    count = Counter(job.status for job in jobs)
    return ChangeState(
        change=change,
        jobs=jobs,
        total=len(jobs),
        done=count[Status.SUCCEEDED],
        failed=count[Status.FAILED],
        cancelled=count[Status.CANCELLED],
        can_undo=undo_available(workspace_),
    )


def details_valid(analysis: Station) -> bool:
    """Whether the saved station details are complete and fit the data."""
    from climpact_web.stations.forms import MetadataForm

    if not analysis.metadata_complete:
        return False
    data = {
        "station_name": analysis.station_name,
        "latitude": analysis.latitude,
        "longitude": analysis.longitude,
        "base_start": analysis.workspace.base_start,
        "base_end": analysis.workspace.base_end,
    }
    return MetadataForm(data, summary=analysis.summary).is_valid()


def change_sentences(analysis: Station, job: Job | None, changes: list[str]) -> list:
    """What changed since ``job``, in words, for the out-of-date banner."""
    recorded = recorded_inputs(analysis, job)
    old_meta = recorded.get("metadata") or {}
    sentences = []
    for name in changes:
        if name == "file":
            sentences.append(_("You loaded a different station file."))
        elif name == "name":
            sentences.append(
                _("You changed the station name to %(name)s.") % {"name": analysis.station_name}
            )
        elif name == "location":
            sentences.append(_("You changed the latitude or longitude."))
        elif name == "base_period":
            sentences.append(
                _("You changed the base period to %(new)s. These results use %(old)s.")
                % {
                    "new": base_period_text(analysis.workspace),
                    "old": f"{old_meta.get('base_start')}–{old_meta.get('base_end')}",
                }
            )
        elif name == "qc":
            sentences.append(_("You changed the quality-control thresholds."))
        elif name == "settings":
            sentences.append(_("You changed the settings."))
    return sentences


# ---- the tabs ----------------------------------------------------------------------------

# Each state's word and icon: the word is always given to screen readers, and shown for
# the states that ask for the user's attention; the icon's shape tells them apart without
# colour (DESIGN.md, "Don't use colour alone"). Quality's tab shows the verdict of the
# checks instead of "done" (#222): Ready, Usable or Fix first, the words and icons of the
# verdict band, with the count of values that look wrong; and "Checking…" while they run.
STATES = {
    "done": (gettext_lazy("Done"), "check-circle", False),
    "attention": (gettext_lazy("Needs attention"), "warning", True),
    "stale": (gettext_lazy("Out of date"), "clock", True),
    "running": (gettext_lazy("Running"), "refresh", True),
    "checking": (gettext_lazy("Checking…"), "refresh", True),
    "todo": (gettext_lazy("Not started"), "circle", False),
    "locked": (gettext_lazy("Not available yet"), "lock", False),
    "ready": (gettext_lazy("Ready"), "check-circle", True),
    "usable": (gettext_lazy("Usable"), "warning", True),
    "fix": (gettext_lazy("Fix first"), "error", True),
}

VERDICTS = ("ready", "usable", "fix")  # qc_review.Verdict.level

SECTIONS = (
    ("quality", gettext_lazy("Quality"), "qc"),
    # Named Indices since #236 (``indices`` since #256); its URL name stays ``results``.
    ("results", gettext_lazy("Indices"), "results"),
    ("files", gettext_lazy("Files"), "downloads"),
)


@dataclass
class Section:
    key: str
    label: str
    url: str | None  # None while the section is not available yet
    state: str
    current: bool = False
    wrong: int = 0  # Quality's verdict: the values that look wrong, shown after the word

    @property
    def verdict(self) -> bool:
        return self.state in VERDICTS

    @property
    def count(self) -> str:
        """The verdict's count for the tab, after the word: "· 21", or "" when nothing
        looks wrong."""
        if not (self.verdict and self.wrong):
            return ""
        return _("· %(n)s") % {"n": numbers.grouped(self.wrong)}

    @property
    def count_label(self) -> str:
        """The count for screen readers, after the word: ", 21 values look wrong"."""
        return ngettext(", %(n)s value looks wrong", ", %(n)s values look wrong", self.wrong) % {
            "n": numbers.grouped(self.wrong)
        }

    @property
    def state_label(self) -> str:
        return STATES[self.state][0]

    @property
    def icon(self) -> str:
        return STATES[self.state][1]

    @property
    def word_shown(self) -> bool:
        return STATES[self.state][2]


def remember_verdict(job: Job, level: str, wrong: int) -> None:
    """Keep the verdict's level and its count of values that look wrong with the checks,
    for the Quality tab (#179, #222)."""
    result = job.result or {}
    if (result.get("verdict"), result.get("verdict_wrong")) != (level, wrong):
        job.result = {**result, "verdict": level, "verdict_wrong": wrong}
        type(job).objects.filter(pk=job.pk).update(result=job.result)


def qc_verdict(analysis: Station, job: Job) -> tuple[str, int] | None:
    """The verdict of finished checks: its level and the values that look wrong. Quality
    keeps it when it shows the checks; the tab works it out once when it has not been kept
    yet (checks not yet shown, or kept before #222). None when it cannot be."""
    result = job.result or {}
    if result.get("verdict") in VERDICTS and "verdict_wrong" in result:
        return result["verdict"], result["verdict_wrong"]
    from climpact_web.stations import qc_review

    try:
        verdict = qc_review.review(job, analysis.station_file).verdict
    except FileNotFoundError:
        return None
    remember_verdict(job, verdict.level, verdict.wrong)
    return verdict.level, verdict.wrong


def _active(job: Job | None) -> bool:
    return job is not None and job.status in (Status.QUEUED, Status.RUNNING)


def section_states(analysis: Station) -> dict[str, str]:
    """Each section's state: done, attention (needs the user), stale (out of date),
    running, todo (not started) or locked (its input does not exist yet). Quality's is
    instead "checking" while the checks run, and once they have finished the verdict:
    ready, usable or fix (#222)."""
    states = {}
    qc_job, qc_shown = analysis.qc_job, shown_qc(analysis)
    qc_ready = (
        analysis.reached(Step.QC) and analysis.metadata_complete and analysis.station_file.is_file()
    )
    if not qc_ready:
        states["quality"] = "locked"
    elif qc_shown is not None and qc_changes(analysis, qc_shown):
        states["quality"] = "stale"
    elif _active(qc_job):
        states["quality"] = "checking"
    elif qc_job is None:
        states["quality"] = "todo"
    elif qc_shown is None or qc_shown != qc_job:
        states["quality"] = "attention"  # the checks failed or were stopped
    else:
        verdict = qc_verdict(analysis, qc_shown)
        states["quality"] = verdict[0] if verdict else "done"

    run, run_shown = analysis.indices_job, shown_run(analysis)
    if not committed(analysis):
        states["results"] = "locked"
    elif run_shown is not None and run_changes(analysis, run_shown):
        states["results"] = "stale"
    elif _active(run):
        states["results"] = "running"
    elif run_shown is None:
        states["results"] = "attention" if run is not None else "todo"
    else:
        states["results"] = "done"

    if qc_shown is None and run_shown is None:
        states["files"] = "locked"
    elif "stale" in (states["quality"], states["results"]):
        states["files"] = "stale"
    else:
        states["files"] = "done"
    return states


def sections(analysis: Station, current: str) -> list[Section]:
    """The tabs, with ``current`` marked: Quality, Indices and Files, each with its state
    and its address (none while it is locked)."""
    states = section_states(analysis)
    out = []
    for key, label, url_name in SECTIONS:
        state = states[key]
        url = None if state == "locked" else analysis.url(url_name)
        wrong = qc_verdict(analysis, shown_qc(analysis))[1] if state in VERDICTS else 0
        out.append(Section(key, str(label), url, state, key == current, wrong))
    return out


def ordered_stations(analysis: Station) -> list[Station]:
    """The stations of the analysis's workspace in the order they were added (the
    overview's order, #234)."""
    return list(
        analysis.workspace.stations.filter(owner=analysis.owner).order_by(
            "created_at", "station_name", "pk"
        )
    )


def workspace_page(analysis: Station) -> dict | None:
    """The workspace's own page in the breadcrumb, as {label, url}: its overview,
    ``/w/<id>/`` (#256, #234). None for a workspace of one station, which that address
    opens straight away."""
    if analysis.workspace.stations.filter(owner=analysis.owner).count() < 2:
        return None
    space = analysis.workspace
    return {"label": space.display_name, "url": space.get_absolute_url()}


def station_nav(analysis: Station) -> dict:
    """The context bar's way round a workspace of several stations (#234): the breadcrumb
    (the workspace, then "Station 2 of 6") and the previous and next station, each at its
    furthest section. A workspace of one station has none, and "Add stations" instead
    (``single_station``)."""
    stations = ordered_stations(analysis)
    if len(stations) < 2:
        return {"breadcrumb": [], "step_previous": None, "step_next": None, "single_station": True}
    position = next((i for i, s in enumerate(stations) if s.pk == analysis.pk), 0)
    space = analysis.workspace

    def step(station):
        if station is None:
            return None
        return {"label": station.station_name or station.file_name, "url": home_url(station)}

    label = _("Station %(n)s of %(count)s") % {"n": position + 1, "count": len(stations)}
    return {
        "breadcrumb": [
            {"label": space.display_name, "url": space.get_absolute_url()},
            {"label": label},
        ],
        "step_previous": step(stations[position - 1] if position > 0 else None),
        "step_next": step(stations[position + 1] if position + 1 < len(stations) else None),
        "single_station": False,
    }


def home_url(analysis: Station) -> str:
    """The station's own address leads to the furthest section it has reached."""
    if committed(analysis):
        name = "results"
    elif set_up(analysis):
        name = "qc"
    else:
        name = "setup"
    return analysis.url(name)


def set_up(analysis: Station) -> bool:
    """Whether the first visit's details are done (#198): the details confirmed, complete
    and fitting the data, so the sections and the Inputs panel show. Until then the
    station's address leads to the New station page (``stations:setup``, #201)."""
    return analysis.reached(Step.QC) and analysis.station_file.is_file() and details_valid(analysis)


def context(analysis: Station, current: str, path: str = "") -> dict:
    """The workspace's context: the context bar's ``workspace_tabs``, ``workspace_current``
    and ``provenance``, its breadcrumb and previous and next station (:func:`station_nav`),
    ``data_page`` (the page uses the width, #227),
    and the Inputs panel (``inputs``, ``input_sheets``, ``input_runs``; :func:`inputs_panel`)
    once the station is set up. ``path`` is the page's address, where an edit returns."""
    out = {
        "workspace_tabs": sections(analysis, current),
        "workspace_current": current,
        "provenance": provenance(analysis, current),
        "data_page": True,  # base.html: the page uses the whole window (#227, #263)
        **station_nav(analysis),
    }
    if current != "setup" and set_up(analysis):
        from climpact_web.stations.views import sheet_context

        out["copy_url"] = analysis.url("copy")  # Copy to workspace… (#241)
        out.update(inputs_panel(analysis, path))
        out["input_sheets"] = [sheet_context(analysis, key) for key in sheet_keys(analysis)]
    return out


def core_version() -> str:
    """The version of the climpact package that calculates, for the provenance line."""
    try:
        return version("climpact")
    except PackageNotFoundError:  # pragma: no cover - the core is always installed
        return ""


def years_text(first, last) -> str:
    """A station's years and how many they are: "1936–2015 · 80 yr"."""
    years = int(last) - int(first) + 1
    return ngettext(
        "%(first)s–%(last)s · %(years)s yr", "%(first)s–%(last)s · %(years)s yr", years
    ) % {"first": first, "last": last, "years": years}


def provenance(analysis: Station, current: str = "") -> list[dict]:
    """The context bar's provenance line (#227): where and when the data are from and what
    made the results: the coordinates, the years ("1936–2015 · 80 yr"), the base period,
    whether the quality thresholds and index settings are the defaults, and the climpact
    version. Quality's line describes the data the checks read instead (#235, the Quality
    board): the coordinates, the years, the days and variables in the file
    ("21,915 days · PR TX TN") and the file's name. Each part is ``{"text", "phone"}``;
    on a phone only the years show. Each line describes the file its section's shown
    job read (#269), which, while that job is out of date, may not be the current one."""
    if current == "quality":
        return quality_provenance(analysis)
    inputs = provenance_inputs(analysis, current)
    meta = inputs["metadata"]
    parts = []
    data = inputs["data"]
    first, last = data.get("first_year"), data.get("last_year")
    complete = analysis.metadata_complete
    if complete:
        parts.append(
            {"text": numbers.coordinates(meta["latitude"], meta["longitude"]), "phone": False}
        )
    if first and last:
        parts.append({"text": years_text(first, last), "phone": True})
    if complete:
        base = _("base %(start)s–%(end)s") % {
            "start": meta["base_start"],
            "end": meta["base_end"],
        }
        parts.append({"text": base, "phone": False})
    if set_up(analysis):
        custom = thresholds_count(inputs["qc"]) + settings_count(inputs["settings"])
        if custom:
            settings = ngettext(
                "%(count)s setting not the default", "%(count)s settings not the default", custom
            ) % {"count": custom}
        else:
            settings = _("ET-SCI defaults")
        parts.append({"text": settings, "phone": False})
    if found := core_version():
        parts.append({"text": f"climpact {found}", "phone": False})
    return parts


def provenance_inputs(analysis: Station, current: str = "") -> dict:
    """The inputs the provenance line describes (:func:`current_inputs` form): those of
    the results on the page. On the Indices, an index's page and Files (``results``,
    ``files``) they are the shown run's while it is out of date (#223): after a change
    the page still shows the old results, so the line must not claim the new inputs
    for them (the Inputs panel and bar show the new values, "· changed"), nor the new
    file's years (#269). An input the run did not record (a batch's results without
    settings, a job from before #269 without ``data``) is the current one."""
    inputs = current_inputs(analysis)
    if current in ("results", "files"):
        shown = shown_run(analysis)
        if shown is not None and run_changes(analysis, shown):
            _use_recorded(
                inputs, recorded_inputs(analysis, shown), ("data", "metadata", "qc", "settings")
            )
    return inputs


def _use_recorded(inputs: dict, recorded: dict, keys) -> None:
    """Put the inputs ``keys`` a job recorded in place of the current ones in ``inputs``."""
    for key in keys:
        if recorded.get(key):
            inputs[key] = recorded[key]


def quality_data(analysis: Station) -> dict:
    """The file Quality's checks read (:func:`file_record` form): the shown checks' record
    while they are out of date (#269), so after "Replace file" the old checks, kept under
    the out-of-date banner until the new ones have finished, are not described by the new
    file. The current file's when the checks recorded none (a job from before #269)."""
    inputs = current_inputs(analysis)
    shown = shown_qc(analysis)
    if shown is not None and qc_changes(analysis, shown):
        _use_recorded(inputs, recorded_inputs(analysis, shown), ("data",))
    return inputs["data"]


def quality_provenance(analysis: Station) -> list[dict]:
    """Quality's provenance line (#235): what the checks read."""
    parts = []
    data = quality_data(analysis)
    if analysis.metadata_complete:
        parts.append(
            {"text": numbers.coordinates(analysis.latitude, analysis.longitude), "phone": False}
        )
    first, last = data.get("first_year"), data.get("last_year")
    if first and last:
        parts.append({"text": years_text(first, last), "phone": True})
    if days := data.get("days"):
        codes = {"prcp": _("PR"), "tmax": _("TX"), "tmin": _("TN")}
        present = [str(codes[key]) for key in data.get("variables", []) if key in codes]
        text = ngettext("%(n)s day", "%(n)s days", days) % {"n": numbers.grouped(days)}
        if present:
            text = _("%(days)s · %(variables)s") % {"days": text, "variables": " ".join(present)}
        parts.append({"text": text, "phone": False})
    if data.get("name"):
        parts.append({"text": data["name"], "phone": False})
    return parts


# ---- the Inputs panel (#198) -------------------------------------------------------------

# The panel's inputs: each with the names of :func:`differences` it covers. Each is edited
# in a side sheet (``stations:edit_input``; the thresholds and index settings since #199).
PANEL_INPUTS = (
    ("file", gettext_lazy("File"), ("file",)),
    ("station", gettext_lazy("Station"), ("name", "location")),
    ("base-period", gettext_lazy("Base period"), ("base_period",)),
    ("thresholds", gettext_lazy("Quality thresholds"), ("qc",)),
    ("settings", gettext_lazy("Index settings"), ("settings",)),
)
SHEETS = tuple(key for key, _label, _names in PANEL_INPUTS)


def sheet_keys(analysis: Station) -> tuple[str, ...]:
    """The sheets the station's pages have: all of them once the data is in use; before
    "See results" not the index settings, which only the results use (#198)."""
    if committed(analysis):
        return SHEETS
    return tuple(key for key in SHEETS if key != "settings")


def affected(names) -> list[str]:
    """The sections a change to the inputs ``names`` updates: Quality if the checks depend on
    one of them, Indices if the run does, and Files with either."""
    out = []
    if any(n in QC_INPUTS for n in names):
        out.append("quality")
    if any(n in RUN_INPUTS for n in names):
        out.append("results")
    if out:
        out.append("files")
    return out


def impact_sentence(names) -> str:
    """What applying a change to ``names`` updates, in words, from :func:`affected`."""
    sections_ = affected(names)
    if "quality" in sections_ and "results" in sections_:
        return _("Updates Quality, Indices and Files.")
    if "results" in sections_:
        return _("Updates Indices and Files. Quality stays as it is.")
    return _("Updates Quality and Files. Indices stay as they are.")


# The sheets of the workspace's settings (#254): a change applies to every station.
WORKSPACE_SHEETS = ("base-period", "thresholds", "settings")


def impact(key: str, analysis: Station | None = None) -> list[str]:
    """What the sheet of input ``key`` says applying will update (#198); for a setting of
    a workspace of several stations, that it applies to all of them (#254), and for every
    setting, that the change can be undone while it is recalculated."""
    names = dict((k, n) for k, _label, n in PANEL_INPUTS)[key]
    if key == "station":
        sentences = [
            impact_sentence(("location",)),
            _("A new station name updates Quality too, as its files are named after it."),
        ]
    else:
        sentences = [impact_sentence(names)]
    if key in WORKSPACE_SHEETS and analysis is not None:
        count = analysis.workspace.stations.count()
        if count > 1:
            sentences.append(
                ngettext(
                    "It applies to the %(count)s station of this workspace.",
                    "It applies to all %(count)s stations of this workspace.",
                    count,
                )
                % {"count": count}
            )
    if key == "file":
        sentences.append(_("The station details and thresholds are kept."))
    elif key == "settings":
        sentences.append(_("About half a minute for 80 years of data."))
    sentences.append(_("What is shown now stays until its replacement is ready."))
    if key in WORKSPACE_SHEETS:
        sentences.append(_("You can undo the change until then."))
    return sentences


def changed_inputs(analysis: Station) -> set[str]:
    """The inputs (names of :func:`differences`) changed since the checks or the results
    shown were produced: the panel highlights them."""
    names = set(qc_changes(analysis, shown_qc(analysis)))
    names.update(run_changes(analysis, shown_run(analysis)))
    return names


def thresholds_changed(analysis: Station) -> int:
    """How many of the quality-control thresholds differ from R's defaults."""
    return thresholds_count(qc_values(analysis))


def thresholds_count(values: dict) -> int:
    """How many of the quality-control thresholds ``values`` differ from R's defaults."""
    from climpact_web.stations.forms import QC_DEFAULTS

    return sum(1 for key, default in QC_DEFAULTS.items() if values.get(key) != default)


def base_period_text(workspace_) -> str:
    """A workspace's base period: "1971–2000"."""
    return f"{workspace_.base_start}–{workspace_.base_end}"


def settings_changed(analysis: Station) -> int:
    """How many of the station's index settings and output options (its workspace's, with
    its own index values) differ from the defaults: each parameter, the custom index, a
    plot title of the user's, and each of the plots, zip and report switched off. From the
    settings form's defaults, without importing the core."""
    return settings_count(station_settings(analysis))


def settings_count(settings: dict) -> int:
    """How many of ``settings`` (:func:`settings_of` form) differ from the defaults: see
    :func:`settings_changed`."""
    from climpact_web.stations.forms_indices import PARAM_FIELDS, IndexParamsForm

    params = settings.get("params") or {}
    plot_title = settings.get("plot_title") or ""
    plots, zip_, report = (bool(settings.get(k, True)) for k in ("plots", "zip", "report"))
    fields = IndexParamsForm.base_fields
    count = sum(
        1 for name in PARAM_FIELDS if name in params and params[name] != fields[name].initial
    )
    default_custom = {
        key: fields[f"custom_{key}"].initial for key in ("variable", "operator", "threshold")
    }
    if "custom" in params and params["custom"] != default_custom:
        count += 1
    count += bool(plot_title) + (not plots) + (not zip_) + (not report)
    return count


def changed_text(count: int) -> str:
    """A panel summary: "Defaults", or how many values were changed."""
    if not count:
        return _("Defaults")
    return ngettext("%(count)s changed", "%(count)s changed", count) % {"count": count}


@dataclass
class PanelInput:
    key: str
    label: str
    value: str
    edit_url: str
    edit_label: str
    changed: bool


@dataclass
class PanelRun:
    key: str  # "qc" or "run"
    label: str
    job: Job


def sheet_url(analysis: Station, key: str, path: str = "") -> str:
    """The address of the sheet ``key`` as a page (``stations:edit_input``), where its Edit
    leads without JavaScript; ``path``, where applying returns."""
    from django.utils.http import urlencode

    url = analysis.url("edit_input", key)
    return f"{url}?{urlencode({'next': path})}" if path else url


def inputs_panel(analysis: Station, path: str = "") -> dict:
    """The Inputs panel (#198): each input with its value, its edit link and whether it
    changed since what is shown; the checks and run under way for the new inputs; and
    each sheet's page by key (``input_urls``), for the links on the page that open a
    sheet (``components/button.html``'s ``sheet``, #199)."""
    from django.utils.formats import number_format

    summary = analysis.summary or {}
    days = summary.get("days") or 0
    count = len(summary.get("variables") or [])
    changed = changed_inputs(analysis)
    custom = {"thresholds": thresholds_changed(analysis), "settings": settings_changed(analysis)}
    values = {
        "file": _("%(days)s days · %(count)s variables")
        % {"days": number_format(days, force_grouping=True), "count": count},
        "station": numbers.coordinates(analysis.latitude, analysis.longitude),
        "base-period": base_period_text(analysis.workspace),
        "thresholds": changed_text(custom["thresholds"]),
        "settings": changed_text(custom["settings"]),
    }
    sheets = sheet_keys(analysis)
    items = []
    for key, label, names in PANEL_INPUTS:
        # No Edit for the index settings before "See results": only the results use them.
        url = sheet_url(analysis, key, path) if key in sheets else ""
        items.append(
            PanelInput(
                key=key,
                label=str(label),
                value=values[key],
                edit_url=url,
                edit_label=_("Replace") if key == "file" else _("Edit"),
                changed=bool(changed.intersection(names)),
            )
        )
    runs = []
    if _active(analysis.qc_job):
        runs.append(PanelRun("qc", _("Checking quality"), analysis.qc_job))
    if committed(analysis) and _active(analysis.indices_job):
        label = _("Recalculating") if shown_run(analysis) else _("Calculating the indices")
        runs.append(PanelRun("run", label, analysis.indices_job))
    urls = {item.key: item.edit_url for item in items if item.edit_url}
    bar = inputs_bar(values["base-period"], sum(custom.values()), items, runs)
    return {
        "inputs": items,
        "input_runs": runs,
        "input_next": path,
        "input_urls": urls,
        "inputs_bar": bar,
        # "Undo the change" beside the runs while a change to the settings can be undone.
        "input_undo": bool(runs) and undo_available(analysis.workspace),
    }


def inputs_bar(base_period: str, custom: int, items: list, runs: list) -> dict:
    """The Inputs panel as one line, on phones (#203, proposal 7): the base period and
    whether the thresholds and index settings are the defaults ("1971–2000 · defaults"),
    then each input changed since what is shown and each run under way, so the bar still
    says what the panel's highlights and progress say."""
    if custom:
        settings = ngettext(
            "%(count)s setting not the default", "%(count)s settings not the default", custom
        ) % {"count": custom}
    else:
        settings = _("defaults")
    return {
        "summary": f"{base_period} · {settings}",
        "changed": [
            _("%(input)s changed") % {"input": item.label} for item in items if item.changed
        ],
        "runs": [str(run.label) for run in runs],
    }

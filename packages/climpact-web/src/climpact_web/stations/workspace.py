"""The station workspace (#179): what each section shows, and whether it is out of date.

A station's pages are three sections, Quality, Results and Files, shown as tabs under the
station's name, beside the Inputs panel (#198), which lists what the user gave and opens
each in a side sheet to change it (:func:`inputs_panel`). A change to an input no longer
resets the later sections. Each job records the inputs it was produced from when it is
queued (``Job.inputs``):

``file``      the SHA-256 of the station file (``StationAnalysis.file_hash``)
``metadata``  the station details: name, latitude, longitude and base period
``qc``        the quality-control thresholds, with R's defaults filled in
``settings``  a station run's index settings and output options (:func:`settings_of`)

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

from dataclasses import dataclass

from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from climpact_web.jobs.models import Job, Status
from climpact_web.stations.models import StationAnalysis, Step

# The ``params`` key of a job that names the finished job of the same kind whose results
# stay on the page, out of date, until this one has finished.
REPLACES = "replaces"

# The inputs each kind of job depends on, by name (see :func:`differences`).
QC_INPUTS = ("file", "name", "qc")
RUN_INPUTS = ("file", "name", "location", "base_period", "qc", "settings")


# ---- inputs ------------------------------------------------------------------------------


def qc_values(analysis: StationAnalysis) -> dict:
    """The analysis's quality-control thresholds, with R's defaults for those not set."""
    from climpact_web.stations.forms import QCParamsForm

    return QCParamsForm.initial_for(analysis.qc_params)


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


def current_inputs(analysis: StationAnalysis) -> dict:
    """The analysis's inputs now: its file, station details and thresholds."""
    return {"file": analysis.file_hash, "metadata": analysis.metadata, "qc": qc_values(analysis)}


def job_inputs(analysis: StationAnalysis, kind: str, params: dict) -> dict:
    """The inputs to record on a job of ``kind`` queued now with ``params``."""
    inputs = current_inputs(analysis)
    if kind == "station":
        inputs["settings"] = settings_of(params)
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


def replaced_job(analysis: StationAnalysis, job: Job | None) -> Job | None:
    """The finished job of the same kind that ``job`` replaces, while it is still kept."""
    job_id = (job.params or {}).get(REPLACES) if job is not None else None
    if not job_id:
        return None
    return Job.objects.filter(
        pk=job_id, owner=analysis.owner, kind=job.kind, status=Status.SUCCEEDED
    ).first()


def shown_qc(analysis: StationAnalysis) -> Job | None:
    """The finished checks Quality shows: the analysis's ``qc`` job, or, while a check of
    new inputs is queued, running or has failed, the one it replaces."""
    job = analysis.qc_job
    if job is None or job.status == Status.SUCCEEDED:
        return job
    return replaced_job(analysis, job)


def committed(analysis: StationAnalysis) -> bool:
    """Whether the user has chosen to use the data ("Use this data"), or opened the station
    from a batch's results. Before that, Results are not shown, nor is the speculative run
    (#178) anywhere, Files included."""
    return analysis.reached(Step.INDICES) or bool(analysis.origin)


def batch_job(analysis: StationAnalysis) -> Job | None:
    """The finished batch job an analysis was opened from, if it is still kept."""
    job_id = (analysis.origin or {}).get("job")
    if not job_id:
        return None
    return Job.objects.filter(pk=job_id, owner=analysis.owner, status=Status.SUCCEEDED).first()


def shown_run(analysis: StationAnalysis) -> Job | None:
    """The finished run Results show: the analysis's own, or the one a newer run replaces,
    or the batch's; None before "Use this data", or while the first run is going on."""
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


def restore_if_cancelled(analysis: StationAnalysis) -> None:
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


def wanted_run_inputs(analysis: StationAnalysis) -> dict:
    """The inputs the results should have now: the analysis's, with the settings of the
    latest run asked for (a recalculation's new settings, #178)."""
    wanted = current_inputs(analysis)
    latest = analysis.indices_job
    if latest is not None and "settings" in (latest.inputs or {}):
        wanted["settings"] = latest.inputs["settings"]
    return wanted


def recorded_inputs(analysis: StationAnalysis, job: Job | None) -> dict:
    """What ``job`` was produced from: its own record, or a batch's ``origin["inputs"]``."""
    if job is None:
        return {}
    if job.kind == "batch":
        return (analysis.origin or {}).get("inputs") or {}
    return job.inputs or {}


def qc_changes(analysis: StationAnalysis, job: Job | None) -> list[str]:
    """The inputs that changed since the checks ``job`` ran."""
    return differences(recorded_inputs(analysis, job), current_inputs(analysis), QC_INPUTS)


def run_changes(analysis: StationAnalysis, job: Job | None) -> list[str]:
    """The inputs that changed since the run ``job`` (the shown results) was made."""
    return differences(recorded_inputs(analysis, job), wanted_run_inputs(analysis), RUN_INPUTS)


def pending_changes(analysis: StationAnalysis, job: Job | None, kind: str) -> list[str]:
    """For the job a section links to (the latest asked for): the inputs it is not of, so
    a new one must be queued. Settings are not compared: the latest run sets them."""
    if job is None:
        return []
    names = QC_INPUTS if kind == "qc" else RUN_INPUTS[:-1]
    return differences(recorded_inputs(analysis, job), current_inputs(analysis), names)


def settle(analysis: StationAnalysis) -> None:
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


def details_valid(analysis: StationAnalysis) -> bool:
    """Whether the saved station details are complete and fit the data."""
    from climpact_web.stations.forms import MetadataForm

    if not analysis.metadata_complete:
        return False
    data = {
        "station_name": analysis.station_name,
        "latitude": analysis.latitude,
        "longitude": analysis.longitude,
        "base_start": analysis.base_start,
        "base_end": analysis.base_end,
    }
    return MetadataForm(data, summary=analysis.summary).is_valid()


def change_sentences(analysis: StationAnalysis, job: Job | None, changes: list[str]) -> list:
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
                    "new": f"{analysis.base_start}–{analysis.base_end}",
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
# colour (DESIGN.md, "Don't use colour alone").
STATES = {
    "done": (gettext_lazy("Done"), "check-circle", False),
    "attention": (gettext_lazy("Needs attention"), "warning", True),
    "stale": (gettext_lazy("Out of date"), "clock", True),
    "running": (gettext_lazy("Running"), "refresh", True),
    "todo": (gettext_lazy("Not started"), "circle", False),
    "locked": (gettext_lazy("Not available yet"), "lock", False),
}

SECTIONS = (
    ("quality", gettext_lazy("Quality"), "stations:qc"),
    ("results", gettext_lazy("Results"), "stations:results"),
    ("files", gettext_lazy("Files"), "stations:downloads"),
)


@dataclass
class Section:
    key: str
    label: str
    url: str | None  # None while the section is not available yet
    state: str
    current: bool = False

    @property
    def state_label(self) -> str:
        return STATES[self.state][0]

    @property
    def icon(self) -> str:
        return STATES[self.state][1]

    @property
    def word_shown(self) -> bool:
        return STATES[self.state][2]


def _active(job: Job | None) -> bool:
    return job is not None and job.status in (Status.QUEUED, Status.RUNNING)


def section_states(analysis: StationAnalysis) -> dict[str, str]:
    """Each section's state: done, attention (needs the user), stale (out of date),
    running, todo (not started) or locked (its input does not exist yet)."""
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
        states["quality"] = "running"
    elif qc_job is None:
        states["quality"] = "todo"
    elif qc_shown is None or qc_shown != qc_job:
        states["quality"] = "attention"  # the checks failed or were stopped
    elif (qc_shown.result or {}).get("verdict") == "fix":
        states["quality"] = "attention"
    else:
        states["quality"] = "done"

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


def sections(analysis: StationAnalysis, current: str) -> list[Section]:
    """The tabs, with ``current`` marked: Quality, Results and Files, each with its state
    and its address (none while it is locked)."""
    states = section_states(analysis)
    out = []
    for key, label, url_name in SECTIONS:
        state = states[key]
        url = None if state == "locked" else reverse(url_name, args=[analysis.pk])
        out.append(Section(key, str(label), url, state, key == current))
    return out


def home_url(analysis: StationAnalysis) -> str:
    """The workspace's own address leads to the furthest section it has reached."""
    if committed(analysis):
        name = "stations:results"
    elif set_up(analysis):
        name = "stations:qc"
    else:
        name = "stations:load"
    return reverse(name, args=[analysis.pk])


def set_up(analysis: StationAnalysis) -> bool:
    """Whether the first visit's details are done (#198): the details confirmed, complete
    and fitting the data, so the sections and the Inputs panel show. Until then the
    station's address leads to the details page (``stations:load``)."""
    return analysis.reached(Step.QC) and analysis.station_file.is_file() and details_valid(analysis)


def context(analysis: StationAnalysis, current: str, path: str = "") -> dict:
    """The workspace's context: the header's ``workspace_tabs`` and ``workspace_current``,
    and the Inputs panel (``inputs``, ``input_sheets``, ``input_runs``; :func:`inputs_panel`)
    once the station is set up. ``path`` is the page's address, where an edit returns."""
    out = {"workspace_tabs": sections(analysis, current), "workspace_current": current}
    if current != "setup" and set_up(analysis):
        from climpact_web.stations.views import sheet_context

        out.update(inputs_panel(analysis, path))
        out["input_sheets"] = [sheet_context(analysis, key) for key in sheet_keys(analysis)]
    return out


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


def sheet_keys(analysis: StationAnalysis) -> tuple[str, ...]:
    """The sheets the station's pages have: all of them once the data is in use; before
    "Use this data" not the index settings, which only the results use (#198)."""
    if committed(analysis):
        return SHEETS
    return tuple(key for key in SHEETS if key != "settings")


def affected(names) -> list[str]:
    """The sections a change to the inputs ``names`` updates: Quality if the checks depend on
    one of them, Results if the run does, and Files with either."""
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
        return _("Updates Quality, Results and Files.")
    if "results" in sections_:
        return _("Updates Results and Files. Quality stays as it is.")
    return _("Updates Quality and Files. Results stay as they are.")


def impact(key: str) -> list[str]:
    """What the sheet of input ``key`` says applying will update (#198)."""
    names = dict((k, n) for k, _label, n in PANEL_INPUTS)[key]
    if key == "station":
        sentences = [
            impact_sentence(("location",)),
            _("A new station name updates Quality too, as its files are named after it."),
        ]
    else:
        sentences = [impact_sentence(names)]
    if key == "file":
        sentences.append(_("The station details and thresholds are kept."))
    elif key == "settings":
        sentences.append(_("About half a minute for 80 years of data."))
    sentences.append(_("What is shown now stays until its replacement is ready."))
    return sentences


def changed_inputs(analysis: StationAnalysis) -> set[str]:
    """The inputs (names of :func:`differences`) changed since the checks or the results
    shown were produced: the panel highlights them."""
    names = set(qc_changes(analysis, shown_qc(analysis)))
    names.update(run_changes(analysis, shown_run(analysis)))
    return names


def thresholds_changed(analysis: StationAnalysis) -> int:
    """How many of the quality-control thresholds differ from R's defaults."""
    from climpact_web.stations.forms import QC_DEFAULTS

    values = qc_values(analysis)
    return sum(1 for key, default in QC_DEFAULTS.items() if values.get(key) != default)


def settings_changed(analysis: StationAnalysis) -> int:
    """How many index settings and output options of the latest run asked for (or the
    batch's) differ from the defaults: each parameter, the custom index, a plot title of
    the user's, and each of the plots, zip and report switched off. From the settings
    form's defaults, without importing the core."""
    from climpact_web.stations.calculation import previous_params
    from climpact_web.stations.forms_indices import PARAM_FIELDS, IndexParamsForm

    params, plot_title, plots, zip_, report, _source = previous_params(analysis)
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


def sheet_url(analysis: StationAnalysis, key: str, path: str = "") -> str:
    """The address of the sheet ``key`` as a page (``stations:edit_input``), where its Edit
    leads without JavaScript; ``path``, where applying returns."""
    from django.utils.http import urlencode

    url = reverse("stations:edit_input", args=[analysis.pk, key])
    return f"{url}?{urlencode({'next': path})}" if path else url


def inputs_panel(analysis: StationAnalysis, path: str = "") -> dict:
    """The Inputs panel (#198): each input with its value, its edit link and whether it
    changed since what is shown; the checks and run under way for the new inputs; and
    each sheet's page by key (``input_urls``), for the links on the page that open a
    sheet (``components/button.html``'s ``sheet``, #199)."""
    from django.utils.formats import number_format

    summary = analysis.summary or {}
    days = summary.get("days") or 0
    count = len(summary.get("variables") or [])
    changed = changed_inputs(analysis)
    values = {
        "file": _("%(days)s days · %(count)s variables")
        % {"days": number_format(days, force_grouping=True), "count": count},
        "station": f"{analysis.latitude:g}°, {analysis.longitude:g}°",
        "base-period": f"{analysis.base_start}–{analysis.base_end}",
        "thresholds": changed_text(thresholds_changed(analysis)),
        "settings": changed_text(settings_changed(analysis)),
    }
    sheets = sheet_keys(analysis)
    items = []
    for key, label, names in PANEL_INPUTS:
        # No Edit for the index settings before "Use this data": only the results use them.
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
    return {"inputs": items, "input_runs": runs, "input_next": path, "input_urls": urls}

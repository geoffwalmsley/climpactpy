"""Steps 3 and 4 of a station (#78): the index parameters, the calculation as a job, the
results dashboard and each index's own page (step 5 is in ``views_sector``).

URLs (all ``/station/<id>/...``, private to the session like the other steps):

``indices``                 the parameters form (GET, POST queues the job)
``indices/validate``        htmx: one group of fields checked as it changes
``results``                 progress while the job runs, then the dashboard
``results/progress``        htmx: the progress fragment; when the job ends it reloads the
                            page (or opens the index the user came from)
``results/<key>``           one index: chart, trend, anomalies, tables, downloads
``results/<series>/anomalies.json``  the standardised anomalies, for the chart

Step 3 works whether or not the quality checks (#77) have been run, as R lets you go on.
The results come from the analysis's ``indices_job``; an analysis opened from a batch's
results (#80, ``origin``) shows the batch's outputs for that station until it is
calculated again here.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.core.files import File
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.gzip import gzip_page
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from climpact_web.core.limits import human_required
from climpact_web.core.navigation import station_steps
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.stages import stage_label
from climpact_web.jobs.views import create_job, progress_context
from climpact_web.stations import results as results_model
from climpact_web.stations.forms import QCParamsForm
from climpact_web.stations.forms_indices import IndexParamsForm, initial_from_params
from climpact_web.stations.models import STATION_FILE, StationAnalysis, Step
from climpact_web.stations.views import get_analysis

INDEX_KEY_MAX = 100


def _station_title(analysis: StationAnalysis) -> str:
    """The plots' default title: R's ``title.station`` (the core's ``station_title``)."""
    from climpact.config import StationMetadata
    from climpact.plots import station_title

    return station_title(
        StationMetadata(analysis.station_name, analysis.latitude or 0.0, analysis.longitude or 0.0)
    )


def _ready(analysis: StationAnalysis) -> bool:
    return (
        analysis.metadata_complete and analysis.reached(Step.QC) and analysis.station_file.is_file()
    )


def batch_job(analysis: StationAnalysis) -> Job | None:
    """The finished batch job an analysis was opened from, if it is still kept."""
    job_id = (analysis.origin or {}).get("job")
    if not job_id:
        return None
    job = Job.objects.filter(pk=job_id, owner=analysis.owner, status=Status.SUCCEEDED).first()
    return job


def batch_custom(job: Job | None) -> dict | None:
    return (job.params or {}).get("custom") if job is not None else None


def previous_params(analysis: StationAnalysis) -> tuple[dict, str, bool, bool, bool, str]:
    """The parameters to start the form from: the last calculation's, else the batch
    station's (``origin``), else the defaults. Returns (params, plot title, plots, zip,
    report, where they come from)."""
    job = analysis.indices_job
    if job is not None and job.kind == "station":
        p = job.params or {}
        return (
            p.get("params") or {},
            p.get("plot_title") or "",
            bool(p.get("plots", True)),
            bool(p.get("zip", True)),
            bool(p.get("report", True)),
            "job",
        )
    origin = analysis.origin or {}
    if origin.get("params"):
        params = dict(origin["params"])
        params["custom"] = batch_custom(batch_job(analysis))
        return params, "", True, True, True, "batch"
    return {}, "", True, True, True, "default"


# ---- step 3: the parameters ------------------------------------------------------------


def indices_context(analysis, form, source: str) -> dict:
    job = analysis.indices_job
    return {
        "analysis": analysis,
        "form": form,
        "names": output_names(form),
        "source": source,
        "steps": station_steps("indices", analysis.step_urls()),
        "has_results": job is not None or bool(batch_job(analysis)),
        "qc_done": analysis.qc_job is not None and analysis.qc_job.status == Status.SUCCEEDED,
        "job": job,
    }


def output_names(form: IndexParamsForm) -> dict[str, str]:
    """The file names of the parameterised indices, from what the form shows."""
    if form.is_bound:
        return form.output_names()
    data = {}
    for name, field in form.fields.items():
        value = form.initial.get(name, field.initial)
        if isinstance(value, bool):
            if value:
                data[name] = "on"
        elif value is not None:
            data[name] = value
    shown = IndexParamsForm(data)
    shown.is_valid()
    return shown.output_names()


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def indices(request, analysis_id):
    """Step 3: the index parameters, then "Calculate indices" queues a station job."""
    analysis = get_analysis(request, analysis_id)
    if not _ready(analysis):
        return redirect("stations:load", analysis_id=analysis.pk)
    title = _station_title(analysis)
    params, plot_title, plots, zip_, report, source = previous_params(analysis)
    if request.method == "POST":
        form = IndexParamsForm(request.POST, station_title=title)
        if form.is_valid():
            job = queue_indices(request, analysis, form)
            url = reverse("stations:results", args=[analysis.pk])
            index = form.cleaned_data.get("index", "")[:INDEX_KEY_MAX]
            if index:
                url += "?" + urlencode({"index": index})
            return redirect(url) if job else redirect("stations:load", analysis_id=analysis.pk)
    else:
        initial = initial_from_params(params, plot_title, plots, zip_, report)
        initial["index"] = request.GET.get("index", "")[:INDEX_KEY_MAX]
        form = IndexParamsForm(initial=initial, station_title=title)
    if analysis.step == Step.QC:
        analysis.advance_to(Step.INDICES)
        analysis.save(update_fields=["step"])
    context = indices_context(analysis, form, source)
    # "Change the settings" on the results page asks for the settings open (#115), even
    # when the last run used the defaults and they would start closed.
    context["open_settings"] = request.method != "POST" and request.GET.get("settings") == "open"
    return render(request, "stations/indices.html", context)


def queue_indices(request, analysis: StationAnalysis, form: IndexParamsForm) -> Job | None:
    if not analysis.station_file.is_file():
        return None
    data = form.cleaned_data
    params = {
        "station_file": STATION_FILE,
        "metadata": analysis.metadata,
        "params": form.job_params(),
        "qc": QCParamsForm.initial_for(analysis.qc_params),  # step 2's thresholds (#77)
        "plot_title": data["plot_title"],
        "plots": data["plots"],
        "zip": data["zip"],
        "report": data["report"],
    }
    with analysis.station_file.open("rb") as handle:
        job = create_job(
            request, "station", params, {STATION_FILE: File(handle)}, title=analysis.station_name
        )
    analysis.indices_job = job
    analysis.advance_to(Step.RESULTS)
    analysis.touch()
    analysis.save()
    return job


@require_POST
def indices_validate(request, analysis_id):
    """htmx: one group of fields checked as it changes, returned on its own with the name
    its index will be written under."""
    analysis = get_analysis(request, analysis_id)
    unit = request.POST.get("group", "")
    if unit not in IndexParamsForm.UNITS:
        return HttpResponseBadRequest()
    form = IndexParamsForm(request.POST, station_title=_station_title(analysis))
    form.is_valid()
    context = {"form": form, "group": unit, "analysis": analysis, "names": form.output_names()}
    return render(request, "stations/_indices_unit.html", context)


# ---- step 4: progress and the dashboard -------------------------------------------------

PHASES = ("read", "qc", "homogeneity", "indices", "write", "plots", "report", "zip")


def phases(job: Job) -> list[dict]:
    """The stages of a station run as a short list (done, current, pending), with the
    product being calculated named in the current one."""
    labels = {
        "read": _("Read the data"),
        "qc": _("Quality checks"),
        "homogeneity": _("Homogeneity"),
        "indices": _("Calculate the indices"),
        "write": _("Write the result files"),
        "plots": _("Draw the plots"),
        "report": _("Write the PDF report"),
        "zip": _("Make the zip file"),
    }
    wanted = [p for p in PHASES if p not in ("plots", "report", "zip") or job.params.get(p)]
    head = (job.stage or "").split(":")[0]
    current = wanted.index(head) if head in wanted else (-1 if job.status == Status.QUEUED else 0)
    out = []
    for i, key in enumerate(wanted):
        if job.status == Status.SUCCEEDED or i < current:
            state = "done"
        elif i == current:
            state = "failed" if job.status == Status.FAILED else "current"
        else:
            state = "pending"
        label = labels[key]
        if state == "current" and key in ("indices", "plots") and job.stage.count(":"):
            label = stage_label(job.stage)
        out.append({"label": label, "state": state})
    return out


def results_url(analysis, index: str = "") -> str:
    url = reverse("stations:results", args=[analysis.pk])
    return url + ("?" + urlencode({"index": index}) if index else "")


def current_source(analysis: StationAnalysis):
    """(job, RunSource or None): the analysis's own calculation, else its batch's."""
    job = analysis.indices_job
    if job is not None:
        if job.status != Status.SUCCEEDED:
            return job, None
        return job, results_model.run_source(job)
    bjob = batch_job(analysis)
    if bjob is not None:
        return bjob, results_model.run_source(bjob, analysis.origin.get("station"))
    return None, None


def load_results(analysis, source):
    return results_model.results_for(
        source, analysis.summary, (analysis.base_start, analysis.base_end)
    )


@never_cache
@require_safe
def results(request, analysis_id):
    """Step 4: the calculation's progress, then every index as a card."""
    analysis = get_analysis(request, analysis_id)
    job, source = current_source(analysis)
    if job is None:
        return redirect("stations:indices", analysis_id=analysis.pk)
    index = request.GET.get("index", "")[:INDEX_KEY_MAX]
    context = {
        "analysis": analysis,
        "job": job,
        "steps": station_steps("results", analysis.step_urls()),
        "index": index,
    }
    if source is None:
        if job.status == Status.SUCCEEDED:  # finished, but without index tables
            context["missing_outputs"] = True
        else:
            context.update(progress_context(request, job))
            context["phases"] = phases(job)
        return render(request, "stations/results_progress.html", context)
    run = load_results(analysis, source)
    if index:
        card = run.find(index)
        if card is not None:
            return redirect("stations:result", analysis_id=analysis.pk, key=card.key)
    if not analysis.reached(Step.RESULTS):
        analysis.advance_to(Step.RESULTS)
        analysis.save(update_fields=["step"])
    context.update(dashboard_context(request, analysis, source, run))
    return render(request, "stations/results.html", context)


@never_cache
@require_safe
def results_progress(request, analysis_id):
    """htmx: the progress fragment. Once the job has finished the page is reloaded (or the
    index the user came from opens), with ``HX-Redirect``."""
    analysis = get_analysis(request, analysis_id)
    job = analysis.indices_job
    if job is None:
        raise Http404
    if job.status == Status.RUNNING:
        from climpact_web.jobs.worker import reap_stale

        if reap_stale():
            job.refresh_from_db()
    if job.status == Status.SUCCEEDED:
        response = HttpResponse(status=204)
        response["HX-Redirect"] = results_url(
            analysis, request.GET.get("index", "")[:INDEX_KEY_MAX]
        )
        return response
    context = {**progress_context(request, job), "analysis": analysis, "phases": phases(job)}
    context["index"] = request.GET.get("index", "")[:INDEX_KEY_MAX]
    return render(request, "stations/_results_progress.html", context)


def params_summary(source) -> list[dict]:
    """The parameters the run used, for the dashboard."""
    p = source.params

    def days(n):
        return ngettext("%(n)s day", "%(n)s days", n) % {"n": n}

    def months(n):
        return ngettext("%(n)s month", "%(n)s months", n) % {"n": n}

    def unit(value, symbol):
        return f"{value:g} {symbol}"

    rows = [
        (_("Days for WSDId"), days(p.wsdi_days)),
        (_("Days for CSDId"), days(p.csdi_days)),
        (_("Days for Rxdday"), days(p.rx_days)),
        (_("Days for TXdTNd and TXbdTNbd"), days(p.txtn_days)),
        (_("Base temperature for HDDheat"), unit(p.hdd_base, "°C")),
        (_("Base temperature for CDDcold"), unit(p.cdd_base, "°C")),
        (_("Base temperature for GDDgrow"), unit(p.gdd_base, "°C")),
        (_("Precipitation amount for Rnnmm"), unit(p.rnnmm, _("mm"))),
        (_("Extra SPI and SPEI time scale"), months(p.spei_months)),
    ]
    out = [{"label": label, "value": value} for label, value in rows]
    custom = p.custom
    out.append(
        {
            "label": _("Custom threshold index"),
            "value": f"{custom.variable} {custom.operator} {custom.threshold:g} ({custom.name})"
            if custom
            else _("none"),
            "unit": "",
        }
    )
    return out


def downloads(source) -> dict:
    """The main downloads with their sizes, for the dashboard's downloads card; the
    downloads page (``stations:downloads``, #79) lists every file."""
    from climpact_web.stations.downloads import main_downloads, summary_downloads

    main = main_downloads(source)
    files = [d for d in (main["report"], main["all_plots"]) if d] + summary_downloads(source)
    return {"job": source.job, "zip": main["zip"], "report": main["report"], "files": files}


def dashboard_context(request, analysis, source, run) -> dict:
    q = request.GET.get("q", "").strip()[:100]
    family = request.GET.get("family", "")
    significant = request.GET.get("significant") == "1"
    families = results_model.families()
    if family not in dict(families):
        family = ""
    sections = run.sections()
    words = q.lower().split()
    filtering = bool(words or family or significant)
    # The "All indices" link of an index's page opens its group without JavaScript.
    group = request.GET.get("group", "")
    shown = 0
    for section in sections:
        for card in section["cards"]:
            card.hidden = bool(
                (family and card.family != family)
                or (significant and not card.significant)
                or any(w not in card.search_text for w in words)
            )
            shown += not card.hidden
        section["hidden"] = all(c.hidden for c in section["cards"])
        # Groups start collapsed, unless a filter shows what is in them or a link asks.
        section["open"] = not section["hidden"] and (filtering or section["key"] == group)
    counts = {key: sum(1 for c in run.cards if c.family == key) for key, _label in families}
    return {
        "source": source,
        "run": run,
        "sections": sections,
        "families": [(k, label, counts[k]) for k, label in families if counts[k]],
        "q": q,
        "family": family,
        "significant": significant,
        "filtering": filtering,
        "shown": shown,
        "total": len(run.cards),
        "significant_cards": run.significant(),
        "significant_count": sum(1 for c in run.cards if c.significant),
        "params": params_summary(source),
        "downloads": downloads(source),
        "from_batch": source.from_batch and analysis.indices_job is None,
    }


# ---- one index ---------------------------------------------------------------------------


@never_cache
@require_safe
def result(request, analysis_id, key):
    """One index: the chosen series as an interactive chart with its trend, its
    standardised anomalies, the trend file's rows, and downloads."""
    analysis = get_analysis(request, analysis_id)
    job, source = current_source(analysis)
    if job is None:
        return redirect("stations:indices", analysis_id=analysis.pk)
    if source is None:
        return redirect("stations:results", analysis_id=analysis.pk)
    run = load_results(analysis, source)
    card = run.card(key)
    if card is None:
        found = run.find(key)
        if found is None:
            raise Http404
        return redirect("stations:result", analysis_id=analysis.pk, key=found.key)
    names = [s.name for s in card.series]
    name = request.GET.get("series", card.main)
    if name not in names:
        name = card.main
    series = next(s for s in card.series if s.name == name)
    plot = run.plots.get(name)
    previous, following = run.neighbours(card)
    context = {
        "analysis": analysis,
        "job": job,
        "source": source,
        "card": card,
        "series": series,
        "steps": station_steps("results", analysis.step_urls()),
        "previous": previous,
        "next": following,
        "trend_rows": results_model.trend_rows(source, card.key) if not card.daily else [],
        "csv_path": source.table_file(name.removeprefix("day_of_")),
        "csv_size": _size(source.index_source.table_path(name.removeprefix("day_of_"))),
        "png_path": source.plot_file(name),
        "png_size": _size(source.station_dir / "plots" / f"{source.station}_{name}.png"),
        "from_batch": source.from_batch and analysis.indices_job is None,
        "chart_title": results_model.chart_title(card, series),
    }
    if plot is not None:
        context["trend"] = results_model.trend_summary(plot)
        context["stats"] = series_stats(plot)
        context["chart_url"] = (
            reverse("charts:job_series", args=[job.pk, name])
            + "?"
            + urlencode({"station": source.station})
        )
        if (
            not name.startswith("day_of_")
            and results_model.anomaly_series(source, name) is not None
        ):
            context["anomaly_url"] = reverse("stations:result_anomalies", args=[analysis.pk, name])
    return render(request, "stations/result.html", context)


def _size(path) -> int:
    return path.stat().st_size if path.is_file() else 0


def series_stats(plot) -> list[dict]:
    """Highest, lowest and mean of a series with when, and the values present."""
    from climpact_web.charts.data import _x_label, number

    pairs = [(float(v), i) for i, v in enumerate(plot.values) if v == v]
    if not pairs:
        return []
    high, low = max(pairs), min(pairs)
    mean = sum(v for v, _i in pairs) / len(pairs)
    return [
        {
            "label": _("Highest"),
            "value": number(high[0]),
            "note": _x_label(plot.step, plot.x[high[1]]),
        },
        {
            "label": _("Lowest"),
            "value": number(low[0]),
            "note": _x_label(plot.step, plot.x[low[1]]),
        },
        {"label": _("Mean"), "value": number(mean), "note": ""},
        {
            "label": _("Values"),
            "value": str(len(pairs)),
            "note": _("of %(total)s, %(missing)s missing")
            % {"total": len(plot.values), "missing": len(plot.values) - len(pairs)},
        },
    ]


@gzip_page
@require_safe
def result_anomalies(request, analysis_id, name):
    """The standardised anomalies of a series, as an ``index`` chart payload (bars)."""
    from climpact_web.charts import data as chart_data
    from climpact_web.charts.views import SERIES_NAME, json_response

    if not SERIES_NAME.match(name):
        raise Http404
    analysis = get_analysis(request, analysis_id)
    job, source = current_source(analysis)
    if source is None:
        raise Http404
    path = source.index_source.table_path(name)

    def build():
        series = results_model.anomaly_series(source, name)
        if series is None:
            return None
        title = _("%(name)s: standardised anomalies") % {"name": name}
        payload = chart_data.series_payload(
            f"{name}_anomaly",
            title,
            "",
            series["step"],
            series["labels"],
            series["values"],
            bars=True,
        )
        payload["axis"] = _("Standard deviations from the mean")
        payload["label"] = _("Anomaly")
        payload["bar_labels"] = [_("Above the mean"), _("Below the mean")]
        payload["csv"] = reverse("jobs:file", args=[job.pk, source.table_file(name)])
        return payload

    return json_response(request, ("anomalies", str(job.pk), source.station, name), [path], build)

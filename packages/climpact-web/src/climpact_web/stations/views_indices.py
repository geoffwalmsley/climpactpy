"""Results (#78, #79): the calculation's progress, the results dashboard, each index's own
page, and "Adjust and recalculate" (#178). The sector comparison is in ``views_sector``.

URLs (all ``/station/<id>/...``, private to the session like the other steps):

``indices``                 the old Calculate step's address: GET goes to "Adjust and
                            recalculate" on Results (old links, bookmarks), POST is that
                            form's submission and queues a new run; with
                            ``recalculate=1`` and no settings, it is "Recalculate" on
                            out-of-date results (#179)
``indices/validate``        htmx: one group of the settings checked as it changes
``results``                 progress while the job runs, then the dashboard; a
                            recalculation keeps the last results under its progress
``results/progress``        htmx: the progress fragment; when the job ends it reloads the
                            page (or opens the index the user came from)
``results/<key>``           one index: chart, trend, anomalies, tables, downloads
``results/<series>/anomalies.json``  the standardised anomalies, for the chart

There is no Calculate step since #178: the indices are calculated with the default
settings while the user looks at the quality checks (:mod:`.calculation`), and "Use this
data" opens the results. The results come from the analysis's ``indices_job``; an analysis
opened from a batch's results (#80, ``origin``) shows the batch's outputs for that station
until it is calculated again here. After a change to an input the results stay, marked out
of date, until the run that replaces them has finished (#179, :mod:`.workspace`).
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.gzip import gzip_page
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from climpact_web.core.limits import human_required
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.stages import stage_label
from climpact_web.jobs.views import progress_context
from climpact_web.stations import calculation, themes, workspace
from climpact_web.stations import results as results_model
from climpact_web.stations.calculation import previous_params, station_title
from climpact_web.stations.forms_indices import IndexParamsForm
from climpact_web.stations.models import StationAnalysis, Step
from climpact_web.stations.views import get_analysis, step_two_ready
from climpact_web.stations.workspace import (
    batch_job,
    committed,
    replaced_job,
    restore_if_cancelled,
    shown_run,
)

INDEX_KEY_MAX = 100


def _ready(analysis: StationAnalysis) -> bool:
    return (
        analysis.metadata_complete and analysis.reached(Step.QC) and analysis.station_file.is_file()
    )


def results_url(analysis, index: str = "") -> str:
    url = reverse("stations:results", args=[analysis.pk])
    return url + ("?" + urlencode({"index": index}) if index else "")


def adjust_url(analysis, index: str = "") -> str:
    """Results with "Adjust and recalculate" open; ``index``, the index page the user came
    from, is where the new results open."""
    query = {"settings": "open", **({"back": index} if index else {})}
    return f"{reverse('stations:results', args=[analysis.pk])}?{urlencode(query)}#adjust"


# ---- Adjust and recalculate --------------------------------------------------------------


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def indices(request, analysis_id):
    """The address of the Calculate step before #178. GET (an old link or bookmark) opens
    "Adjust and recalculate" on Results; POST is that form: queue a run with the settings,
    which replaces the results when it finishes."""
    analysis = get_analysis(request, analysis_id)
    if not _ready(analysis):
        return redirect("stations:load", analysis_id=analysis.pk)
    index = request.GET.get("index", "")[:INDEX_KEY_MAX]
    if request.method != "POST":
        return redirect(adjust_url(analysis, index))
    if request.POST.get("recalculate"):
        # "Recalculate" on out-of-date results: the current inputs, the latest settings.
        restore_if_cancelled(analysis)
        calculation.recalculate(request, analysis)
        analysis.touch()
        analysis.save()
        return redirect(results_url(analysis))
    form = IndexParamsForm(request.POST, station_title=station_title(analysis))
    if not form.is_valid():
        return render_results(request, analysis, form)
    job = calculation.queue_station_run(request, analysis, form)
    if job is None:
        return redirect("stations:load", analysis_id=analysis.pk)
    analysis.advance_to(Step.RESULTS)
    analysis.touch()
    analysis.save()
    return redirect(results_url(analysis, form.cleaned_data.get("index", "")[:INDEX_KEY_MAX]))


@require_POST
def indices_validate(request, analysis_id):
    """htmx: one group of fields checked as it changes, returned on its own with its
    warnings."""
    analysis = get_analysis(request, analysis_id)
    unit = request.POST.get("group", "")
    if unit not in IndexParamsForm.UNITS:
        return HttpResponseBadRequest()
    form = IndexParamsForm(request.POST, station_title=station_title(analysis))
    form.is_valid()
    context = {"form": form, "group": unit, "analysis": analysis}
    return render(request, "stations/_indices_unit.html", context)


# ---- progress and the dashboard ----------------------------------------------------------

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


def current_source(analysis: StationAnalysis):
    """(job, RunSource or None): the results shown (:func:`workspace.shown_run`), else the
    run in progress (no source yet); (None, None) before the user has chosen to use the
    data, or with nothing calculated."""
    if not committed(analysis):
        return None, None
    job = shown_run(analysis)
    if job is not None:
        station = analysis.origin.get("station") if job.kind == "batch" else None
        return job, results_model.run_source(job, station)
    return analysis.indices_job, None


def load_results(analysis, source):
    return results_model.results_for(
        source, analysis.summary, (analysis.base_start, analysis.base_end)
    )


def settings_context(request, analysis, form=None) -> dict:
    """The "Adjust and recalculate" form: the settings of the results shown (or of the run
    in progress), open when asked for (``?settings=open``) or when it has errors."""
    previous = previous_params(analysis)
    if form is None:
        back = request.GET.get("back", "")[:INDEX_KEY_MAX]
        form = calculation.settings_form(analysis, previous, index=back)
    return {
        "form": form,
        "settings_source": previous[5],
        "open_settings": form.is_bound or request.GET.get("settings") == "open",
    }


@never_cache
@require_safe
def results(request, analysis_id):
    """Results: the calculation's progress, then every index as a card."""
    analysis = get_analysis(request, analysis_id)
    if not committed(analysis):
        # Not before "Use this data": the run may be going on behind the quality checks.
        target = "stations:qc" if step_two_ready(analysis) else "stations:load"
        return redirect(target, analysis_id=analysis.pk)
    return render_results(request, analysis)


def render_results(request, analysis, form=None):
    """The results page: the dashboard, with a recalculation's progress above it, or the
    progress of the first run, or (with ``form``) the settings' errors."""
    restore_if_cancelled(analysis)
    job, source = current_source(analysis)
    index = request.GET.get("index", "")[:INDEX_KEY_MAX]
    context = {
        "analysis": analysis,
        "job": job,
        **workspace.context(analysis, "results"),
        "index": index,
        **settings_context(request, analysis, form),
    }
    if job is None or source is None:
        if job is None:  # nothing calculated: the run was refused, say, or cancelled
            context["no_run"] = True
        elif job.status == Status.SUCCEEDED:  # finished, but without index tables
            context["missing_outputs"] = True
        else:
            context.update(progress_context(request, job))
            context["phases"] = phases(job)
        return render(request, "stations/results_progress.html", context)
    run = load_results(analysis, source)
    running = analysis.indices_job
    if running == job:
        running = None
    # ?index= opens that index; while a recalculation runs the page stays here, under its
    # progress, which opens the index once the new results are ready.
    if index and form is None and (running is None or running.is_finished):
        card = run.find(index)
        if card is not None:
            return redirect("stations:result", analysis_id=analysis.pk, key=card.key)
    if not analysis.reached(Step.RESULTS):
        analysis.advance_to(Step.RESULTS)
        analysis.save(update_fields=["step"])
    if running is not None:  # a recalculation, under way or failed
        context["recalculation"] = {**progress_context(request, running), "phases": phases(running)}
    context["stale"] = stale_context(analysis, job, running)
    context.update(dashboard_context(request, analysis, source, run))
    return render(request, "stations/results.html", context)


@never_cache
@require_safe
def results_progress(request, analysis_id):
    """htmx: the progress fragment. Once the job has finished the page is reloaded (or the
    index the user came from opens), with ``HX-Redirect``; so it is when a recalculation is
    cancelled, to show the results it would have replaced."""
    analysis = get_analysis(request, analysis_id)
    job = analysis.indices_job
    if job is None:
        raise Http404
    if job.status == Status.RUNNING:
        from climpact_web.jobs.worker import reap_stale

        if reap_stale():
            job.refresh_from_db()
    index = request.GET.get("index", "")[:INDEX_KEY_MAX]
    cancelled_recalculation = job.status == Status.CANCELLED and (
        replaced_job(analysis, job) or batch_job(analysis)
    )
    if job.status == Status.SUCCEEDED or cancelled_recalculation:
        response = HttpResponse(status=204)
        response["HX-Redirect"] = results_url(analysis, index)
        return response
    context = {**progress_context(request, job), "analysis": analysis, "phases": phases(job)}
    context["index"] = index
    return render(request, "stations/_results_progress.html", context)


def params_summary(params) -> list[dict]:
    """The settings a run used (an :class:`~climpact.config.IndexParams`), each with
    whether it differs from Climpact's default."""
    from climpact.config import IndexParams

    def days(n):
        return ngettext("%(n)s day", "%(n)s days", n) % {"n": n}

    def months(n):
        return ngettext("%(n)s month", "%(n)s months", n) % {"n": n}

    def unit(value, symbol):
        return f"{value:g} {symbol}"

    def custom_text(custom):
        if custom is None:
            return _("none")
        return f"{custom.variable} {custom.operator} {custom.threshold:g} ({custom.name})"

    default = IndexParams()
    rows = [
        ("wsdi_days", _("Days for WSDId"), days),
        ("csdi_days", _("Days for CSDId"), days),
        ("rx_days", _("Days for Rxdday"), days),
        ("txtn_days", _("Days for TXdTNd and TXbdTNbd"), days),
        ("hdd_base", _("Base temperature for HDDheat"), lambda v: unit(v, "°C")),
        ("cdd_base", _("Base temperature for CDDcold"), lambda v: unit(v, "°C")),
        ("gdd_base", _("Base temperature for GDDgrow"), lambda v: unit(v, "°C")),
        ("rnnmm", _("Precipitation amount for Rnnmm"), lambda v: unit(v, _("mm"))),
        ("spei_months", _("Extra SPI and SPEI time scale"), months),
        ("custom", _("Custom threshold index"), custom_text),
    ]
    return [
        {
            "label": label,
            "value": text(getattr(params, name)),
            "changed": getattr(params, name) != getattr(default, name),
        }
        for name, label, text in rows
    ]


def settings_line(params) -> str:
    """The settings in one sentence, for the results' header (#178): the defaults, or the
    settings that differ from them."""
    changed = [f"{p['label']} {p['value']}" for p in params_summary(params) if p["changed"]]
    if not changed:
        return _("Climpact's default settings.")
    return _("Settings changed: %(settings)s.") % {"settings": ", ".join(changed)}


def downloads(source) -> dict:
    """The zip, with its size, for the dashboard's one "Download all"; the Files page
    (``stations:downloads``, #79, #176) lists every file."""
    from climpact_web.stations.downloads import main_downloads

    return {"job": source.job, "zip": main_downloads(source)["zip"]}


def dashboard_context(request, analysis, source, run) -> dict:
    q = request.GET.get("q", "").strip()[:100]
    theme = request.GET.get("theme", "")
    significant = request.GET.get("significant") == "1"
    found = run.themes()
    if theme not in {t.key for t in found}:
        theme = ""
    sections = run.sections()
    words = q.lower().split()
    filtering = bool(words or theme or significant)
    # The "All indices" link of an index's page opens its group without JavaScript.
    group = request.GET.get("group", "")
    shown = 0
    for section in sections:
        for card in section["cards"]:
            card.hidden = bool(
                (theme and card.theme != theme)
                or (significant and not card.significant)
                or any(w not in card.search_text for w in words)
            )
            shown += not card.hidden
        section["hidden"] = all(c.hidden for c in section["cards"])
        # Groups start collapsed, unless a filter shows what is in them or a link asks.
        section["open"] = not section["hidden"] and (filtering or section["key"] == group)
    first_year = (analysis.summary or {}).get("first_year", "")
    return {
        "source": source,
        "run": run,
        "sections": sections,
        "summary_sentences": themes.summary(run.cards, found, first_year),
        "headline_themes": [_theme_entry(analysis, t) for t in found if t.theme.headline],
        "also_measured": [_theme_entry(analysis, t) for t in found if not t.theme.headline],
        "themes": found,
        "q": q,
        "theme": theme,
        "significant": significant,
        "filtering": filtering,
        "shown": shown,
        "total": len(run.cards),
        "significant_count": sum(1 for c in run.cards if c.significant),
        "settings_line": settings_line(source.params),
        "downloads": downloads(source),
        "from_batch": source.from_batch,
    }


def stale_context(analysis, shown, running) -> dict | None:
    """The out-of-date banner of the results shown (#179): what changed since they were
    calculated, in words, and whether a run of the new inputs is on the way (``running``,
    its progress then shows in the banner) or has to be asked for ("Recalculate"). None
    when they are current."""
    changes = workspace.run_changes(analysis, shown)
    if not changes:
        return None
    return {
        "changes": workspace.change_sentences(analysis, shown, changes),
        "replacing": running is not None and not running.is_finished,
        "details_valid": workspace.details_valid(analysis),
    }


def _theme_entry(analysis, found: themes.ThemeResult) -> dict:
    """A theme's headline (or "Also measured" line) for the template: its finding, its
    largest significant trends as links, and a link to its indices in the catalogue."""
    page = reverse("stations:results", args=[analysis.pk])
    n = len(found.cards)
    entry = {
        "key": found.key,
        "label": found.label,
        "finding": found.finding,
        "badge": found.badge,
        "items": [
            {
                "href": reverse("stations:result", args=[analysis.pk, card.key]),
                "title": card.title,
                "code": card.code,
                "trend": themes.trend_text(card),
                "direction": card.trend["direction"],
                "spark": card.spark,
            }
            for card in found.top
        ],
        "more_href": f"{page}?{urlencode({'theme': found.key})}#catalogue",
        "more_label": ngettext(
            "See the %(n)s index in %(theme)s", "See all %(n)s indices in %(theme)s", n
        )
        % {"n": n, "theme": found.label},
        "note": "",
    }
    if found.key == "averages":
        mean = next((c for c in found.cards if c.key == themes.MEAN_TEMPERATURE), None)
        if mean is not None and mean.trend and mean.trend.get("valid"):
            entry["note"] = _("Mean temperature (%(code)s): %(trend)s") % {
                "code": mean.code,
                "trend": themes.trend_text(mean),
            }
    elif found.key == "custom":
        # The user's own index: its definition, and its trend in words.
        card = found.cards[0]
        entry["definition"] = card.definition
        entry["code"] = card.code
        entry["more_href"] = reverse("stations:result", args=[analysis.pk, card.key])
        entry["more_label"] = _("Open %(code)s") % {"code": card.code}
        if card.significant:
            entry["finding"] = (
                _("Increased significantly: %(trend)s.")
                if card.trend["direction"] == "up"
                else _("Decreased significantly: %(trend)s.")
            ) % {"trend": themes.trend_text(card)}
        elif card.trend and card.trend.get("valid"):
            entry["finding"] = _("No significant change.")
    return entry


# ---- one index ---------------------------------------------------------------------------


@never_cache
@require_safe
def result(request, analysis_id, key):
    """One index: the chosen series as an interactive chart with its trend, its
    standardised anomalies and the trend file's rows. Its only downloads are the chart's
    own (PNG, SVG, CSV); every other file is in Files (#176)."""
    analysis = get_analysis(request, analysis_id)
    job, source = current_source(analysis)
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
        **workspace.context(analysis, "results"),
        "stale": bool(workspace.run_changes(analysis, job)),
        "previous": previous,
        "next": following,
        "trend_rows": results_model.trend_rows(source, card.key) if not card.daily else [],
        "csv_path": source.table_file(name.removeprefix("day_of_")),
        "csv_size": _size(source.index_source.table_path(name.removeprefix("day_of_"))),
        "png_path": source.plot_file(name),
        "from_batch": source.from_batch,
        "chart_title": results_model.chart_title(card, series),
    }
    if plot is not None:
        context["trend"] = results_model.trend_summary(plot)
        context["stats"] = series_stats(plot, series.units)
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


def series_stats(plot, units: str = "") -> list[dict]:
    """Highest, lowest and mean of a series with when and ``units``, and the values
    present. A day-of-occurrence series gives calendar days (``day 200``)."""
    from climpact_web.charts.data import _x_label, number

    pairs = [(float(v), i) for i, v in enumerate(plot.values) if v == v]
    if not pairs:
        return []
    high, low = max(pairs), min(pairs)
    mean = sum(v for v, _i in pairs) / len(pairs)

    def text(value: float) -> str:
        if plot.name.startswith("day_of_"):
            return _("day %(value)s") % {"value": number(value)}
        return results_model.with_units(number(value), units)

    return [
        {
            "label": _("Highest"),
            "value": text(high[0]),
            "note": _x_label(plot.step, plot.x[high[1]]),
        },
        {
            "label": _("Lowest"),
            "value": text(low[0]),
            "note": _x_label(plot.step, plot.x[low[1]]),
        },
        {"label": _("Mean"), "value": text(mean), "note": ""},
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

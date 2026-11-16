"""Results (#78, #79): the calculation's progress, the results dashboard and each index's
own page. The sector comparison is in ``views_sector``. The index settings are edited in
the Inputs panel's sheet since #199 (``views.edit_input``), not on Results.

URLs (all ``/station/<id>/...``, private to the session like the other steps):

``indices``                 the old Calculate step's address: GET (old links, bookmarks)
                            opens Results with the Index settings sheet; POST is
                            "Recalculate" on out-of-date results (#179): the current
                            inputs with the latest settings
``indices/validate``        htmx: one group of the settings sheet checked as it changes
``results``                 progress while the job runs, then the dashboard; a
                            recalculation keeps the last results under its progress;
                            ``?settings=open`` (old links) opens the Index settings sheet
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
from climpact_web.stations.calculation import station_title
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
    """Results with the Index settings sheet open (#199): the old "Adjust and recalculate"
    address. ``index``, the index page the user came from, is where applying returns."""
    query = {"settings": "open", **({"back": index} if index else {})}
    return f"{reverse('stations:results', args=[analysis.pk])}?{urlencode(query)}"


# ---- the old Calculate step, and "Recalculate" -------------------------------------------


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def indices(request, analysis_id):
    """The address of the Calculate step before #178. GET (an old link or bookmark) opens
    the Index settings sheet over Results (#199). POST is "Recalculate" on out-of-date
    results (#179): the current inputs with the latest settings. The settings themselves
    are applied from the sheet (``views.edit_input``)."""
    analysis = get_analysis(request, analysis_id)
    if not _ready(analysis):
        return redirect("stations:load", analysis_id=analysis.pk)
    index = request.GET.get("index", "")[:INDEX_KEY_MAX]
    if request.method != "POST":
        return redirect(adjust_url(analysis, index))
    if not request.POST.get("recalculate"):
        # A settings form from before #199: the settings are in the sheet now.
        return redirect(workspace.sheet_url(analysis, "settings", results_url(analysis)))
    restore_if_cancelled(analysis)
    calculation.recalculate(request, analysis)
    analysis.touch()
    analysis.save()
    return redirect(results_url(analysis))


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


def open_sheet(request, analysis) -> tuple[dict | None, str]:
    """``?settings=open``, the old "Adjust and recalculate" address (#199): the Index
    settings sheet opens as the page loads (js/sheet.js), and without JavaScript the page
    goes on to the sheet's own page. Applying returns to the index the user came from
    (``back``), else to Results. Returns (the sheet to open, or None; where applying
    returns)."""
    if request.GET.get("settings") != "open":
        return None, request.path
    back = request.GET.get("back", "")[:INDEX_KEY_MAX]
    target = results_url(analysis, back)
    return {"key": "settings", "url": workspace.sheet_url(analysis, "settings", target)}, target


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


def render_results(request, analysis):
    """The results page: the dashboard, with a recalculation's progress above it, or the
    progress of the first run."""
    restore_if_cancelled(analysis)
    job, source = current_source(analysis)
    index = request.GET.get("index", "")[:INDEX_KEY_MAX]
    sheet, back = open_sheet(request, analysis)
    context = {
        "analysis": analysis,
        "job": job,
        **workspace.context(analysis, "results", back),
        "index": index,
        "open_sheet": sheet,
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
    if index and (running is None or running.is_finished):
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


# The catalogue's sortable columns (#200): the key of ?sort=, and the direction a first
# click sorts in (names A to Z; the largest trends and the significant ones first).
SORTS = {
    "name": "ascending",
    "code": "ascending",
    "trend": "descending",
    "significance": "descending",
}


def _significance_rank(card) -> int:
    """2 significant, 1 a trend that is not, 0 no trend (too few values, daily tables)."""
    if not (card.trend and card.trend.get("valid")):
        return 0
    return 2 if card.significant else 1


def sort_cards(cards: list, sort: str, descending: bool) -> list:
    """The catalogue's rows sorted by a column (``SORTS``), ties in the catalogue's order.
    Rows without a trend stay last when sorting by the trend, whichever the direction."""
    if sort == "name":
        return sorted(cards, key=lambda c: c.title.casefold(), reverse=descending)
    if sort == "code":
        return sorted(cards, key=lambda c: c.code.casefold(), reverse=descending)
    if sort == "significance":
        return sorted(cards, key=_significance_rank, reverse=descending)
    if sort == "trend":
        with_trend = [c for c in cards if c.trend and c.trend.get("valid")]
        without = [c for c in cards if c not in with_trend]
        return sorted(with_trend, key=lambda c: c.trend["slope"], reverse=descending) + without
    return list(cards)


def _column_labels() -> dict[str, str]:
    return {
        "name": _("Index"),
        "code": _("Code"),
        "trend": _("Trend per decade"),
        "significance": _("Significance"),
    }


def sort_sentence(column: str, descending: bool) -> str:
    """What a sort is announced as: "Sorted by Trend per decade, descending." """
    if descending:
        return _("Sorted by %(column)s, descending.") % {"column": column}
    return _("Sorted by %(column)s, ascending.") % {"column": column}


def dashboard_context(request, analysis, source, run) -> dict:
    """The Results page (#200): the answer, the theme tiles, and the catalogue as one
    table, filtered by theme chip, "Significant only" and a search, and sorted by a column.
    Without JavaScript the filters are a form sent to this page and the column headers are
    links; js/results.js does the same in place."""
    q = request.GET.get("q", "").strip()[:100]
    theme = request.GET.get("theme", "")
    significant = request.GET.get("significant") == "1"
    sort = request.GET.get("sort", "")
    if sort not in SORTS:
        sort = ""
    direction = request.GET.get("dir", "")
    if direction not in ("ascending", "descending"):
        direction = SORTS.get(sort, "")
    descending = direction == "descending"
    found = run.themes()
    ordered = [c for s in run.sections() for c in s["cards"]]
    chips = [
        {"key": key, "label": label, "hue": themes.hue_of(key), "count": n}
        for key, label in (
            *((t.key, t.label) for t in found if t.theme.headline),
            (themes.ALSO_MEASURED, _("Also measured")),
        )
        if (n := sum(1 for c in ordered if c.chip == key))
    ]
    if theme not in {c["key"] for c in chips}:
        theme = ""
    words = q.lower().split()
    shown = 0
    for position, card in enumerate(ordered):
        # What js/results.js sorts and filters by, as the server does.
        card.position = position
        card.sort_rank = _significance_rank(card)
        card.sort_trend = repr(float(card.trend["slope"])) if card.sort_rank else ""
        card.hidden = bool(
            (theme and card.chip != theme)
            or (significant and not card.significant)
            or any(w not in card.search_text for w in words)
        )
        shown += not card.hidden
    rows = sort_cards(ordered, sort, descending)
    # Each header links to the page sorted by its column, the filters kept: the first
    # click in the column's own direction, a second the other way.
    filters = {k: v for k, v in (("q", q), ("theme", theme)) if v}
    if significant:
        filters["significant"] = "1"
    labels = _column_labels()
    page = reverse("stations:results", args=[analysis.pk])
    columns = []
    for key, first in SORTS.items():
        state = direction if key == sort else ""
        to = first
        if state:
            to = "ascending" if state == "descending" else "descending"
        columns.append(
            {
                "key": key,
                "label": labels[key],
                "sort": state,
                "first": first,
                "href": f"{page}?{urlencode({**filters, 'sort': key, 'dir': to})}#catalogue",
            }
        )
    summary = analysis.summary or {}
    first_year = summary.get("first_year", "")
    last_year = summary.get("last_year", "")
    return {
        "source": source,
        "run": run,
        "rows": rows,
        "columns": columns,
        "sort": sort,
        "direction": direction,
        "sort_text": sort_sentence(labels[sort], descending) if sort else "",
        "series_years": f"{first_year}–{last_year}" if first_year and last_year else "",
        "summary_sentences": themes.summary(run.cards, found, first_year),
        "headline_themes": [_theme_entry(analysis, t) for t in found if t.theme.headline],
        "chips": chips,
        "q": q,
        "theme": theme,
        "significant": significant,
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
    """A theme's tile for the template: its finding, its largest significant trends as
    links (the value and its units apart, as the tile sets them), and a link to its
    indices in the catalogue."""
    page = reverse("stations:results", args=[analysis.pk])
    n = len(found.cards)
    return {
        "key": found.key,
        "label": found.label,
        "hue": found.hue,
        "finding": found.finding,
        "badge": found.badge,
        "items": [
            {
                "href": reverse("stations:result", args=[analysis.pk, card.key]),
                "title": card.title,
                "code": card.code,
                "value": card.trend["slope_text"],
                # Short, so the trend keeps to one line: "pp / decade" (#200).
                "units": short_units(card),
                "units_title": card.trend_units if card.units == "%" else "",
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
    }


def short_units(card) -> str:
    """A trend's units in a theme tile: "pp" for percentage points (spelt out in its
    ``abbr``), the index's units otherwise."""
    return _("pp") if card.units == "%" else card.trend_units


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
        **workspace.context(analysis, "results", request.path),
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

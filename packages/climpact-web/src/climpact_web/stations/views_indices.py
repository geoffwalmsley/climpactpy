"""Results (#78, #79): the calculation's progress, the results dashboard and each index's
own page. The sector comparison is in ``views_sector``. The index settings are edited in
the Inputs panel's sheet since #199 (``views.edit_input``), not on Results.

URLs (all ``/w/<workspace>/<station>/...``, private to the session like the other steps):

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
``results/<key>``           one index (#237): its chart, trend statistics and values

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
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from climpact_web.core import numbers
from climpact_web.core.limits import human_required
from climpact_web.jobs.forms import safe_station_name
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.stages import stage_label
from climpact_web.jobs.views import progress_context
from climpact_web.stations import calculation, themes, workspace
from climpact_web.stations import results as results_model
from climpact_web.stations.calculation import station_title
from climpact_web.stations.forms_indices import IndexParamsForm
from climpact_web.stations.models import Source, Station, Step
from climpact_web.stations.views import get_analysis, step_two_ready
from climpact_web.stations.workspace import (
    batch_job,
    committed,
    replaced_job,
    restore_if_cancelled,
    shown_run,
)

INDEX_KEY_MAX = 100


def _ready(analysis: Station) -> bool:
    return (
        analysis.metadata_complete and analysis.reached(Step.QC) and analysis.station_file.is_file()
    )


def results_url(analysis, index: str = "") -> str:
    url = analysis.url("results")
    return url + ("?" + urlencode({"index": index}) if index else "")


def adjust_url(analysis, index: str = "") -> str:
    """Results with the Index settings sheet open (#199): the old "Adjust and recalculate"
    address. ``index``, the index page the user came from, is where applying returns."""
    query = {"settings": "open", **({"back": index} if index else {})}
    return f"{analysis.url('results')}?{urlencode(query)}"


# ---- the old Calculate step, and "Recalculate" -------------------------------------------


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@human_required
def indices(request, workspace_id, slug):
    """The address of the Calculate step before #178. GET (an old link or bookmark) opens
    the Index settings sheet over Results (#199). POST is "Recalculate" on out-of-date
    results (#179): the current inputs with the latest settings. The settings themselves
    are applied from the sheet (``views.edit_input``)."""
    analysis = get_analysis(request, workspace_id, slug)
    if not _ready(analysis):
        return redirect(analysis.url("setup"))
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
def indices_validate(request, workspace_id, slug):
    """htmx: one group of fields checked as it changes, returned on its own with its
    warnings."""
    analysis = get_analysis(request, workspace_id, slug)
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


def current_source(analysis: Station):
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
        source, analysis.summary, (analysis.workspace.base_start, analysis.workspace.base_end)
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
def results(request, workspace_id, slug):
    """Results: the calculation's progress, then every index as a card."""
    analysis = get_analysis(request, workspace_id, slug)
    if not committed(analysis):
        # Not before "See results": the run may be going on behind the quality checks.
        return redirect(analysis.url("qc" if step_two_ready(analysis) else "setup"))
    return render_results(request, analysis)


def batch_failure(analysis) -> str:
    """Why a batch's station failed in its run, in words (``batch.fill.run_states``), for
    its Indices: its workspace's address opens on them when it is the only station (#256).
    Empty for any other station. As a sentence: the runner's errors start in lower case."""
    if analysis.source != Source.BATCH:
        return ""
    from climpact_web.batch.fill import FAILED, run_states

    state = run_states([analysis]).get(analysis.pk)
    if state is None or state.state != FAILED or not state.error:
        return ""
    error = state.error[:1].upper() + state.error[1:]
    return error if error.endswith((".", "!", "?")) else error + "."


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
            context["run_failure"] = batch_failure(analysis)
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
            return redirect(analysis.url("result", card.key))
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
def results_progress(request, workspace_id, slug):
    """htmx: the progress fragment. Once the job has finished the page is reloaded (or the
    index the user came from opens), with ``HX-Redirect``; so it is when a recalculation is
    cancelled, to show the results it would have replaced."""
    analysis = get_analysis(request, workspace_id, slug)
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


# The table's sortable columns (#200, #236), in the table's order (codes first, #218): the
# key of ?sort=, and the direction a first click sorts in (codes and names A to Z; the
# largest trends and the significant ones first).
SORTS = {
    "code": "ascending",
    "name": "ascending",
    "trend": "descending",
    "significance": "descending",
}
# The order the table opens in (#263, the Results board): by the size of the trend, the
# slope per decade without its sign, largest first. It is no column's: ?sort=size.
DEFAULT_SORT = "size"


def _significance_rank(card) -> int:
    """2 significant, 1 a trend that is not, 0 no trend (too few values, daily tables)."""
    if not (card.trend and card.trend.get("valid")):
        return 0
    return 2 if card.significant else 1


def sort_cards(cards: list, sort: str, descending: bool) -> list:
    """The table's rows sorted by a column (``SORTS``), ties in the catalogue's order
    (names tie by code).
    Rows without a trend stay last when sorting by the trend, whichever the direction."""
    if sort == "name":
        # Short names repeat (each heatwave definition's "Number of heatwaves"), so by
        # code within a name.
        return sorted(
            cards, key=lambda c: (c.title.casefold(), c.code.casefold()), reverse=descending
        )
    if sort == "code":
        return sorted(cards, key=lambda c: c.code.casefold(), reverse=descending)
    if sort == "significance":
        return sorted(cards, key=_significance_rank, reverse=descending)
    if sort in ("trend", "size"):
        with_trend = [c for c in cards if c.trend and c.trend.get("valid")]
        without = [c for c in cards if c not in with_trend]

        def key(c):
            return abs(c.trend["slope"]) if sort == "size" else c.trend["slope"]

        return sorted(with_trend, key=key, reverse=descending) + without
    return list(cards)


def _column_labels() -> dict[str, str]:
    """Each sortable column's header, and its name in the sentence that announces a sort
    (the header "Sig." is "Significance" there)."""
    return {
        "code": (_("Code"), _("Code")),
        "name": (_("Index"), _("Index")),
        "trend": (_("Slope per decade"), _("Slope per decade")),
        "significance": (_("Significant"), _("Significant")),
    }


def size_sentence() -> str:
    """What the default order is announced as (#263)."""
    return _("Sorted by the size of the trend, largest first.")


def sort_sentence(column: str, descending: bool) -> str:
    """What a sort is announced as: "Sorted by Slope per decade, descending." """
    if descending:
        return _("Sorted by %(column)s, descending.") % {"column": column}
    return _("Sorted by %(column)s, ascending.") % {"column": column}


def run_base(analysis, job) -> tuple[int, int] | None:
    """The base period the shown results used: the run's, else the workspace's."""
    meta = ((job.params or {}) if job is not None else {}).get("metadata") or {}
    start, end = meta.get("base_start"), meta.get("base_end")
    if start and end:
        return int(start), int(end)
    space = analysis.workspace
    if space.base_start and space.base_end:
        return int(space.base_start), int(space.base_end)
    return None


def _row(analysis, source, run, card, theme_label: str, base) -> dict:
    """One index for the table and its detail (#236, #263): the slope with its unit, its
    interval, and the detail's chart, statistics (with the mean and whether the trend is
    significant) and links. Numbers by the rules of #226."""
    from climpact_web.stations import index_detail

    plot = run.plots.get(card.main)
    trend = card.trend if card.trend and card.trend.get("valid") else None
    mean = index_detail.mean(plot.values) if plot is not None else None
    places = numbers.slope_decimals(card.units)
    page = analysis.url("result", card.key)
    job = source.job
    links = {"page": page}
    if not card.daily:
        links["csv"] = reverse(
            "jobs:file", args=[job.pk, source.table_file(card.main.removeprefix("day_of_"))]
        )
        png = source.plot_file(card.main)
        if png:
            links["png"] = reverse("jobs:file", args=[job.pk, png])
        monthly = next(
            (s.name for s in card.series if s.name.endswith("_MON") and s.name != card.main),
            "",
        )
        if monthly:
            links["monthly"] = f"{page}?{urlencode({'series': monthly})}"
    row = {
        "card": card,
        "key": card.key,
        "theme": theme_label,
        "unit": card.units,
        # The slope's unit beside it (#263: "+5.15 days"), percentage points for the trend
        # of a percentage (#226): "+1.31 pp".
        "slope_unit": numbers.trend_units(card.units),
        "slope_pp": numbers.unit_label(card.units) == "%",
        "slope": trend["slope_text"] if trend else "",
        "interval": trend["interval_text"] if trend else "",
        "mean": numbers.fixed(mean, places) if mean is not None else "",
        "mean_text": numbers.with_unit(numbers.fixed(mean, places), card.units)
        if mean is not None
        else "",
        "links": links,
    }
    if plot is not None:
        chart = index_detail.chart(plot, base)
        row.update(
            chart=chart,
            readout=index_detail.readout(
                card,
                plot,
                chart,
                "" if card.daily else page,
                src=reverse("charts:job_series", args=[job.pk, card.main])
                + "?"
                + urlencode({"station": source.station}),
            )
            if chart
            else "",
            chart_label=index_detail.summary(card, plot),
            caption=index_detail.caption(card, plot),
            used_label=index_detail.used_label(plot),
            used=index_detail.values_used(card, plot),
        )
    return row


def dashboard_context(request, analysis, source, run) -> dict:
    """The Indices (#236, #263, the Results board): a filter rail (search, theme with
    counts, "Significant only"), one line that answers, the table of every index (code,
    name, slope per decade with its unit, 95% interval, significance, sparkline), sortable
    by column and opening sorted by the size of the trend, and the selected index in a
    detail pane beside it (``?show=<key>``, the first row shown by default). Without
    JavaScript the filters are a form sent to this page, the column headers links and each
    row's code a link to ``?show=``; js/results.js does the same in place."""
    q = request.GET.get("q", "").strip()[:100]
    theme = request.GET.get("theme", "")
    significant = request.GET.get("significant") == "1"
    sort = request.GET.get("sort", "")
    if sort not in SORTS:
        sort = DEFAULT_SORT
    direction = request.GET.get("dir", "")
    if direction not in ("ascending", "descending"):
        direction = SORTS.get(sort, "descending")
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
    chip_labels = {c["key"]: c["label"] for c in chips}
    if theme not in chip_labels:
        theme = ""
    words = q.lower().split()
    base = run_base(analysis, source.job)
    rows = {}
    for position, card in enumerate(ordered):
        row = _row(analysis, source, run, card, chip_labels.get(card.chip, ""), base)
        # What js/results.js sorts and filters by, as the server does.
        row["position"] = position
        row["rank"] = _significance_rank(card)
        row["sort_trend"] = repr(float(card.trend["slope"])) if row["rank"] else ""
        row["hidden"] = bool(
            (theme and card.chip != theme)
            or (significant and not card.significant)
            or any(w not in card.search_text for w in words)
        )
        rows[card.key] = row
    table = [rows[c.key] for c in sort_cards(ordered, sort, descending)]
    shown = sum(1 for r in table if not r["hidden"])
    selected = request.GET.get("show", "")[:INDEX_KEY_MAX]
    if selected not in rows:
        selected = next((r["key"] for r in table if not r["hidden"]), table[0]["key"])
    rows[selected]["selected"] = True
    # Each header links to the page sorted by its column, the filters kept: the first
    # click in the column's own direction, a second the other way.
    filters = {k: v for k, v in (("q", q), ("theme", theme)) if v}
    if significant:
        filters["significant"] = "1"
    # Each row's code shows its detail, the filters and the order kept.
    kept = {**filters, **({"sort": sort, "dir": direction} if sort != DEFAULT_SORT else {})}
    for row in table:
        row["show_href"] = f"?{urlencode({**kept, 'show': row['key']})}#detail-{row['key']}"
    labels = _column_labels()
    page = analysis.url("results")
    columns = {}
    for key, first in SORTS.items():
        state = direction if key == sort else ""
        to = first
        if state:
            to = "ascending" if state == "descending" else "descending"
        columns[key] = {
            "key": key,
            "label": labels[key][0],
            "name": labels[key][1],
            "sort": state,
            "first": first,
            "href": f"{page}?{urlencode({**filters, 'sort': key, 'dir': to, 'show': selected})}",
        }
    summary = analysis.summary or {}
    first_year = summary.get("first_year", "")
    last_year = summary.get("last_year", "")
    mean = run.card(themes.MEAN_TEMPERATURE)
    mean_trend = ""
    if mean is not None and mean.trend and mean.trend.get("valid"):
        mean_trend = f"{mean.code} {mean.trend['per_decade_text']}"
    return {
        "source": source,
        "run": run,
        "rows": table,
        "columns": columns,
        "sort": sort,
        "direction": direction,
        "default_sort": DEFAULT_SORT,
        "sort_text": sort_sentence(labels[sort][1], descending)
        if sort in labels
        else size_sentence(),
        "series_years": f"{first_year}–{last_year}" if first_year and last_year else "",
        "chips": chips,
        "q": q,
        "theme": theme,
        "significant": significant,
        "selected": selected,
        "shown": shown,
        "total": len(run.cards),
        "significant_count": sum(1 for c in run.cards if c.significant),
        "mean_trend": mean_trend,
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


# ---- one index ---------------------------------------------------------------------------


@never_cache
@require_safe
def result(request, workspace_id, slug, key):
    """One index (#237, the Index board): its series (annual, or monthly where the index
    has it: ``?series=``) as a chart of the values or of their anomalies from the base
    period (``?view=anomaly``), beside its trend statistics, and the values as a table.
    Its context bar has the previous and next index, the provenance line and the index's
    files: the series' CSV, R's plot and a citation (#176: every other file is in Files)."""
    from climpact_web.stations import index_detail, index_page

    analysis = get_analysis(request, workspace_id, slug)
    job, source = current_source(analysis)
    if source is None:
        return redirect(analysis.url("results"))
    run = load_results(analysis, source)
    card = run.card(key)
    if card is None:
        found = run.find(key)
        if found is None:
            raise Http404
        return redirect(analysis.url("result", found.key))
    # The page shows the annual or the monthly values; the days of the extremes are a
    # column of their table, so a day-of-occurrence series opens its index's main one.
    shown = [s for s in card.series if not s.name.startswith("day_of_")]
    name = request.GET.get("series", card.main)
    series = next((s for s in shown if s.name == name), None) or next(
        s for s in card.series if s.name == card.main
    )
    name = series.name
    plot = run.plots.get(name)
    view = "anomaly" if request.GET.get("view") == "anomaly" else "values"
    base = run_base(analysis, job)
    page = analysis.url("result", card.key)
    previous, following = run.neighbours(card)
    theme = themes.by_key().get(card.theme)
    links = {"csv": reverse("jobs:file", args=[job.pk, source.table_file(name)])}
    if png := source.plot_file(name):
        links["png"] = reverse("jobs:file", args=[job.pk, png])
    station = analysis.station_name or analysis.file_name
    results_page = analysis.url("results")
    context = {
        "analysis": analysis,
        "job": job,
        "source": source,
        "card": card,
        "series": series,
        **workspace.context(analysis, "results", request.path),
        "stale": bool(workspace.run_changes(analysis, job)),
        # A run of new inputs under way (#237: no Inputs panel here to show it).
        "running": next((r for r in context_runs(analysis, request.path) if r.key == "run"), None),
        "theme": str(theme.label) if theme else "",
        # The daily tables' definitions name their unit already.
        "units": "" if card.daily else numbers.unit_label(card.units),
        "definition": card.definition
        + ("" if not card.definition or card.definition.endswith((".", "?", "!")) else "."),
        "links": links,
        "breadcrumb": [
            *filter(None, [workspace.workspace_page(analysis)]),
            {"label": station, "url": analysis.url()},
            {
                "label": _("Indices"),
                "url": f"{results_page}?{urlencode({'show': card.key})}#index-{card.key}",
            },
        ],
        "step_previous": _step(analysis, previous),
        "step_next": _step(analysis, following),
        "from_batch": source.from_batch,
    }
    if plot is None:
        context["citation"] = ""
        return render(request, "stations/result.html", context)
    day_plot = run.plots.get(f"day_of_{name}")
    anomaly_ok = index_page.has_anomalies(plot, base)
    if not anomaly_ok:
        view = "values"
    needs = results_model._needs(results_model._info_for(card.key))
    gone = index_page.left_out(plot, index_page.missing_days(analysis, needs))
    charts = []
    for v in ("values", "anomaly") if anomaly_ok else ("values",):
        drawn = index_page.chart(card, plot, base, anomaly=v == "anomaly")
        if drawn is not None:
            charts.append(
                {
                    "view": v,
                    "chart": drawn,
                    "label": index_page.chart_label(card, plot, base, anomaly=v == "anomaly"),
                    "shown": v == view,
                }
            )
    kept = {"series": name} if name != card.main else {}
    views = []
    if anomaly_ok and charts:
        views = [
            {"key": "values", "label": _("Values"), "href": f"{page}?{urlencode(kept)}"},
            {
                "key": "anomaly",
                "label": _("Anomaly from %(start)s–%(end)s") % {"start": base[0], "end": base[1]},
                "href": f"{page}?{urlencode({**kept, 'view': 'anomaly'})}",
            },
        ]
        for v in views:
            v["current"] = v["key"] == view
    periods = []
    if len(shown) > 1:
        labels = {"year": _("Annual"), "month": _("Monthly")}
        for s in shown:
            query = {**({"series": s.name} if s.name != card.main else {})}
            if view == "anomaly":
                query["view"] = "anomaly"
            periods.append(
                {
                    "label": labels.get(s.step, s.label),
                    "href": f"{page}?{urlencode(query)}" if query else page,
                    "current": s.name == name,
                }
            )
    mean = index_page.base_mean(plot, base)
    when = {"year": _("Year"), "month": _("Month")}.get(plot.step, _("Day"))
    rows = index_page.table(card, plot, day_plot, base, gone)
    # ?at=1944 (a year picked on the Indices' chart, #283): its row is selected and the
    # interactive chart reads it out.
    at = request.GET.get("at", "")
    if not any(r["when"] == at for r in rows):
        at = ""
    for r in rows:
        r["selected"] = r["when"] == at
    low = index_page.low_is_record(card.key)
    context.update(
        trend=results_model.trend_summary(plot),
        series_name=index_detail.series_name(card, plot),
        charts=charts,
        views=views,
        periods=periods,
        bars=plot.bars,
        has_smooth=any(c["chart"].smooth for c in charts),
        has_gaps=any(c["chart"].gaps for c in charts),
        used_label=index_detail.used_label(plot),
        used=index_detail.values_used(card, plot),
        base_mean=numbers.with_unit(numbers.number(mean), card.units) if mean is not None else "",
        record=index_page.record(card, plot),
        left_out=index_page.left_out_summary(plot, gone),
        rows=rows,
        at=at,
        chart_data=index_page.payload(
            card, plot, base, gone, day_plot, name=f"{safe_station_name(station)}_{name}"
        )
        if charts
        else None,
        table_title={"year": _("Annual values"), "month": _("Monthly values")}.get(
            plot.step, _("Values by day of the year")
        ),
        when_label=when,
        value_label=f"{card.code} {numbers.unit_label(card.units)}".strip(),
        has_anomaly=anomaly_ok,
        ranked=plot.step in ("year", "month"),
        date_label=(_("Date of minimum") if low else _("Date of maximum")) if day_plot else "",
        citation=index_page.citation(
            analysis, card, plot, base, workspace.core_version(), timezone.localdate()
        ),
    )
    return render(request, "stations/result.html", context)


def context_runs(analysis, path: str) -> list:
    """The runs under way the Inputs panel would show (``workspace.inputs_panel``)."""
    if not workspace.set_up(analysis):
        return []
    return workspace.inputs_panel(analysis, path)["input_runs"]


def _step(analysis, card) -> dict | None:
    """The previous or next index for the context bar, named codes first (#218)."""
    if card is None:
        return None
    return {
        "url": analysis.url("result", card.key),
        "code": card.code,
        "name": card.title,
        "label": card.code,
    }

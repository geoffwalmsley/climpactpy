from django.conf import settings
from django.db import connection
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

import climpact
import climpact_web
from climpact_web.core import numbers
from climpact_web.core.forms import PatternDemoForm
from climpact_web.core.navigation import destination, gridded_steps
from climpact_web.help.tour import home_tour
from climpact_web.stations.workspace import years_text


@require_safe
def home(request):
    """The landing page: what Climpact does and the ways to start."""
    ways = []
    for key, description in (
        ("batch", _("Process many stations in one run from a batch metadata file.")),
        (
            "gridded",
            _("Calculate indices and thresholds on gridded netCDF data, and map the results.")
            if settings.IS_HOSTED
            else _(
                "Calculate indices and thresholds on gridded netCDF data on this computer, "
                "and map the results."
            ),
        ),
        ("help", _("Guides to preparing station files, base periods and reading results.")),
    ):
        d = destination(key)
        if d.available:
            ways.append({"label": d.label, "icon": d.icon, "url": d.url, "text": description})
    context = {
        "start_url": destination("station").url,
        "sample_url": destination("sample").url,
        "ways": ways,
        "tour_steps": home_tour(),
    }
    return render(request, "core/home.html", context)


@require_safe
def patterns(request):
    """Every component on one page, for design review and the accessibility audit.
    Only with ``PATTERN_LIBRARY`` (on by default when ``DEBUG`` is)."""
    if not settings.PATTERN_LIBRARY:
        raise Http404
    form = PatternDemoForm(
        data={
            "station_name": "Sydney Observatory Hill",
            "latitude": "-133.9",
            "base_start": "1990",
            "base_end": "1961",
            "variable": "tx",
            "method": "ols",
        }
    )
    form.is_valid()  # bound with mistakes, to show the inline errors
    return render(request, "core/patterns.html", pattern_context(form))


def add_review():
    """Three files on Add stations (#233): one read with its metadata, one with no
    coordinates yet, one that cannot be read."""
    from climpact_web.stations.add_stations import review
    from climpact_web.stations.models import Workspace

    def read(first, last, days, missing):
        summary = {
            "first_date": f"{first}-01-01",
            "last_date": f"{last}-12-31",
            "first_year": first,
            "last_year": last,
            "days": days,
            "missing": {},
            "missing_percent": missing,
        }
        return {"ok": True, "problems": [], "problem_count": 0, "warnings": [],
                "repeats": 0, "summary": summary}  # fmt: skip

    line = {"message": "", "line": 1, "text": "2000,1,1,0.0", "short": ""}
    line["short"] = _("line 1 has 4 values, expected 6 (year month day PR TX TN)")
    report = {
        "files": {
            "moruya_heads_069018.txt": read(1910, 2015, 38_716, 6.9),
            "coffs_harbour_059040.txt": read(1943, 2015, 26_663, 0.4),
            "taree_airport.csv": {
                "ok": False,
                "problems": [line],
                "problem_count": 1,
                "warnings": [],
                "repeats": 0,
                "summary": None,
            },  # fmt: skip
        },
        "metadata": {
            "name": "stations_nsw.txt",
            "rows": {
                "moruya_heads_069018.txt": {
                    "line": 2,
                    "latitude": -35.91,
                    "longitude": 150.15,
                    "params": {},
                }
            },  # fmt: skip
        },
    }
    return review(report, Workspace())


def overview_demo() -> dict:
    """The run status line and the Stations table of a workspace overview (#234), as on
    the Calculate board while its stations calculate: one row in each state."""
    from types import SimpleNamespace

    from climpact_web.stations import overview as ov

    def row(slug, name, ll, period, missing, quality, indices, significant=("–", "")):
        return ov.Row(
            station=SimpleNamespace(slug=slug),
            name=name,
            url="#stations-table",
            coordinates=ll,
            period=period,
            missing=missing,
            quality=quality,
            indices=indices,
            significant=significant[0],
            significant_label=significant[1],
        )

    usable = ov.Quality("usable", _("Usable"), _("· 5"), _(", 5 values look wrong"))
    rows = [
        row("sydney", _("Sydney Observatory Hill"), "33.86° S 151.21° E", "1936–2015", "0.1%",
            usable, ov.Indices("done", _("Done")),
            (_("22 of 80"), _("22 of 80 indices with a significant trend"))),
        row("nowra", _("Nowra RAN Air Station"), "34.95° S 150.54° E", "1955–2015", "3.2%",
            ov.Quality("ready", _("Ready")), ov.Indices("calculating", _("Calculating · 40%"),
                                                        percent=40)),
        row("moruya", _("Moruya Heads"), "35.91° S 150.15° E", "1910–2015", "6.9%",
            ov.Quality("locked", "–"), ov.Indices("not_run", _("Not run"),
                                                  fix_label=_("Fix the file"), fix_url="#")),
        row("port", _("Port Macquarie"), "31.43° S 152.87° E", "1995–2015", "0.0%",
            ov.Quality("checking", _("Checking…")), ov.Indices("waiting", _("Waiting"))),
        row("late", _("Late Start"), "30.00° S 140.00° E", "2000–2020", "0.3%",
            ov.Quality("ready", _("Ready")),
            ov.Indices("failed", _("Failed"), error=_("No data in the base period."),
                       fix_label=_("Change base period"), fix_url="#")),
    ]  # fmt: skip
    status = ov.StatusLine(
        "running",
        _("Calculating indices: 1 of 4 stations done."),
        _("About 25 s left. Finished stations open now. Moruya Heads was not run."),
        35,
        [ov.Link(_("Cancel"), "#stations-table", post=True)],
    )
    return {"overview_rows": rows, "overview_status": status}


def trends_demo() -> dict:
    """Trends across stations (#238): four stations by four indices, one without results,
    with each state of a cell, and the first column's interval plot."""
    from types import SimpleNamespace

    from climpact_web.stations import trend_grid

    indices = [  # code, short name, units, theme
        ("TXx", _("Hottest day"), "°C", "heat"),
        ("TN90p", _("Warm nights"), "%", "heat"),
        ("TX10p", _("Cool days"), "%", "cold"),
        ("PRCPTOT", _("Wet-day total"), "mm", "rain"),
    ]
    values = {  # slope, lower, upper per decade
        _("Sydney Observatory Hill"): [(0.21, 0.1, 0.33), (1.31, 0.8, 1.9), (-1.84, -2.4, -1.2),
                                       (4.1, -8.0, 16.0)],
        _("Newcastle Nobbys"): [(0.12, -0.03, 0.27), (1.62, 1.0, 2.2), (-0.6, -0.9, -0.3),
                                (-31.0, -55.0, -6.0)],
        _("Nowra RAN Air Station"): [(0.3, 0.12, 0.47), (0.7, -0.2, 1.6), (-1.05, -1.9, -0.2),
                                     (-12.0, -40.0, 15.0)],
    }  # fmt: skip

    def card(code, name, units, theme, slope, lower, upper):
        trend = {
            "valid": True,
            "slope": slope,
            "lower": lower,
            "upper": upper,
            "significant": lower > 0 or upper < 0,
            "slope_text": numbers.slope(slope, units),
            "per_decade_text": numbers.per_decade(slope, units),
            "interval_text": numbers.interval(lower, upper, units),
        }
        return SimpleNamespace(
            key=code.lower(), title=name, trend=trend, significant=trend["significant"],
            trend_units=numbers.trend_units(units),
            trend_units_title=_("percentage points") if units == "%" else "",
            theme=theme, hue=theme,
        )  # fmt: skip

    place = SimpleNamespace(url=lambda *args: "#trend-grid")
    stations = [
        trend_grid._Station(
            SimpleNamespace(name=name, source=True, why="", station=place),
            {i[0]: card(*i, *v) for i, v in zip(indices, rows, strict=True)},
        )
        for name, rows in values.items()
    ]
    stations.append(
        trend_grid._Station(
            SimpleNamespace(name=_("Moruya Heads"), source=None, why=_("failed"), station=place),
            {},
        )
    )
    found = trend_grid.grid_of(stations, [i[0] for i in indices], None)
    for plot in found.plots:
        plot.csv_url = "#trend-grid"
    return {"trends_demo": found}


def pattern_context(form):
    tab_items = [
        {"id": "tab-annual", "label": _("Annual"), "text": _("Annual values, 1936 to 2015.")},
        {"id": "tab-monthly", "label": _("Monthly"), "text": _("Monthly values by year.")},
        {"id": "tab-table", "label": _("Table"), "text": _("The same values as a table.")},
    ]
    return {
        "form": form,
        "steps_first": gridded_steps("files"),
        "steps_middle": gridded_steps("setup", urls={"files": "#"}),
        "steps_last": gridded_steps("results", urls={k: "#" for k in ("files", "setup")}),
        "table_columns": [
            {"label": _("Year"), "code": True},
            {"label": _("TXx (°C)"), "numeric": True},
            {"label": _("TNn (°C)"), "numeric": True},
            {"label": _("PRCPTOT (mm)"), "numeric": True},
        ],
        "table_rows": [
            ["2011", "41.2", "5.9", "1,162.4"],
            ["2012", "39.8", "4.7", "1,021.0"],
            ["2013", "45.8", "6.3", "1,032.8"],
            ["2014", "40.1", "5.2", "1,120.6"],
        ],
        "tab_items": tab_items,
        "add_review": add_review(),  # Add stations' review table (#233)
        # The verdict strip and coverage strip (#235), with the stress file's counts.
        "verdict_facts": [
            _("65,720 values checked"),
            _("21 look wrong (0.03%)"),
            _("105 worth a look"),
            _("25 missing (0.04%)"),
        ],
        "coverage_rows": [
            {
                "name": name,
                "cells": [
                    {"x": i, "step": 1 if not missing.get(i) else 2 if missing[i] <= 3 else 3}
                    for i in range(30)
                ],
                "total": total,
            }
            for name, missing, total in (
                (_("PR"), {2: 2, 11: 1, 27: 3}, _("6 days")),
                (_("TX"), {2: 1, 19: 4}, _("5 days")),
                (_("TN"), {2: 1, 8: 2, 19: 4}, _("7 days")),
            )
        ],
        "coverage_years": [1991, 1996, 2001, 2006, 2011, 2015, 2020],
        # The context bar (#227): as a station's, with a breadcrumb and the next station.
        # The workspace overview (#234): the run status line and the Stations table.
        **overview_demo(),
        **trends_demo(),  # Trends across stations (#238)
        "context_breadcrumb": [
            {"label": _("NSW coast"), "url": "#context-bar"},
            {"label": _("Station 1 of 6")},
        ],
        "context_next": {"label": _("Newcastle Nobbys"), "url": "#context-bar"},
        "context_provenance": [
            {"text": numbers.coordinates(-33.86, 151.21), "phone": False},
            {"text": years_text(1936, 2015), "phone": True},
            {"text": _("base %(start)s–%(end)s") % {"start": 1971, "end": 2000}, "phone": False},
            {"text": _("ET-SCI defaults"), "phone": False},
            {"text": "climpact 0.1.3", "phone": False},
        ],
        "file_rows": [
            {
                "name": name,
                "csv": {"label": f"{name} table", "kind": "csv", "size": csv},
                "png": {"label": f"{name} plot", "kind": "png", "size": png},
            }
            for name, csv, png in (("TXx", 3_400, 7_600), ("TNn", 3_300, 7_400))
        ],
        "stages": [
            {"label": _("Read station file"), "state": "done"},
            {"label": _("Quality control"), "state": "done"},
            {"label": _("Thresholds"), "state": "current"},
            {"label": _("Indices"), "state": "pending"},
            {"label": _("Trends"), "state": "pending"},
        ],
        "stages_failed": [
            {"label": _("Read station file"), "state": "done"},
            {"label": _("Quality control"), "state": "failed"},
        ],
        # A station's Indices (#236): the rail, the table and the detail pane.
        "indices_demo": indices_demo(),
        # A trend by the number rules (#226), as the index page's Trend statistic.
        "trend_demo": {
            "value": numbers.per_decade(0.21, "°C"),
            "interval": numbers.interval(0.08, 0.35, "°C"),
        },
        # The Inputs panel and a side sheet (#198).
        **inputs_demo(),
        # The New station page's steps and file card (#201).
        "setup_demo": setup_demo(),
        # The workspace tabs (#179), one with every status and one as on a first visit.
        "workspace_demo": workspace_demo(
            [
                ("quality", "attention"),
                ("results", "stale"),
                ("files", "running"),
            ],
            "results",
        ),
        "workspace_first": workspace_demo(
            [("quality", "todo"), ("results", "locked"), ("files", "locked")],
            "quality",
        ),
        # Quality's tab shows the checks' verdict (#222): checking, then each level.
        "workspace_verdicts": [
            (
                _("Example: checking"),
                workspace_demo(
                    [("quality", "checking"), ("results", "locked"), ("files", "locked")], "quality"
                ),
            ),
            (
                _("Example: ready"),
                workspace_demo(
                    [("quality", "ready"), ("results", "todo"), ("files", "done")], "quality"
                ),
            ),
            (
                _("Example: usable"),
                workspace_demo(
                    [("quality", "usable", 21), ("results", "done"), ("files", "done")], "quality"
                ),
            ),
            (
                _("Example: fix first"),
                workspace_demo(
                    [("quality", "fix", 1204), ("results", "running"), ("files", "done")], "quality"
                ),
            ),
        ],
        "stale_changes": [
            _("You changed the base period to %(new)s. These results use %(old)s.")
            % {"new": "1981–2010", "old": "1971–2000"}
        ],
        "spark_line": {
            "line": "M0 50L40 46L80 44L120 36L160 30L200 22L240 10",
            "trend": "M0 52L240 12",
        },
        "summary_items": [
            (_("Station"), "Sydney Observatory Hill"),
            (_("Period"), _("1936 to 2015")),
            (_("Base period"), _("1961 to 1990")),
            (_("Missing days"), _("1.2%")),
        ],
        "chart_legend": [
            {"label": _("Annual value"), "token": "--chart-1"},
            {"label": _("Linear trend"), "token": "--chart-trend"},
        ],
        "palette_groups": [
            (_("Categorical, in order"), [f"--chart-{i}" for i in range(1, 9)]),
            (
                _("Variables and marks"),
                ["--chart-tmax", "--chart-tmin", "--chart-prcp"]
                + ["--chart-trend", "--chart-trend-band", "--chart-flag"],
            ),
            (_("Sequential"), [f"--chart-seq-{i}" for i in range(1, 6)]),
            (_("Diverging"), [f"--chart-div-{i}" for i in range(1, 8)]),
            (
                _("Trend scale: a significant decrease or increase, weak and strong"),
                ["--chart-decrease-2", "--chart-decrease-1"]
                + ["--chart-increase-1", "--chart-increase-2"],
            ),
            (
                _("Coverage: complete, 1–3 days missing, 4 or more"),
                [f"--chart-coverage-{i}" for i in range(1, 4)],
            ),
            (
                _("Interface: ink for actions, blue for links, brand for the logo and focus"),
                ["--color-ink", "--color-ink-hover", "--color-link", "--color-link-hover"]
                + ["--color-brand", "--color-focus"]
                + ["--color-selected", "--color-text", "--color-text-muted"]
                + ["--color-border-strong"],
            ),
            (
                _("Status: the verdict and run state only"),
                ["--color-success", "--color-warning", "--color-danger"],
            ),
            (
                _("Theme hues, each with its tint"),
                [
                    f"--color-{hue}{tint}"
                    for hue in ("heat", "cold", "rain", "drought", "other")
                    for tint in ("", "-soft")
                ],
            ),
        ],
        "icons": [
            "upload",
            "download",
            "file",
            "folder",
            "layers",
            "grid",
            "station",
            "book",
            "terminal",
            "play",
            "chart",
            "bars",
            "table",
            "check",
            "check-circle",
            "circle",
            "dot-circle",
            "info",
            "help",
            "warning",
            "error",
            "close",
            "arrow-right",
            "chevron-down",
            "search",
            "refresh",
            "clock",
            "sliders",
            "thermometer",
            "droplet",
            "sun",
            "moon",
            "monitor",
            "globe",
            "external",
            "image",
            "flag",
            "lock",
        ],  # fmt: skip
    }


@never_cache
@require_safe
def healthz(request):
    """Health check for the load balancer and the ``climpact-web`` command: the app is up
    and its database answers. 200 with ``"status": "ok"``, else 503."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database = "ok"
    except Exception:  # any database failure means unhealthy
        database = "unavailable"
    healthy = database == "ok"
    return JsonResponse(
        {
            "status": "ok" if healthy else "error",
            "database": database,
            "version": climpact_web.__version__,
            "core_version": climpact.__version__,
        },
        status=200 if healthy else 503,
    )


def setup_demo() -> dict:
    """The New station page's file card (#201) for the pattern library: 80 years of daily
    data, three of them missing more than 15 days."""
    from climpact_web.stations.forms import UploadForm
    from climpact_web.stations.views import year_strip

    years = []
    for year in range(1936, 2016):
        days = 366 if year % 4 == 0 else 365
        short = {1948: 201, 1966: 340, 1996: 345}.get(year, days)
        years.append({"year": year, "days": days, "prcp": days, "tmax": short, "tmin": days})
    summary = {"first_year": 1936, "last_year": 2015, "days": 29220, "years": years}
    return {
        "summary": summary,
        "strip": year_strip(summary),
        "field": UploadForm(auto_id="pattern_%s")["station_file"],
    }


def indices_demo() -> dict:
    """The Indices' rail, table and detail pane (#236) as stations/_indices.html takes
    them: three rows of the Sydney sample, largest trend first (#263), the first selected,
    its chart drawn by the same code from an illustrative series."""
    from types import SimpleNamespace

    from climpact_web.stations import index_detail

    years = list(range(1936, 2016))
    rows = []
    demo = (
        # key, code, name, theme, hue, units; slope, its interval, mean, significant
        ("su", "SU", _("Summer days"), _("Heat"), "heat", "days", 5.15, 3.79, 6.54, 93.28, True),
        ("prcptot", "PRCPTOT", _("Wet-day total"), _("Rain"), "rain", "mm",
         4.6, -9.9, 19.2, 1210.1, False),
        ("tn10p", "TN10p", _("Cold nights"), _("Cold"), "cold", "%",
         -1.93, -2.4, -1.47, 13.12, True),
    )  # fmt: skip
    for i, (key, code, title, theme, hue, units, slope, lower, upper, mean, sig) in enumerate(demo):
        values = [mean + slope * (y - 1975.5) / 10 + 6 * ((y * 7919) % 13 - 6) / 6 for y in years]
        plot = SimpleNamespace(
            values=values,
            x=[float(y) for y in years],
            step="year",
            bars=False,
            trend=SimpleNamespace(valid=True, intercept=mean - slope * 3.95, slope=slope / 10),
        )
        trend = {
            "valid": True,
            "per_decade_text": numbers.per_decade(slope, units),
            "interval_text": numbers.interval(lower, upper, units),
        }
        card = {
            "key": key,
            "code": code,
            "title": title,
            "hue": hue,
            "chip": hue,
            "units": units,
            "trend": trend,
            "significant": sig,
            "trend_units_title": _("percentage points") if units == "%" else "",
            "definition": "",
            "search_text": key,
            "spark": {
                "line": "M0 50L40 46L80 44L120 36L160 30L200 22L240 10",
                "trend": "M0 52L240 12",
            },
        }
        named = SimpleNamespace(code=code, units=units, trend=trend)
        rows.append(
            {
                "card": card,
                "key": key,
                "theme": theme,
                "unit": units,
                "slope_unit": numbers.trend_units(units),
                "slope_pp": units == "%",
                "slope": numbers.slope(slope, units),
                "interval": trend["interval_text"],
                "mean": numbers.fixed(mean, numbers.slope_decimals(units)),
                "mean_text": numbers.with_unit(
                    numbers.fixed(mean, numbers.slope_decimals(units)), units
                ),
                "links": {"page": "#indices-demo", "csv": "#indices-demo", "png": "#indices-demo"},
                "chart": index_detail.chart(plot, (1971, 2000)),
                "chart_label": index_detail.summary(named, plot),
                "caption": index_detail.caption(named, plot),
                "used_label": index_detail.used_label(plot),
                "used": index_detail.values_used(named, plot),
                "position": i,
                "rank": 2 if sig else 1,
                "sort_trend": repr(slope),
                "show_href": f"?show={key}#detail-{key}",
                "selected": i == 0,
            }
        )
    columns = {
        key: {"key": key, "label": label, "name": label, "first": first, "href": "#indices-demo"}
        for key, label, first in (
            ("code", _("Code"), "ascending"),
            ("name", _("Index"), "ascending"),
            ("trend", _("Slope per decade"), "descending"),
            ("significance", _("Significant"), "descending"),
        )
    }
    return {
        "action": "#indices-demo",
        "rows": rows,
        "columns": columns,
        "chips": [
            {"key": "heat", "label": _("Heat"), "hue": "heat", "count": 30},
            {"key": "cold", "label": _("Cold"), "hue": "cold", "count": 12},
            {"key": "rain", "label": _("Rain"), "hue": "rain", "count": 13},
            {"key": "drought", "label": _("Drought"), "hue": "drought", "count": 9},
            {"key": "other", "label": _("Also measured"), "hue": "other", "count": 16},
        ],
        "series_years": "1936–2015",
        "selected": "su",
        "shown": 3,
        "total": 80,
        "significant_count": 22,
        "mean_trend": f"TMm {numbers.per_decade(0.19, '°C')}",
        "default_sort": "size",
        "sort_text": _("Sorted by the size of the trend, largest first."),
    }


def inputs_demo() -> dict:
    """The Inputs panel (#198) for the pattern library: the inputs of the Sydney sample,
    its base period changed and two index settings, and two sheets: the base period's, and
    the index settings', the long one (#199); and the same as the phone's Inputs bar (#203),
    with a run under way."""
    import uuid
    from types import SimpleNamespace

    from climpact_web.stations import workspace
    from climpact_web.stations.forms import BasePeriodForm
    from climpact_web.stations.forms_indices import IndexParamsForm
    from climpact_web.stations.workspace import PanelInput

    rows = [
        ("file", _("File"), _("29,220 days · 3 variables"), _("Replace"), False),
        ("station", _("Station"), numbers.coordinates(-33.86, 151.21), _("Edit"), False),
        ("base-period", _("Base period"), "1981–2010", _("Edit"), True),
        ("thresholds", _("Quality thresholds"), workspace.changed_text(0), _("Edit"), False),
        ("settings", _("Index settings"), workspace.changed_text(2), _("Edit"), False),
    ]
    form = BasePeriodForm({"base_start": 1981, "base_end": 2010})
    form.is_valid()
    inputs = [
        PanelInput(key, str(label), value, "#inputs-panel", str(edit), changed)
        for key, label, value, edit, changed in rows
    ]
    running = [SimpleNamespace(label=_("Recalculating"))]
    return {
        "inputs_bar_demo": workspace.inputs_bar("1981–2010", 2, inputs, running),
        "demo_analysis": SimpleNamespace(
            pk=uuid.UUID(int=0), workspace_id=uuid.UUID(int=0), slug="sydney"
        ),
        "inputs_demo": inputs,
        "sheet_demo_list": [
            {
                "key": "base-period",
                "title": _("Base period"),
                "intro": _("The years the percentile indices are compared with."),
                "form": form,
                "impact": workspace.impact("base-period"),
            },
            {
                "key": "settings",
                "title": _("Index settings"),
                "intro": _("The choices some indices depend on, and the files a run writes."),
                "form": IndexParamsForm(
                    initial={"rx_days": 3, "plot_title": ""}, station_title="Sydney"
                ),
                "impact": workspace.impact("settings"),
                "settings_source": "job",
            },
        ],
    }


def workspace_demo(states, current):
    """Workspace tabs for the pattern library: (section, state) pairs, or (section, state,
    values that look wrong) for Quality's verdict, as ``stations.workspace.sections`` gives
    them."""
    from climpact_web.stations.workspace import SECTIONS, Section

    labels = {key: label for key, label, _url in SECTIONS}
    return [
        Section(
            key,
            str(labels[key]),
            None if state == "locked" else "#workspace-tabs",
            state,
            key == current,
            *wrong,
        )  # fmt: skip
        for key, state, *wrong in states
    ]

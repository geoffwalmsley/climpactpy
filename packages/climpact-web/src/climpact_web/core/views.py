from django.conf import settings
from django.db import connection
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

import climpact
import climpact_web
from climpact_web.core.forms import PatternDemoForm
from climpact_web.core.navigation import destination, station_steps
from climpact_web.help.tour import home_tour


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
        "steps": station_steps("upload"),
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


def pattern_context(form):
    tab_items = [
        {"id": "tab-annual", "label": _("Annual"), "text": _("Annual values, 1936 to 2015.")},
        {"id": "tab-monthly", "label": _("Monthly"), "text": _("Monthly values by year.")},
        {"id": "tab-table", "label": _("Table"), "text": _("The same values as a table.")},
    ]
    return {
        "form": form,
        "steps_first": station_steps("upload"),
        "steps_middle": station_steps("indices", urls={"upload": "#", "qc": "#"}),
        "steps_last": station_steps("sector", urls={k: "#" for k in ("upload", "qc")}),
        "table_columns": [
            {"label": _("Year")},
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
                _("Interface"),
                ["--color-accent", "--color-success", "--color-warning", "--color-danger"]
                + ["--color-text", "--color-text-muted", "--color-border-strong"],
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

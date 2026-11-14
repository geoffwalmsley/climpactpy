"""``{% load charts %}{% chart_scripts %}``: the chart assets, for a page's ``head`` block.

Loads uPlot's stylesheet, ``css/charts.css``, uPlot and ``js/charts.js`` (both deferred),
and the chart text in the interface language as JSON (``#climpact-chart-text``), which
``charts.js`` reads for its buttons, read-out, table and messages. Only pages with a chart
load these (#82).
"""

from django import template
from django.templatetags.static import static
from django.utils.html import format_html, json_script
from django.utils.translation import gettext as _

register = template.Library()

ASSETS = {
    "uplot_css": "climpact_web/vendor/uplot/uPlot.min.css",
    "charts_css": "climpact_web/css/charts.css",
    "uplot_js": "climpact_web/vendor/uplot/uPlot.iife.min.js",
    "charts_js": "climpact_web/js/charts.js",
}


def chart_text() -> dict[str, str]:
    """The strings ``charts.js`` shows. ``{from}``, ``{to}``, ``{n}`` are filled in by
    the script."""
    return {
        "showing": _("Showing {from} to {to}."),
        "all": _("Showing the whole series."),
        "loadError": _("The chart could not be loaded. The CSV download still has the data."),
        "tableCaption": _("Values shown in the chart, {from} to {to}"),
        "tooMany": _(
            "{n} rows are in view. Zoom in to {max} rows or fewer to list them here, or "
            "download the CSV."
        ),
        "date": _("Date"),
        "year": _("Year"),
        "month": _("Month"),
        "day": _("Day of the year"),
        "dateOfEvent": _("Date of the event"),
        "flagged": _("Flagged"),
        "trend": _("Trend"),
        "missing": _("missing"),
        "wet": _("Wet (above 0)"),
        "dry": _("Dry (below 0)"),
        "exportTitle": _("Exported from Climpact"),
    }


@register.simple_tag
def chart_scripts():
    return format_html(
        '<link rel="stylesheet" href="{}">\n<link rel="stylesheet" href="{}">\n'
        '<script src="{}" defer></script>\n<script src="{}" defer></script>\n{}',
        static(ASSETS["uplot_css"]),
        static(ASSETS["charts_css"]),
        static(ASSETS["uplot_js"]),
        static(ASSETS["charts_js"]),
        json_script(chart_text(), "climpact-chart-text"),
    )

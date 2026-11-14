"""The first-run tour of the landing page (#81): a few steps pointing at parts of the page.

The steps are data for ``js/tour.js`` (``json_script``), with translated text. A step
whose ``target`` selector matches nothing on the page is skipped, so the tour survives
layout changes. Without JavaScript there is no tour; the page explains itself anyway.
"""

from django.conf import settings
from django.utils.translation import gettext as _

STORAGE_KEY = "climpact-tour"  # localStorage: "done" once finished or dismissed


def home_tour() -> list[dict[str, str]]:
    return [
        {
            "target": "#hero-actions",
            "title": _("Start here"),
            "text": _(
                "Load a station file of daily data, or try Climpact first with the sample "
                "data for Sydney. Nothing is calculated until you ask."
            ),
        },
        {
            "target": "#how-title",
            "title": _("Four steps"),
            "text": _(
                "Load the data, check its quality, calculate the indices, then explore and "
                "download the results. Comparing with sector data is optional."
            ),
        },
        {
            "target": "#ways-title",
            "title": _("Many stations at once"),
            "text": _("Process many stations in one run from a batch metadata file.")
            if settings.IS_HOSTED
            else _(
                "Process many stations in one run from a batch metadata file, or "
                "gridded netCDF data on this computer."
            ),
        },
        {
            "target": ".site-nav a[data-nav='help']",
            "title": _("Help when you need it"),
            "text": _(
                "Guides to station files, base periods, quality checks, indices and trends. "
                "Look for the question-mark links next to fields for a short explanation."
            ),
        },
        {
            "target": ".site-nav a[data-nav='jobs']",
            "title": _("Your calculations"),
            "text": _(
                "Calculations run in the background. Come back to them here, even after "
                "closing the page."
            ),
        },
    ]

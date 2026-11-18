"""The first-run tour of the landing page (#81): a few steps pointing at parts of the page.

The steps are data for ``js/tour.js`` (``json_script``), with translated text. A step
whose ``target`` selector matches nothing on the page is skipped, so the tour survives
layout changes. Without JavaScript there is no tour; the page explains itself anyway.
"""

from django.utils.translation import gettext as _

STORAGE_KEY = "climpact-tour"  # localStorage: "done" once finished or dismissed


def home_tour() -> list[dict[str, str]]:
    return [
        {
            "target": "#hero-actions",
            "title": _("Start here"),
            "text": _(
                "Get started with your own station files, or see an example: the sample "
                "station for Sydney, opened on its indices."
            ),
        },
        {
            "target": "#how-title",
            "title": _("A workspace of stations"),
            "text": _(
                "Add one station or a whole network. Each station's data is checked and its "
                "indices calculated with the defaults; change the settings later and what "
                "they affect is calculated again."
            ),
        },
        {
            "target": "#app-help",
            "title": _("Help when you need it"),
            "text": _(
                "Help opens the guide to the page you are on. Each section has a Help "
                "button of its own, at the end of its heading, for a short explanation."
            ),
        },
        {
            "target": ".site-nav a[data-nav='workspaces']",
            "title": _("Workspaces"),
            "text": _(
                "Every workspace you start is listed here. Calculations run in the "
                "background: come back to them, even after closing the page."
            ),
        },
    ]

"""Where the app's main destinations live, for the header and the landing page (#71).
No page has a step indicator any more: the single station's sections are tabs since #179
(``stations.workspace``), the batch's stations are the workspace's since #234, and a
gridded run is a place with tabs since #289 (a breadcrumb before it starts).

The screens arrive in later tickets (#76-#81, #85). Each destination names the URL its
ticket will add; until that URL exists the destination resolves to ``None``, so the
landing page shows it as "available soon" and the header leaves it out. Adding the URL
is all a later ticket has to do.
"""

from dataclasses import dataclass

from django.conf import settings
from django.urls import NoReverseMatch, reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class Destination:
    key: str
    url_name: str
    label: Promise
    icon: str
    in_nav: bool = True
    gridded: bool = False  # offered only when gridded runs are (settings.GRIDDED_ENABLED)
    # The URL prefixes whose pages the link is current on, besides its own address, as
    # URL names or paths: the header's Workspaces is current on every station and batch
    # page too (#227), all under ``/w/`` since #256.
    sections: tuple[str, ...] = ()

    @property
    def url(self) -> str | None:
        return url_or_none(self.url_name)

    @property
    def available(self) -> bool:
        return not (self.gridded and not settings.GRIDDED_ENABLED)


# The header (#227, the workspace design of #230): Climpact, then Workspaces and Gridded;
# Index reference and Help at its end (base.html). Single station, Batch and Your
# calculations are no longer header links: Workspaces (#242) replaced them, and the
# landing page leads to Get started (Add stations).
DESTINATIONS = (
    Destination(
        "workspaces",
        "stations:workspaces",
        _("Workspaces"),
        "layers",
        sections=("stations:add", "/w/"),
    ),
    # Add stations (#233) is the one way in, for one station or many.
    Destination("station", "stations:add", _("Single station"), "station", in_nav=False),
    Destination("sample", "stations:add_sample", _("Try with sample data"), "play", in_nav=False),
    Destination("batch", "stations:add", _("Batch"), "layers", in_nav=False),
    Destination("gridded", "gridded:start", _("Gridded"), "grid", gridded=True),
    # Not a header link since #197: Help at the end of the header opens the current
    # page's guide (page_help below), and the landing page links the help.
    Destination("help", "help:index", _("Help"), "book", in_nav=False),
)


def url_or_none(url_name: str, *args) -> str | None:
    try:
        return reverse(url_name, args=args or None)
    except NoReverseMatch:
        return None


def destination(key: str) -> Destination:
    return next(d for d in DESTINATIONS if d.key == key)


def nav_items(request) -> list[dict]:
    """Header links: destinations that exist and are offered in this mode. ``current`` is
    "page" on the destination's own address and "true" on the pages under it."""
    items = []
    path = request.path if request is not None else ""
    for d in DESTINATIONS:
        url = d.url
        if d.in_nav and d.available and url:
            sections = [s if s.startswith("/") else url_or_none(s) for s in d.sections]
            prefixes = [p for p in (url, *sections) if p and p != "/"]
            current = "page" if path == url else ""
            if not current and any(path.startswith(p) for p in prefixes):
                current = "true"
            items.append(
                {"key": d.key, "label": d.label, "url": url, "icon": d.icon, "current": current}
            )
    return items


def index_reference_url() -> str | None:
    """The header's Index reference (#227): the index reference's list of every index
    (#319, ``/help/indices/``)."""
    return url_or_none("help:index_reference")


def index_reference_current(request) -> str:
    """Index reference is current (#325) on ``/help/indices/`` ("page") and on the pages
    under it, each index's (#319; "true"); Help is not, there."""
    url = (index_reference_url() or "").split("#", 1)[0]
    path = request.path if request is not None else ""
    if not url:
        return ""
    if path == url:
        return "page"
    return "true" if path.startswith(url) else ""


# ---- The header's Help button (#197) ---------------------------------------------------

# The guide each page's Help button opens, by URL namespace and name; a namespace alone
# covers its other pages. Pages without one open the help's index.
PAGE_GUIDES = {
    "stations:add": "station-file",
    "stations:add_to": "station-file",
    "stations:add_review": "station-file",
    "stations:setup": "station-file",
    "stations:qc": "quality-control",
    "stations:results": "indices",
    "stations:results_progress": "indices",
    "stations:result": "indices",
    "stations:downloads": "indices",
    "stations:sector": "sector",
    "stations": "station-file",
    "batch": "batch",
    "gridded": "gridded",
}


def page_help(request) -> dict | None:
    """The header's Help button: the guide of the page shown, or the help's index."""
    from climpact_web.help.guides import get_guide

    match = getattr(request, "resolver_match", None) if request is not None else None
    slug = None
    if match is not None:
        slug = PAGE_GUIDES.get(match.view_name) or PAGE_GUIDES.get(match.namespace)
    guide = get_guide(slug) if slug else None
    if guide is not None:
        return {"url": guide.url, "title": guide.title, "current": False}
    url = url_or_none("help:index")
    if url is None:
        return None
    # Current on the help's pages (#325), but not where Index reference is.
    current = (
        match is not None and match.namespace == "help" and not index_reference_current(request)
    )
    return {"url": url, "title": None, "current": current}

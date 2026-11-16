"""Where the app's main destinations live, for the header, the landing page and the step
indicator of the batch and gridded flows (#71). The single station has no steps since
#179: its sections are tabs (``stations.workspace``).

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
    # The URL whose pages the link is current on, when not the link's own: the single
    # station's link opens New station (/station/new, #201) and is current on /station/...
    section_name: str = ""

    @property
    def url(self) -> str | None:
        return url_or_none(self.url_name)

    @property
    def available(self) -> bool:
        return not (self.gridded and not settings.GRIDDED_ENABLED)


DESTINATIONS = (
    Destination(
        "station", "stations:new", _("Single station"), "station", section_name="stations:upload"
    ),
    Destination("sample", "stations:sample", _("Try with sample data"), "play", in_nav=False),
    Destination("batch", "batch:start", _("Batch"), "layers"),
    Destination("gridded", "gridded:start", _("Gridded"), "grid", gridded=True),
    # Not a header link since #197: the Help button at the end of the header opens the
    # current page's guide (page_help below), and the landing page links the help.
    Destination("help", "help:index", _("Help"), "book", in_nav=False),
    Destination("jobs", "jobs:list", _("Your calculations"), "clock"),
)


def url_or_none(url_name: str) -> str | None:
    try:
        return reverse(url_name)
    except NoReverseMatch:
        return None


def destination(key: str) -> Destination:
    return next(d for d in DESTINATIONS if d.key == key)


def nav_items(request) -> list[dict]:
    """Header links: destinations that exist and are offered in this mode."""
    items = []
    path = request.path if request is not None else ""
    for d in DESTINATIONS:
        url = d.url
        if d.in_nav and d.available and url:
            section = url_or_none(d.section_name) if d.section_name else url
            current = path == url or (section != "/" and path.startswith(section))
            items.append(
                {"key": d.key, "label": d.label, "url": url, "icon": d.icon, "current": current}
            )
    return items


# ---- The header's Help button (#197) ---------------------------------------------------

# The guide each page's Help button opens, by URL namespace and name; a namespace alone
# covers its other pages. Pages without one open the help's index.
PAGE_GUIDES = {
    "stations:new": "station-file",
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
    current = match is not None and match.namespace == "help"
    return {"url": url, "title": None, "current": current}


# ---- Step indicator --------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    key: str
    label: Promise
    url_name: str
    optional: bool = False


@dataclass
class StepState:
    key: str
    label: Promise
    state: str  # "complete", "current" or "upcoming"
    url: str | None = None
    optional: bool = False
    number: int = 0


# The gridded steps (#85): choose the netCDF files, check them and set the parameters, then
# follow the run and explore the results.
GRIDDED_STEPS = (
    Step("files", _("Choose files"), "gridded:start"),
    Step("setup", _("Check and set up"), "gridded:setup"),
    Step("results", _("Calculate and explore"), "gridded:results"),
)


# The batch page's steps (#80): load the files, check the stations and choose the options,
# then follow the run and download the results.
BATCH_STEPS = (
    Step("upload", _("Load files"), "batch:start"),
    Step("check", _("Check stations"), "batch:check"),
    Step("results", _("Calculate and download"), "batch:results"),
)


def batch_steps(current: str, urls: dict[str, str] | None = None) -> list[StepState]:
    """The batch steps with ``current`` marked. Steps before it are complete and link back
    when ``urls`` gives their address (a run's own URLs)."""
    return flow_steps(BATCH_STEPS, current, urls)


def gridded_steps(current: str, urls: dict[str, str] | None = None) -> list[StepState]:
    """The gridded steps with ``current`` marked, as :func:`batch_steps`."""
    return flow_steps(GRIDDED_STEPS, current, urls)


def flow_steps(
    definition: tuple[Step, ...], current: str, urls: dict[str, str] | None = None
) -> list[StepState]:
    keys = [s.key for s in definition]
    if current not in keys:
        raise ValueError(f"unknown step {current!r}; expected one of {keys}")
    position = keys.index(current)
    urls = urls or {}
    steps = []
    for number, step in enumerate(definition, start=1):
        if number - 1 < position:
            state = "complete"
        elif number - 1 == position:
            state = "current"
        else:
            state = "upcoming"
        steps.append(
            StepState(
                key=step.key,
                label=step.label,
                state=state,
                url=urls.get(step.key) if state == "complete" else None,
                optional=step.optional,
                number=number,
            )
        )
    return steps

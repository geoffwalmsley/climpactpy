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
# calculations are no longer header links: the landing page starts a station or a batch.
# Until the Workspaces page lands (#242), Workspaces opens the list of calculations.
DESTINATIONS = (
    Destination(
        "workspaces",
        "jobs:list",
        _("Workspaces"),
        "layers",
        sections=("stations:upload", "batch:start", "/w/"),
    ),
    Destination("station", "stations:new", _("Single station"), "station", in_nav=False),
    Destination("sample", "stations:sample", _("Try with sample data"), "play", in_nav=False),
    Destination("batch", "batch:start", _("Batch"), "layers", in_nav=False),
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
    """The header's Index reference (#227): the definition of every index, in the guide
    to the indices, until an index reference page of its own exists."""
    url = url_or_none("help:guide", "indices")
    return f"{url}#the-indices" if url else None


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
    Step("results", _("Calculate and download"), "stations:workspace"),
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

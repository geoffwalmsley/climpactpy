"""Where the app's main destinations live, for the header, the landing page and the step
indicator (#71).

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
    local_only: bool = False  # offered only by the local install (gridded runs, as in R)

    @property
    def url(self) -> str | None:
        return url_or_none(self.url_name)

    @property
    def available(self) -> bool:
        return not (self.local_only and settings.IS_HOSTED)


DESTINATIONS = (
    Destination("station", "stations:upload", _("Single station"), "station"),
    Destination("sample", "stations:sample", _("Try with sample data"), "play", in_nav=False),
    Destination("batch", "batch:start", _("Batch"), "layers"),
    Destination("gridded", "gridded:start", _("Gridded"), "grid", local_only=True),
    Destination("help", "help:index", _("Help"), "book"),
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
            current = path == url or (url != "/" and path.startswith(url))
            items.append({"label": d.label, "url": url, "icon": d.icon, "current": current})
    return items


# ---- Step indicator --------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    key: str
    label: Promise
    url_name: str
    optional: bool = False


STATION_STEPS = (
    Step("upload", _("Load data"), "stations:upload"),
    Step("qc", _("Check quality"), "stations:qc"),
    Step("indices", _("Calculate indices"), "stations:indices"),
    Step("results", _("Results and downloads"), "stations:results"),
    Step("sector", _("Compare with sector data"), "stations:sector", optional=True),
)


@dataclass
class StepState:
    key: str
    label: Promise
    state: str  # "complete", "current" or "upcoming"
    url: str | None = None
    optional: bool = False
    number: int = 0


# The batch page's steps (#80): load the files, check the stations and choose the options,
# then follow the run and download the results.
BATCH_STEPS = (
    Step("upload", _("Load files"), "batch:start"),
    Step("check", _("Check stations"), "batch:check"),
    Step("results", _("Calculate and download"), "batch:results"),
)


def station_steps(current: str, urls: dict[str, str] | None = None) -> list[StepState]:
    """The single-station steps with ``current`` marked. Steps before it are complete and
    link back when ``urls`` gives their address (a run's own URLs, from #76-#78)."""
    return flow_steps(STATION_STEPS, current, urls)


def batch_steps(current: str, urls: dict[str, str] | None = None) -> list[StepState]:
    """The batch steps with ``current`` marked, as :func:`station_steps`."""
    return flow_steps(BATCH_STEPS, current, urls)


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

"""The help frame (#325): the help's contents, shared by every help page, and the help
home's lists.

Every help page shows the same contents at the inline start: "Search help", "Help home",
then three groups, Guides (in ``GUIDE_ORDER``), Reference and More. They are plain links,
so a reader without JavaScript and a crawler reach every help page from any other. The
current page's link has ``aria-current="page"``.

The Reference pages (the index reference, the command line and the file formats) come
with #319. Each names the URL its page will have; until that URL exists the link resolves
to ``None`` and is left out, as the header's destinations are (``core.navigation``), so
adding the URL is all #319 has to do. The help home's Reference cards fall back to the
guide sections that hold the same things meanwhile.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from climpact_web.core.navigation import url_or_none
from climpact_web.help.guides import GUIDE_ORDER, get_guide
from climpact_web.help.indices import catalogue

# Guides listed under More rather than Guides: they are not a step of the work.
MORE_GUIDES = ("faq", "accessibility")


@dataclass(frozen=True)
class Reference:
    """A Reference page of #319: where it will live, and what stands in for it on the
    help home until it does (a guide and its section, or nothing)."""

    key: str
    url_name: str
    label: Promise
    args: tuple[str, ...] = ()
    # Current on the pages under it too: the index reference on each index's page.
    section: bool = False
    children: tuple[Reference, ...] = ()
    fallback: tuple[str, str] | None = None  # (guide slug, anchor) for the home's card

    @property
    def url(self) -> str | None:
        return url_or_none(self.url_name, *self.args)


REFERENCE = (
    Reference(
        "index-reference",
        "help:index_reference",
        _("Index reference"),
        section=True,
        fallback=("indices", "the-indices"),
    ),
    Reference("command-line", "help:command_line", _("Command line")),
    Reference(
        "formats",
        "help:formats",
        _("File formats"),
        children=(
            Reference("station-file", "help:format", _("Station file"), ("station-file",)),
            Reference(
                "batch-metadata", "help:format", _("Batch metadata file"), ("batch-metadata",)
            ),
            Reference(
                "gridded-inputs", "help:format", _("Gridded input files"), ("gridded-inputs",)
            ),
            Reference("sector-data", "help:format", _("Sector data file"), ("sector-data",)),
        ),
        fallback=("gridded", "input-files"),
    ),
)


def _link(label, url: str, path: str, section: bool = False, children=()) -> dict:
    current = path == url or (section and path.startswith(url))
    return {"label": label, "url": url, "current": current, "children": list(children)}


def contents(path: str) -> dict:
    """The help's contents for the page at ``path``: the home link and the groups, each
    link with ``current`` set on the page shown."""
    guides = [get_guide(slug) for slug in GUIDE_ORDER if slug not in MORE_GUIDES]
    reference = []
    for item in REFERENCE:
        url = item.url
        if url is None:
            continue
        children = [_link(c.label, c.url, path) for c in item.children if c.url]
        reference.append(_link(item.label, url, path, item.section, children))
    faq, accessibility = (get_guide(slug) for slug in MORE_GUIDES)
    more = [
        _link(faq.title, faq.url, path),
        _link(_("Help topics, A to Z"), reverse("help:topics"), path),
        _link(accessibility.title, accessibility.url, path),
    ]
    groups = [
        {
            "key": "guides",
            "label": _("Guides"),
            "links": [_link(g.title, g.url, path) for g in guides if g],
        },
        {"key": "reference", "label": _("Reference"), "links": reference},
        {"key": "more", "label": _("More"), "links": more},
    ]
    return {
        "home": _link(_("Help home"), reverse("help:index"), path),
        "groups": [g for g in groups if g["links"]],
    }


# ---- The help home (the Help board) ----------------------------------------------------

# The home's Reference cards: what each area holds, and a line of what it is about.
CARD_TEXT = {
    "index-reference": (
        _(
            "All %(count)s ET-SCI indices: definition, unit, settings, missing-data rule "
            "and file names."
        ),
        "TX90p · Rx5day · SPI · …",
    ),
    "command-line": (
        _(
            "Install the climpact package and run stations, batches and grids without the "
            "browser. Every option of every command."
        ),
        "climpact run · batch · gridded-indices",
    ),
    "formats": (
        _(
            "The station file, the batch metadata file, the gridded netCDF inputs and the "
            "sector data file, with examples."
        ),
        "year month day prcp tmax tmin",
    ),
}

# The questions the help home lists, by their anchor in the questions guide.
COMMON_QUESTIONS = ("file-refused", "years-missing", "percentile-missing", "same-as-r", "data-kept")


def reference_cards() -> list[dict]:
    """The help home's Reference cards: each area's page, or until #319 adds it the guide
    section that holds the same things; an area with neither is left out."""
    cards = []
    for item in REFERENCE:
        url = item.url
        if url is None and item.fallback:
            slug, anchor = item.fallback
            url = f"{reverse('help:guide', args=[slug])}#{anchor}"
        if url is None:
            continue
        text, hint = CARD_TEXT[item.key]
        cards.append(
            {
                "label": item.label,
                "url": url,
                "text": text % {"count": len(catalogue())},
                "hint": hint,
            }
        )
    return cards


def common_questions() -> list[dict]:
    """The help home's common questions: links into the questions guide, named as its
    headings are."""
    faq = get_guide("faq")
    names = {item["id"]: item["name"] for item in faq.toc}
    return [{"label": names[key], "url": f"{faq.url}#{key}"} for key in COMMON_QUESTIONS]

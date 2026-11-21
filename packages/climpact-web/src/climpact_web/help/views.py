from importlib import resources

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_safe

from climpact_web.core.navigation import url_or_none
from climpact_web.help import reference
from climpact_web.help.contents import MORE_GUIDES, REFERENCE, common_questions, reference_cards
from climpact_web.help.guides import (
    FORMAT_PREFIX,
    GUIDE_ORDER,
    all_guides,
    get_guide,
    guide_slug,
    search,
)
from climpact_web.help.indices import catalogue
from climpact_web.help.sections import (
    UnknownSection,
    UnknownTopic,
    get_section,
    parse_topics,
    section_context,
)
from climpact_web.help.seo import page_meta
from climpact_web.help.topics import KINDS, topics

HOME_LEAD = (
    "Help for Climpact: preparing data, choosing the settings and reading the results, the "
    "definition of every ET-SCI index, the command line and the file formats."
)
TOPICS_LEAD = (
    "Every short explanation shown next to the fields and results, with a link to the guide "
    "that says more."
)


def sample_data() -> dict:
    """Where each flow's sample lives; ``None`` for a screen that does not exist yet."""
    return {
        "station_sample": url_or_none("stations:add_sample"),
        "station_file": url_or_none("stations:sample_file"),
        "batch_sample": url_or_none("stations:add_sample_batch"),
        "batch_metadata": url_or_none("batch:sample_metadata"),
        "gridded_sample": url_or_none("gridded:sample") if settings.GRIDDED_ENABLED else None,
        "sector_file": url_or_none("stations:sector_sample"),
    }


@require_safe
def index(request):
    """The help home (#325, the Help board): search, the Reference cards, the guides in
    order, common questions, sample data and the tour."""
    context = {
        "guides": [g for g in all_guides() if g.slug not in MORE_GUIDES],
        "reference_cards": reference_cards(),
        "questions": common_questions(),
        "faq": get_guide("faq"),
        "page_meta": page_meta(request, HOME_LEAD),
        **sample_data(),
    }
    return render(request, "help/index.html", context)


@require_safe
def guide(request, slug):
    slug = guide_slug(slug)
    page = get_guide(slug) if slug else None
    if page is None:
        raise Http404
    position = GUIDE_ORDER.index(slug)
    previous = get_guide(GUIDE_ORDER[position - 1]) if position > 0 else None
    following = get_guide(GUIDE_ORDER[position + 1]) if position + 1 < len(GUIDE_ORDER) else None
    context = {
        "guide": page,
        "previous": previous,
        "next": following,
        "toc": page.toc,
        "page_meta": page_meta(request, page.summary),
    }
    return render(request, "help/guide.html", context)


@require_safe
def topic_list(request):
    """Every help topic, grouped, A to Z within each group: the index of topics."""
    groups = {}
    for topic in topics().values():
        groups.setdefault(topic.kind, []).append(topic)
    ordered = [
        {"key": kind, "label": label, "topics": sorted(groups.get(kind, []), key=_sort_key)}
        for kind, label in KINDS.items()
        if groups.get(kind)
    ]
    toc = [{"id": f"group-{g['key']}", "name": g["label"]} for g in ordered]
    meta = page_meta(request, TOPICS_LEAD)
    return render(request, "help/topics.html", {"groups": ordered, "toc": toc, "page_meta": meta})


def _sort_key(topic):
    return str(topic.title).casefold()


@require_safe
def search_view(request):
    query = request.GET.get("q", "").strip()[:200]
    results = search(query) if query else []
    context = {"query": query, "results": results}
    context["page_meta"] = page_meta(request, _("Search the help."), index=False)
    if request.headers.get("HX-Request"):
        return render(request, "help/_results.html", context)
    return render(request, "help/search.html", context)


@require_safe
def section(request, section_id):
    """A section's help on its own page (#177): where the ⓘ leads without JavaScript.
    ``?topics=`` adds the screen's own topics, as the ⓘ of an index page does."""
    try:
        found = get_section(section_id)
        extra = parse_topics(request.GET.get("topics", "")[:500])
    except (UnknownSection, UnknownTopic):
        raise Http404 from None
    context = section_context(found, extra)
    # An index page's help is named after its index rather than "This index".
    context["title"] = context["topics"][0].title if extra else found.title
    context["page_meta"] = page_meta(request, context["title"], index=False)
    return render(request, "help/section.html", context)


# ---- The Reference pages (#319) ----------------------------------------------------------

ABBREVIATIONS = (
    ("TX", gettext_lazy("daily maximum temperature")),
    ("TN", gettext_lazy("daily minimum")),
    ("TM", gettext_lazy("mean of TX and TN")),
    ("DTR", "TX − TN"),
    ("PR", gettext_lazy("daily precipitation")),
    (gettext_lazy("wet day"), "PR ≥ 1 mm"),
    (
        gettext_lazy("base period"),
        gettext_lazy("the years percentiles come from, 1971–2000 by default"),
    ),
)


def _crumbs(*items) -> list[dict]:
    """The breadcrumb after Help: (label, url or None) pairs."""
    return [{"label": label, "url": url} for label, url in items]


def _calculate_it(code: str) -> dict:
    return {
        "title": _("Calculate it"),
        "text": _("%(code)s for your own stations, with its trend and chart.") % {"code": code},
        "label": _("Get started"),
        "url": reverse("stations:add"),
    }


@require_safe
def index_reference(request):
    """The index reference (the HelpIndices board): every index by theme, with Find and
    the theme pills as a GET form (``?q=``, ``?theme=``); filtered, it is noindex with a
    canonical link to the plain list."""
    query = request.GET.get("q", "").strip()[:100]
    theme = request.GET.get("theme", "").strip()
    if theme not in {t.key for t, _members in reference.themes()}:
        theme = ""
    groups, shown, total = reference.list_rows(query, theme)
    filtered = bool(query or theme)
    lead = _(
        "The %(count)s indices Climpact calculates, as defined by the WMO Expert Team on "
        "Sector-specific Climate Indices (ET-SCI), which include the 27 ETCCDI indices. Each "
        "has a page with its definition, unit, settings and the files it is written to."
    ) % {"count": total}
    context = {
        "lead": lead,
        "abbreviations": ABBREVIATIONS,
        "groups": groups,
        "pills": reference.theme_pills(theme),
        "query": query,
        "theme": theme,
        "shown": shown,
        "total": total,
        "filtered": filtered,
        "crumbs": _crumbs((_("Reference"), None)),
        "page_meta": page_meta(
            request,
            lead,
            index=not filtered,
            canonical=reverse("help:index_reference") if filtered else None,
        ),
    }
    return render(request, "help/index_reference.html", context)


@require_safe
def index_csv(request):
    """The core's ``climate.indices.csv``, every definition as R has it, for scripts."""
    text = resources.files("climpact.data").joinpath("climate.indices.csv").read_text()
    response = HttpResponse(text, content_type="text/tab-separated-values; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="climate.indices.csv"'
    return response


@require_safe
def index_page(request, code):
    """One index (the HelpIndex board) at its lowercase short name; other spellings and
    output names redirect there."""
    canonical = reference.canonical_slug(code)
    if canonical is None:
        raise Http404
    if canonical != code:
        return redirect("help:index", canonical, permanent=True)
    info = next(i for i in catalogue() if reference.slug(i) == canonical)
    found = reference.page(info)
    theme = found["theme"]
    toc = [
        {"id": "facts", "name": _("At a glance")},
        {"id": "calculation", "name": _("How it is calculated")},
        {"id": "files", "name": _("In the result files")},
        {"id": "command-line", "name": _("On the command line")},
        {"id": "related", "name": _("Related indices")},
        {"id": "references", "name": _("References")},
    ]
    theme_url = f"{reverse('help:index_reference')}?theme={theme.key}" if theme else None
    context = {
        "page": found,
        "toc": toc,
        "help_action": _calculate_it(info.name),
        "crumbs": _crumbs(
            (_("Index reference"), reverse("help:index_reference")),
            (theme.label if theme else "", theme_url),
        ),
        "files_guide": reference_url("indices", "the-index-files"),
        "page_meta": page_meta(request, found["lead_text"]),
    }
    return render(request, "help/index_page.html", context)


def reference_url(slug: str, anchor: str) -> str:
    return f"{get_guide(slug).url}#{anchor}"


@require_safe
def command_line(request):
    """The command-line guide (the HelpCli board): guides/<language>/command-line.md with
    the option tables generated from the ``climpact`` parser."""
    page = get_guide("command-line")
    context = {
        "guide": page,
        # The commands, not each of their option tables.
        "toc": [{**item, "children": []} for item in page.toc],
        "crumbs": _crumbs((_("Reference"), None)),
        "page_title": _("Command line: climpact run, batch and gridded"),
        "page_meta": page_meta(request, page.summary),
    }
    return render(request, "help/guide.html", context)


FORMAT_HINTS = {
    "station-file": "year month day prcp tmax tmin",
    "batch-metadata": "station_file latitude longitude wsdin …",
    "gridded-inputs": "CF netCDF: tasmax, tasmin, pr",
    "sector-data": "Year,value: one row per year",
}


def _format_cards(current: str = "") -> list[dict]:
    formats = next(item for item in REFERENCE if item.key == "formats")
    cards = []
    for child in formats.children:
        slug = child.args[0]
        if slug == current:
            continue
        page = get_guide(FORMAT_PREFIX + slug)
        cards.append(
            {
                "label": child.label,
                "url": child.url,
                "hint": FORMAT_HINTS[slug],
                "summary": page.summary if page else "",
            }
        )
    return cards


@require_safe
def formats(request):
    """The file formats: a card for each format page."""
    lead = _(
        "The files Climpact reads: the station file, the batch metadata file, the gridded "
        "netCDF inputs and the sector data file, each with an example and its rules."
    )
    context = {
        "lead": lead,
        "cards": _format_cards(),
        "crumbs": _crumbs((_("Reference"), None)),
        "page_meta": page_meta(request, lead),
    }
    return render(request, "help/formats.html", context)


@require_safe
def format_page(request, slug):
    """A file format (the HelpFormat board): a specification, from
    guides/<language>/format-<slug>.md."""
    page = get_guide(FORMAT_PREFIX + slug)
    if page is None:
        raise Http404
    toc = list(page.toc)
    if page.html.lstrip().startswith('<pre id="example"'):
        toc.insert(0, {"id": "example", "name": _("Example"), "children": []})
    toc.append({"id": "other-formats", "name": _("Other formats"), "children": []})
    context = {
        "guide": page,
        "toc": toc,
        "crumbs": _crumbs((_("File formats"), reverse("help:formats"))),
        "other_formats": _format_cards(slug),
        "help_action": check_a_file() if slug in ("station-file", "batch-metadata") else None,
        "page_meta": page_meta(request, page.summary),
    }
    return render(request, "help/guide.html", context)


def check_a_file() -> dict:
    return {
        "title": _("Check a file"),
        "text": _(
            "Add it to a workspace: the file is read and every problem listed before "
            "anything is calculated."
        ),
        "label": _("Get started"),
        "url": reverse("stations:add"),
    }

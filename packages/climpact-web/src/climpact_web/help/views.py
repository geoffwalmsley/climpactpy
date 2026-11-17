from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_safe

from climpact_web.core.navigation import url_or_none
from climpact_web.help.guides import GUIDE_ORDER, all_guides, get_guide, search
from climpact_web.help.sections import (
    UnknownSection,
    UnknownTopic,
    get_section,
    parse_topics,
    section_context,
)
from climpact_web.help.topics import KINDS, topics


def sample_data() -> dict:
    """Where each flow's sample lives; ``None`` for a screen that does not exist yet."""
    return {
        "station_sample": url_or_none("stations:add_sample"),
        "station_file": url_or_none("stations:sample_file"),
        "batch_sample": url_or_none("stations:add_sample_batch"),
        "batch_metadata": url_or_none("batch:sample_metadata"),
        "gridded_url": None if settings.IS_HOSTED else url_or_none("gridded:start"),
        "show_gridded": not settings.IS_HOSTED,
    }


@require_safe
def index(request):
    """The help home: search, the guides, sample data, the list of topics and the tour."""
    context = {"guides": all_guides(), **sample_data()}
    return render(request, "help/index.html", context)


@require_safe
def guide(request, slug):
    page = get_guide(slug)
    if page is None:
        raise Http404
    position = GUIDE_ORDER.index(slug)
    previous = get_guide(GUIDE_ORDER[position - 1]) if position > 0 else None
    following = get_guide(GUIDE_ORDER[position + 1]) if position + 1 < len(GUIDE_ORDER) else None
    context = {"guide": page, "previous": previous, "next": following, "guides": all_guides()}
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
    return render(request, "help/topics.html", {"groups": ordered})


def _sort_key(topic):
    return str(topic.title).casefold()


@require_safe
def search_view(request):
    query = request.GET.get("q", "").strip()[:200]
    results = search(query) if query else []
    context = {"query": query, "results": results}
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
    return render(request, "help/section.html", context)

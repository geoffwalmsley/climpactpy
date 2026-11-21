"""In-app help (#81): guide pages, contextual help topics, section help in the drawer
(#177), the index catalogue, search, translations with English fallback, and the
first-run tour."""

import re
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

import made
import pytest
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import RequestFactory, override_settings
from django.utils.html import escape

import climpact_web
from climpact_web.help import contents, guides, sections, topics
from climpact_web.help.guides import GUIDE_ORDER, get_guide
from climpact_web.help.topics import UnknownTopic, get_topic
from climpact_web.stations import forms as station_forms

PACKAGE = Path(climpact_web.__file__).parent
TEMPLATES = sorted(PACKAGE.rglob("templates/**/*.html"))

pytestmark = pytest.mark.django_db

REFERENCE_FORMATS = ("station-file", "batch-metadata", "gridded-inputs", "sector-data")


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = settings.MEDIA_ROOT / "runs"


# ---- Guides ------------------------------------------------------------------------------


def test_every_guide_renders_with_a_table_of_contents(client):
    for slug in GUIDE_ORDER:
        response = client.get(get_guide(slug).url)
        assert response.status_code == 200, slug
        html = response.content.decode()
        guide = get_guide(slug)
        assert guide.title and guide.summary, slug
        assert f"<h1>{guide.title}</h1>" in html
        assert 'class="help-toc help-toc--rail"' in html and guide.toc, slug
        assert "guide:" not in guide.html and "url:" not in guide.html  # links resolved


def test_unknown_guide_is_404(client):
    assert client.get("/help/no-such-guide/").status_code == 404


def test_batch_guide_describes_add_stations_and_the_overview(client):
    """The batch guide follows a batch through Add stations' review and the workspace's
    overview (#337), not the batch check and results pages that went with #271 and #311."""
    html = client.get("/help/batch/").content.decode()
    for anchor in ("the-metadata-file", "the-review-table", "options", "cancel", "files"):
        assert f'id="{anchor}"' in html, anchor
    assert 'href="/help/#samples-title"' in html and 'href="/add/"' in html
    text = re.sub(r"\s+", " ", html)
    assert "The run was cancelled." in text and "Not run" in text
    for stale in ("left out", "the results say why", "each station's zip", "Open as a single"):
        assert stale not in text, stale
    base = re.sub(r"\s+", " ", client.get("/help/base-period/").content.decode())
    assert "the batch page" not in base and "under a year in the base period" in base


def test_guides_have_previous_and_next_links(client):
    html = client.get("/help/base-period/").content.decode()
    assert 'href="/help/station-file/" rel="prev"' in html
    assert 'href="/help/quality-control/" rel="next"' in html


def test_station_guides_describe_add_stations_and_the_workspace(client):
    """The station file and sector guides follow a station through Add stations, its tabs
    and Your inputs (#342), not the single-station steps that went with #179, #198 and
    #233; the anchors help topics and other guides link to are kept."""
    html = client.get("/help/station-file/").content.decode()
    for anchor in (
        "missing-values",
        "common-problems",
        "station-details",
        "adding-a-station",
        "the-stations-pages",
        "changing-the-file-or-the-details",
    ):
        assert f'id="{anchor}"' in html, anchor
    assert 'href="/add/"' in html and 'href="/help/#samples-title"' in html
    assert 'href="/help/batch/#following-the-calculation"' in html
    text = re.sub(r"\s+", " ", html)
    for words in ("Add 1 station and check it", "Use the sample station", "Your inputs"):
        assert words in text, words
    sector = client.get("/help/sector/").content.decode()
    for anchor in ("the-sector-file", "settings", "detrending", "reading-the-results"):
        assert f'id="{anchor}"' in sector, anchor
    sector_text = re.sub(r"\s+", " ", sector)
    assert "Compare with sector data" in sector_text and "Calculate correlations" in sector_text
    for slug in ("station-file", "sector", "faq", "indices"):
        guide = re.sub(r"\s+", " ", get_guide(slug).html)
        for stale in ("step", "Adjust and recalculate", "the link from the results"):
            assert stale not in guide, (slug, stale)


def test_help_index_lists_guides_and_sample_data(client):
    """#325, the Help board: the search, the Reference cards, the guides as a numbered
    list in their order, common questions and the sample data as a short list."""
    html = client.get("/help/").content.decode()
    main = html[html.index('<div class="help-home">') :]
    guides = re.findall(r'<span><a href="(/help/[^/]+/)">', main)
    assert guides == [get_guide(s).url for s in GUIDE_ORDER if s not in ("faq", "accessibility")]
    assert 'class="help-guide-list__number" aria-hidden="true">1</span>' in main
    # The Reference cards lead to the Reference pages (#319).
    cards = re.findall(r'<h3 class="card__title help-card__title"><a href="([^"]+)">([^<]+)', main)
    assert cards == [
        ("/help/indices/", "Index reference"),
        ("/help/command-line/", "Command line"),
        ("/help/formats/", "File formats"),
    ]
    assert "All 55 ET-SCI indices" in main
    for anchor in ("file-refused", "years-missing", "percentile-missing", "same-as-r", "data-kept"):
        assert f'href="/help/faq/#{anchor}"' in main
    assert ">All questions</a>" in main
    assert 'action="/add/sample"' in main and 'action="/add/sample-batch"' in main  # #233
    assert "/station/sample.txt" in main and "/batch/sample-metadata.txt" in main
    assert "/station/sample-sector.csv" in main
    assert 'action="/gridded/sample"' in main  # local mode
    assert 'href="/?tour=1"' in main
    # The search keeps its live results.
    assert 'hx-get="/help/search/"' in main and 'id="help-results"' in main
    assert 'class="help-search--large"' in main


@override_settings(IS_HOSTED=True, GRIDDED_ENABLED=False)
def test_hosted_help_index_has_no_gridded_sample(client):
    assert "/gridded/sample" not in client.get("/help/").content.decode()


def _contents(html):
    """The help contents' column (the rail; the disclosure repeats it)."""
    return re.search(r'<nav class="help-contents help-contents--rail".*?</nav>', html, re.S)[0]


@pytest.mark.parametrize(
    "url",
    ["/help/", "/help/trends/", "/help/topics/", "/help/search/?q=base", "/help/faq/",
     "/help/sections/load.details/"],
)  # fmt: skip
def test_every_help_page_has_the_help_contents(client, url):
    """#325: every help page has the help's contents, as a column and as a disclosure for
    narrow screens, plain links in three groups, without JavaScript."""
    html = client.get(url).content.decode()
    nav = _contents(html)
    assert 'aria-label="Help contents"' in nav
    assert 'action="/help/search/"' in nav and 'name="q"' in nav and "Search help" in nav
    assert '<a class="help-contents__link" href="/help/"' in nav
    labels = re.findall(r'<p class="group-label help-contents__label"[^>]*>([^<]+)</p>', nav)
    assert labels == ["Guides", "Reference", "More"]
    links = re.findall(r'href="(/help/[^"]*)"', nav)
    guides = [get_guide(s).url for s in GUIDE_ORDER if s not in ("faq", "accessibility")]
    formats = [f"/help/formats/{f}/" for f in REFERENCE_FORMATS]
    reference = ["/help/indices/", "/help/command-line/", "/help/formats/", *formats]
    assert links == [
        "/help/",
        *guides,
        *reference,
        "/help/faq/",
        "/help/topics/",
        "/help/accessibility/",
    ]
    assert '<details class="disclosure help-contents-disclosure">' in html
    assert "<summary><span>Help contents</span>" in html
    # The page's text and its h1 are in the frame; headings don't skip levels.
    assert html.count("<h1") == 1


@pytest.mark.parametrize(
    ("url", "current"),
    [("/help/", "/help/"), ("/help/trends/", "/help/trends/"),
     ("/help/topics/", "/help/topics/"), ("/help/accessibility/", "/help/accessibility/"),
     ("/help/search/?q=base", None)],
)  # fmt: skip
def test_the_current_help_page_is_marked_in_the_contents(client, url, current):
    nav = _contents(client.get(url).content.decode())
    marked = re.findall(r'href="([^"]+)" aria-current="page"', nav)
    assert marked == ([current] if current else [])


def test_reference_pages_join_the_contents_once_they_exist():
    """#319 adds the Reference pages: each joins the contents and the home's cards by its
    URL name alone, the index reference current on the pages under it too."""
    urls = {
        ("help:index_reference",): "/help/indices/",
        ("help:command_line",): "/help/command-line/",
        ("help:formats",): "/help/formats/",
        ("help:format", "station-file"): "/help/formats/station-file/",
    }
    with mock.patch.object(contents, "url_or_none", lambda name, *a: urls.get((name, *a))):
        found = contents.contents("/help/indices/tx90p/")
        reference = next(g for g in found["groups"] if g["key"] == "reference")
        assert [link["url"] for link in reference["links"]] == [
            "/help/indices/",
            "/help/command-line/",
            "/help/formats/",
        ]
        assert reference["links"][0]["current"]
        assert [c["url"] for c in reference["links"][2]["children"]] == [
            "/help/formats/station-file/"
        ]
        cards = contents.reference_cards()
        assert [c["url"] for c in cards] == [
            "/help/indices/",
            "/help/command-line/",
            "/help/formats/",
        ]


def test_on_this_page_and_the_call_to_action(client):
    """#325: On this page beside the text (a column) and above it on narrow screens (a
    disclosure), with js/help-toc.js; a page's call to action under it (#319's pages)."""
    html = client.get("/help/quality-control/").content.decode()
    assert '<nav class="help-toc help-toc--rail" aria-labelledby="help-toc-title-rail"' in html
    assert 'id="help-toc-title-rail">On this page</p>' in html  # a label, not a heading
    assert '<details class="disclosure help-toc-disclosure">' in html
    assert 'href="#outliers"' in html and "js/help-toc" in html
    page = html.index('class="help-frame__page"')
    assert page < html.index("help-toc-disclosure") < html.index('class="help-article"')
    assert html.index('class="help-article"') < html.index('class="help-frame__aside"')
    # The topics A to Z list their groups there; search has nothing to list.
    topics = client.get("/help/topics/").content.decode()
    assert 'href="#group-' in topics and "help-toc--rail" in topics
    search = client.get("/help/search/?q=base").content.decode()
    assert "help-toc" not in search and "js/help-toc" not in search
    request = RequestFactory().get("/help/trends/")
    action = {"title": "Calculate it", "text": "For your stations.", "label": "Get started",
              "url": "/add/"}  # fmt: skip
    framed = render_to_string("help/frame.html", {"help_action": action}, request=request)
    assert framed.count('<div class="help-action">') == 2  # beside, and above on narrow
    assert '<a href="/add/">Get started</a>' in framed


def test_header_help_button_opens_the_pages_guide(client):
    """#197: Help at the end of the header leads to the guide of the page shown, or to the
    help's index; not a link among the destinations. A quiet link since #227, after Index
    reference, which leads to every index's definition."""
    html = client.get("/").content.decode()
    nav = re.findall(r'<nav class="site-nav".*?</nav>', html, re.S)[0]
    assert "/help/" not in nav
    button = re.search(r'<a class="site-header__link" id="app-help"[^>]*>.*?</a>', html, re.S)
    assert 'href="/help/" aria-label="Help"' in button.group(0)
    assert ">Help</a>" in button.group(0)
    reference = re.search(r'<a class="site-header__link[^"]*" href="([^"]+)">Index reference', html)
    assert reference.group(1) == "/help/indices/"
    html = client.get("/help/trends/").content.decode()
    assert re.search(r'id="app-help" href="/help/" aria-label="Help" aria-current="page"', html)
    # On /help/indices/ Index reference is current instead (#325), and on each index's page.
    html = client.get("/help/indices/").content.decode()
    assert re.search(r'href="/help/indices/" aria-current="page">Index reference', html)
    assert not re.search(r'id="app-help"[^>]*aria-current', html)
    html = client.get("/help/indices/tx90p/").content.decode()
    assert re.search(r'href="/help/indices/" aria-current="true">Index reference', html)
    assert not re.search(r'id="app-help"[^>]*aria-current', html)
    for url, guide in [("/add/", "station-file"), ("/jobs/", "batch")][:1]:
        html = client.get(url).content.decode()
        assert re.search(rf'id="app-help" href="/help/{guide}/" aria-label="Help: [^"]+"', html)


def test_links_to_pages_that_do_not_exist_keep_their_text(settings):
    body = guides.resolve_links(
        '<p><a href="url:stations:indices">the indices step</a> and '
        '<a href="guide:trends#sens-slope">trends</a> and <a href="guide:#x">here</a> and '
        '<a href="url:help:index#samples-title">samples</a></p>',
        "faq",
    )
    assert "<p>the indices step and " in body  # #78 adds that URL
    assert 'href="/help/trends/#sens-slope"' in body and 'href="/help/faq/#x"' in body
    assert 'href="/help/#samples-title"' in body  # a page of the app, at an anchor (#337)


# ---- No broken links ---------------------------------------------------------------------


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs, self.ids = [], set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("href"):
            self.hrefs.append(attrs["href"])


def parse(html):
    parser = Links()
    parser.feed(html)
    return parser


def pages_with_help(client):
    """Every help page, and the screens that show help topics."""
    urls = ["/", "/help/", "/help/topics/", "/help/search/?q=base"]
    urls += [f"/help/{slug}/" for slug in GUIDE_ORDER]
    urls += ["/add/"]
    load = made.station_to_set_up(client, sample=True).url("setup")  # a station's own setup page
    review = client.post("/add/sample-batch")["Location"]  # Add stations' review (#233)
    return [*urls, load, review]


def test_no_link_to_a_help_topic_or_guide_is_broken(client):
    """Every link on the help pages and the screens with help resolves, and every
    #anchor exists on its page."""
    cache = {}

    def page(path):
        if path not in cache:
            response = client.get(path)
            cache[path] = (response.status_code, parse(response.content.decode()).ids)
        return cache[path]

    checked = 0
    for url in pages_with_help(client):
        response = client.get(url)
        assert response.status_code == 200, url
        parsed = parse(response.content.decode())
        for href in parsed.hrefs:
            split = urlsplit(href)
            if split.scheme or href.startswith("//"):
                continue  # external links
            path = split.path or urlsplit(url).path
            if not path.startswith("/help/") and not split.fragment:
                continue  # other app pages are tested by their own apps
            status, ids = (200, parsed.ids) if path == urlsplit(url).path else page(path)
            assert status == 200, f"{url}: {href}"
            if split.fragment:
                assert split.fragment in ids, f"{url}: {href} has no #{split.fragment}"
            checked += 1
    assert checked > 300


def test_every_topic_points_at_an_existing_guide_section():
    for topic in topics.topics().values():
        assert topic.guide in GUIDE_ORDER, topic.id
        guide = get_guide(topic.guide)
        if topic.anchor:
            assert topic.anchor in guide.anchors, f"{topic.id}: #{topic.anchor}"


def test_every_topic_used_in_a_template_exists():
    used = set()
    for template in TEMPLATES:
        source = template.read_text()
        used |= set(re.findall(r'{%\s*help_topic\s+"([^"]+)"', source))
    assert used, "no help topics used"
    assert used <= topics.topic_ids(), used - topics.topic_ids()


def test_every_section_used_in_a_template_exists_and_its_topics_too():
    used = set()
    for template in TEMPLATES:
        source = template.read_text()
        used |= set(re.findall(r'{%\s*section_help\s+"([^"]+)"', source))
        # A field no longer takes a help topic of its own (#177).
        assert not re.search(r'components/field\.html"[^%]*\bhelp=', source), template.name
    assert used == sections.section_ids(), used ^ sections.section_ids()
    for section in sections.SECTIONS:
        assert section.topics or section.notes, section.id
        assert set(section.topics) <= topics.topic_ids(), section.id


# ---- Contextual help ---------------------------------------------------------------------


def render_topic(source):
    return Template("{% load help %}" + source).render(Context({}))


def test_help_topic_opens_in_place_with_a_guide_link():
    html = render_topic('{% help_topic "station.base_period" %}')
    assert '<details class="disclosure help-topic help-topic--compact"' in html
    assert 'data-help-topic="station.base_period"' in html
    assert "What is the base period?" in html and "percentile thresholds" in html
    assert 'href="/help/base-period/"' in html and "More in the guide: Choosing a base" in html
    block = render_topic('{% help_topic "qc.outliers" summary="Why?" variant="block" %}')
    assert "help-topic--compact" not in block and "<span>Why?</span>" in block
    assert 'href="/help/quality-control/#outliers"' in block


def test_help_links_under_a_heading_ask_a_question():
    """#115: a link that would repeat or contradict the heading it sits under asks a
    question instead; the list of topics keeps the topic's name."""
    html = render_topic('{% help_topic "qc.toolarge" %}')
    assert "<span>What counts as too large?</span>" in html
    assert "Values too large" not in html
    assert str(get_topic("qc.toolarge").title) == "Values too large"
    assert str(get_topic("qc.tmaxmin").title) == "Minimum at or above maximum"
    html = render_topic('{% help_topic "station.latitude" %}')  # a question already
    assert "<span>Why the latitude matters</span>" in html


def test_index_topics_come_from_the_core_definitions():
    topic = get_topic("index.txx")
    # Codes first (#218); R's long name follows the definition.
    assert str(topic.title) == "TXx Hottest day"
    assert str(topic.text) == "Annual warmest daily TX. Units: °C. Name in Climpact for R: Max TX."
    assert str(get_topic("index.fd").text) == "Annual number of days when TN < 0 °C. Units: days."
    assert topic.url == "/help/about-the-indices/#index-txx"
    html = render_topic('{% help_topic "index.tx90p" %}')
    assert "Annual percentage of days when TX &gt; 90th percentile. Units: % of days." in html


def test_unknown_topic_fails_in_tests_and_is_hidden_in_production(settings, caplog):
    with pytest.raises(UnknownTopic):
        render_topic('{% help_topic "no.such" %}')
    settings.HELP_STRICT = False
    settings.DEBUG = False
    assert render_topic('{% help_topic "no.such" %}').strip() == ""
    assert "unknown help topic 'no.such'" in caplog.text


def test_field_component_has_no_help_link_of_its_own():
    """#177: a field has its label, a short hint and its errors; its section's ⓘ has the
    help."""
    form = station_forms.MetadataForm()
    html = Template('{% include "components/field.html" with field=form.latitude %}').render(
        Context({"form": form})
    )
    assert "help-topic" not in html and "help-button" not in html
    assert 'id="id_latitude_helptext"' in html and "Negative south of the equator." in html


def test_section_help_is_a_link_and_a_button_for_the_drawer():
    """#177: the Help button is a link to the section's help page, for browsers without
    JavaScript, and a hidden button that drawer.js shows, which opens the drawer with the
    help in the <template> beside it. Both show the word Help (#197) and are named
    "Help: <section>"."""
    html = render_topic('{% section_help "load.details" %}')
    link = re.search(
        r'<a class="help-button" href="([^"]+)" data-help-link[^>]*>.*?</a>', html, re.S
    )
    assert link.group(1) == "/help/sections/load.details/"
    assert 'aria-label="Help: Station details"' in link.group(0)
    assert "<span>Help</span>" in link.group(0)
    button = re.search(r'<button type="button" class="help-button"[^>]*>', html).group(0)
    assert 'data-drawer-open="help-load-details"' in button
    assert 'aria-controls="help-drawer"' in button and 'aria-expanded="false"' in button
    assert " hidden" in button
    template = re.search(r'<template id="help-load-details"[^>]*>(.*)</template>', html, re.S)
    assert 'data-title="Help: Station details"' in template.group(0)
    body = template.group(1)
    for topic_id in ("station.name", "station.latitude", "station.longitude"):
        assert f'data-help-topic="{topic_id}"' in body
    assert 'data-help-topic="station.base_period"' in body
    assert "These details change the results." in body
    # One link per guide the topics point to, to the first topic's section in it.
    assert 'href="/help/station-file/#station-details"' in body
    assert 'href="/help/base-period/"' in body
    assert body.count("More in the guide:") == 2


def test_section_help_with_the_screens_own_topics():
    html = render_topic('{% section_help "result.index" topics="index.txx" title="TXx" %}')
    assert 'href="/help/sections/result.index/?topics=index.txx"' in html
    assert 'aria-label="Help: TXx"' in html
    first, then = 'data-help-topic="index.txx"', 'data-help-topic="trend.sen_slope"'
    assert html.index(first) < html.index(then)
    assert 'id="help-result-index-index-txx"' in html


def test_unknown_section_fails_in_tests_and_is_hidden_in_production(settings, caplog):
    with pytest.raises(sections.UnknownSection):
        render_topic('{% section_help "no.such" %}')
    with pytest.raises(UnknownTopic):
        render_topic('{% section_help "load.details" topics="no.such" %}')
    settings.HELP_STRICT = False
    settings.DEBUG = False
    assert render_topic('{% section_help "no.such" %}').strip() == ""
    assert "unknown help section 'no.such'" in caplog.text


@pytest.mark.parametrize("section", sections.SECTIONS, ids=lambda s: s.id)
def test_every_section_has_a_help_page(client, section):
    """Where the ⓘ leads without JavaScript: the same help on a page of its own."""
    html = client.get(section.url).content.decode()
    assert f"<h1>{escape(section.title)}</h1>" in html
    for topic_id in section.topics:
        assert f'data-help-topic="{topic_id}"' in html


def test_section_help_page_with_topics_and_unknown_ones(client):
    html = client.get("/help/sections/result.index/?topics=index.txx").content.decode()
    assert "<h1>TXx Hottest day</h1>" in html and 'data-help-topic="index.txx"' in html
    assert client.get("/help/sections/no.such/").status_code == 404
    assert client.get("/help/sections/result.index/?topics=no.such").status_code == 404


def test_every_page_has_one_hidden_drawer(client):
    html = client.get("/").content.decode()
    assert html.count('id="help-drawer"') == 1
    drawer = re.search(r'<aside class="drawer[^"]*" id="help-drawer"[^>]*>', html).group(0)
    assert "hidden" in drawer and 'aria-labelledby="help-drawer-title"' in drawer
    assert "<dialog" not in drawer  # not modal
    assert html.index("</main>") < html.index('id="help-drawer"') < html.index("<footer")
    assert "js/drawer.js" in html


def test_quality_verdict_help_states_the_verdict_limits():
    """The limits in the verdict's help are those of qc_review.VERDICT_LIMITS."""
    from climpact_web.stations.qc_review import VERDICT_LIMITS

    text = " ".join(str(n.text) for n in sections.get_section("quality.verdict").notes)
    assert f"{VERDICT_LIMITS.wrong_share:.1%}" in text
    assert f"more than {VERDICT_LIMITS.short_years_share:.0%} of the years" in text


def test_add_stations_and_the_setup_page_show_their_help(client):
    # Add stations (#233) links the formats; the header's Help opens the station file guide.
    html = client.get("/add/").content.decode()
    assert 'href="/help/station-file/"' in html
    review = client.get(client.post("/add/sample-batch")["Location"]).content.decode()
    assert 'href="/help/batch/#the-metadata-file"' in review
    # A station's own setup page (a new file that needs new details) keeps its help.
    load = client.get(made.station_to_set_up(client, sample=True).url("setup")).content.decode()
    assert re.findall(r'href="/help/sections/([^/]+)/"', load) == ["upload.file", "load.details"]
    for topic_id in ("station.name", "station.latitude", "station.longitude"):
        assert f'data-help-topic="{topic_id}"' in load
    assert 'data-help-topic="station.base_period"' in load
    assert "help-topic--compact" not in load  # no help link under a field
    js = (PACKAGE / "core" / "static" / "climpact_web" / "js" / "tour.js").read_text()
    assert '"climpact-tour"' in js and "localStorage" in js
    assert "Escape" in js and 'aria-modal", "false"' in js


def test_accessibility_statement_is_linked_from_every_footer(client):
    """The accessibility statement (#83) is a guide, linked from the page shell's footer."""
    for url in ("/", "/add/", "/help/", "/no-such-page/"):
        html = client.get(url).content.decode()
        assert 'href="/help/accessibility/"' in html, url
    html = client.get("/help/accessibility/").content.decode()
    for text in ("WCAG 2.1", "partially conforms", "Known limitations", "Reporting a problem"):
        assert text in html

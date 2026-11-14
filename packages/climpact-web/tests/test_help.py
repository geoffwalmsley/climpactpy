"""In-app help (#81): guide pages, contextual help topics, the index catalogue, search,
translations with English fallback, and the first-run tour."""

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from django.template import Context, Template
from django.test import override_settings
from django.utils import translation

import climpact_web
from climpact_web.batch import forms as batch_forms
from climpact_web.help import guides, indices, topics
from climpact_web.help.guides import GUIDE_ORDER, get_guide, search
from climpact_web.help.topics import UnknownTopic, get_topic, index_topic_for_output
from climpact_web.stations import forms as station_forms

PACKAGE = Path(climpact_web.__file__).parent
TEMPLATES = sorted(PACKAGE.rglob("templates/**/*.html"))

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = settings.MEDIA_ROOT / "runs"


# ---- Guides ------------------------------------------------------------------------------


def test_every_guide_renders_with_a_table_of_contents(client):
    for slug in GUIDE_ORDER:
        response = client.get(f"/help/{slug}/")
        assert response.status_code == 200, slug
        html = response.content.decode()
        guide = get_guide(slug)
        assert guide.title and guide.summary, slug
        assert f"<h1>{guide.title}</h1>" in html
        assert 'class="help-toc"' in html and guide.toc, slug
        assert "guide:" not in guide.html and "url:" not in guide.html  # links resolved


def test_unknown_guide_is_404(client):
    assert client.get("/help/no-such-guide/").status_code == 404


def test_guides_have_previous_and_next_links(client):
    html = client.get("/help/base-period/").content.decode()
    assert 'href="/help/station-file/" rel="prev"' in html
    assert 'href="/help/quality-control/" rel="next"' in html


def test_help_index_lists_guides_and_sample_data(client):
    html = client.get("/help/").content.decode()
    for slug in GUIDE_ORDER:
        assert f'href="/help/{slug}/"' in html
    assert 'action="/station/sample"' in html and 'action="/batch/sample"' in html
    assert "/station/sample.txt" in html and "/batch/sample-metadata.txt" in html
    assert "climpact.sampledata.gridded.1991-2010.nc" in html  # local mode
    assert 'href="/?tour=1"' in html and 'href="/help/topics/"' in html


@override_settings(IS_HOSTED=True)
def test_hosted_help_index_has_no_gridded_sample(client):
    assert "climpact.sampledata.gridded" not in client.get("/help/").content.decode()


def test_header_links_to_help(client):
    html = client.get("/").content.decode()
    nav = re.findall(r'<nav class="site-nav".*?</nav>', html, re.S)[0]
    assert 'href="/help/" data-nav="help"' in nav
    assert 'aria-current="page"' in client.get("/help/trends/").content.decode()


def test_links_to_pages_that_do_not_exist_keep_their_text(settings):
    body = guides.resolve_links(
        '<p><a href="url:gridded:start">the gridded screen</a> and '
        '<a href="guide:trends#sens-slope">trends</a> and <a href="guide:#x">here</a></p>',
        "faq",
    )
    assert "<p>the gridded screen and " in body
    assert 'href="/help/trends/#sens-slope"' in body and 'href="/help/faq/#x"' in body


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
    urls += ["/station/", "/batch/"]
    load = client.post("/station/sample")["Location"]
    check = client.post("/batch/sample")["Location"]
    return [*urls, load, check]


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
        used |= set(re.findall(r'\bhelp="([^"]+)"', source))
    assert used, "no help topics used"
    assert used <= topics.topic_ids(), used - topics.topic_ids()


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


def test_index_topics_come_from_the_core_definitions():
    topic = get_topic("index.txx")
    assert str(topic.title) == "TXx: Max TX"
    assert str(topic.text) == "Annual warmest daily TX. Units: °C."
    assert topic.url == "/help/indices/#index-txx"
    html = render_topic('{% help_topic "index.tx90p" %}')
    assert "Annual percentage of days when TX &gt; 90th percentile. Units: % of days." in html


def test_unknown_topic_fails_in_tests_and_is_hidden_in_production(settings, caplog):
    with pytest.raises(UnknownTopic):
        render_topic('{% help_topic "no.such" %}')
    settings.HELP_STRICT = False
    settings.DEBUG = False
    assert render_topic('{% help_topic "no.such" %}').strip() == ""
    assert "unknown help topic 'no.such'" in caplog.text


def test_field_component_shows_a_help_topic():
    form = station_forms.MetadataForm()
    html = Template(
        '{% include "components/field.html" with field=form.latitude help="station.latitude" %}'
    ).render(Context({"form": form}))
    assert 'data-help-topic="station.latitude"' in html


def test_step_1_and_batch_screens_show_their_help(client):
    html = client.get("/station/").content.decode()
    assert 'data-help-topic="station.file"' in html
    assert 'href="/help/station-file/"' in html
    load = client.get(client.post("/station/sample")["Location"]).content.decode()
    for topic_id in ("station.name", "station.latitude", "station.longitude"):
        assert f'data-help-topic="{topic_id}"' in load
    assert 'data-help-topic="station.base_period"' in load
    html = client.get("/batch/").content.decode()
    assert 'data-help-topic="batch.metadata_file"' in html
    assert 'data-help-topic="batch.station_files"' in html
    check = client.get(client.post("/batch/sample")["Location"]).content.decode()
    for topic_id in ("batch.base_period", "batch.workers", "batch.plots", "batch.metadata_file"):
        assert f'data-help-topic="{topic_id}"' in check


# The base period's two year fields share the fieldset's hint and help topic.
FIELDSET_COVERED = {"base_start", "base_end"}


@pytest.mark.parametrize(
    "form_class",
    [
        station_forms.UploadForm,
        station_forms.MetadataForm,
        station_forms.RunAllForm,
        batch_forms.UploadForm,
        batch_forms.AddFilesForm,
        batch_forms.OptionsForm,
    ],
    ids=lambda c: f"{c.__module__.split('.')[1]}.{c.__name__}",
)
def test_every_form_field_has_help_text(form_class):
    for name, field in form_class().fields.items():
        assert field.help_text or name in FIELDSET_COVERED, f"{form_class.__name__}.{name}"


# ---- The index catalogue -----------------------------------------------------------------


def test_catalogue_covers_every_index_of_the_core_file():
    shorts = [info.short for info in indices.catalogue()]
    rows = {row["Short.name"] for row in indices._rows()}
    assert set(shorts) == rows and len(shorts) == len(rows)
    grouped = [short for _key, _label, members in indices.GROUPS for short in members]
    assert sorted(grouped) == sorted(shorts)  # each in exactly one group
    assert set(indices.DISPLAY_NAMES) == rows
    for info in indices.catalogue():
        assert info.units in indices.UNITS, info.short
        assert "degrees_C" not in info.definition + info.long_name


def test_catalogue_entries_read_well():
    by = indices.by_short()
    assert by["fd"].long_name == "Frost days" and by["fd"].annual and by["fd"].monthly
    assert by["tx90p"].base_period and not by["fd"].base_period
    assert by["gsl"].annual and not by["gsl"].monthly
    assert by["spi"].monthly and not by["spi"].annual
    assert by["hwEHF"].long_name == "Heatwaves as per Nairn and Fawcett"
    assert by["txdtnd"].param_topic == "param.txtn_days"


def test_indices_guide_has_an_entry_for_every_index(client):
    html = client.get("/help/indices/").content.decode()
    ids = parse(html).ids
    for info in indices.catalogue():
        assert info.anchor in ids, info.short
    assert '<h4 id="index-rxdday">Rxdday: User-defined consecutive days PR amount</h4>' in html
    assert "You choose <em>d</em> on the indices step." in html
    assert "You choose <em>nn</em> on the indices step." in html


@pytest.mark.parametrize(
    "name, topic_id",
    [
        ("txx", "index.txx"),
        ("txx_MON", "index.txx"),
        ("rx1day_ANN", "index.rx1day"),
        ("rx3day_ANN", "index.rxdday"),
        ("r10mm", "index.r10mm"),
        ("r30mm_MON", "index.rnnmm"),
        ("wsdi", "index.wsdi"),
        ("wsdi3", "index.wsdid"),
        ("tx2tn2", "index.txdtnd"),
        ("txb2tnb2", "index.txbdtnbd"),
        ("hddheat18", "index.hddheatn"),
        ("gddgrow10_ANN", "index.gddgrown"),
        ("TX90-HWN_ANN", "index.hw"),
        ("EHF-HWPS_ANN", "index.hwEHF"),
        ("EHFdaily", "index.hwEHF"),
        ("3month_spi_MON", "index.spi"),
        ("24month_spei_MON", "index.spei"),
        ("tx95t_DAY", "index.tx95t"),
        ("TXge40_ANN", "param.custom"),
        ("TNlt-2.5", "param.custom"),
        ("nothing", None),
    ],
)
def test_index_topic_for_output_names(name, topic_id):
    assert index_topic_for_output(name) == topic_id


def test_index_messages_file_is_up_to_date():
    """Regenerate with ``python -m climpact_web.help.indices``."""
    assert indices.MESSAGES_FILE.read_text() == indices.messages_source()


# ---- Topic list and search ---------------------------------------------------------------


def test_topic_list_has_every_topic(client):
    html = client.get("/help/topics/").content.decode()
    ids = parse(html).ids
    for topic in topics.topics().values():
        assert topic.anchor_id in ids, topic.id
    assert "Quality checks" in html and "Indices" in html


def test_search_finds_guide_sections_and_topics(client):
    results = search("base period")
    assert "base period" in results[0].title.lower()  # title matches rank first
    urls = [r.url for r in results]
    assert any(u.startswith("/help/base-period/#") for u in urls)
    assert any(r.context == "Help topic" for r in results)
    assert search("") == [] and search("zzzz-nothing") == []
    assert any(r.url == "/help/indices/#index-tx90p" for r in search("tx90p"))
    html = client.get("/help/search/?q=outliers").content.decode()
    assert "<h1>" in html and 'href="/help/quality-control/#outliers"' in html
    partial = client.get("/help/search/?q=outliers", HTTP_HX_REQUEST="true").content.decode()
    assert "<h1>" not in partial and "results for “outliers”" in partial
    assert "Nothing found" in client.get("/help/search/?q=qwertyuiop").content.decode()


def test_search_is_live_with_htmx_and_works_without_it(client):
    html = client.get("/help/").content.decode()
    assert re.search(r'<form class="help-search" method="get" action="/help/search/"', html)
    assert 'hx-get="/help/search/"' in html and 'hx-target="#help-results"' in html


# ---- Translations ------------------------------------------------------------------------


def test_language_candidates():
    assert guides.language_candidates("pt-br") == ["pt-br", "pt", "en"]
    assert guides.language_candidates("en") == ["en"]
    assert guides.language_candidates(None) == ["en"]


@override_settings(LANGUAGES=[("en", "English"), ("fr", "French")])
def test_guides_fall_back_to_english_and_use_a_translation_when_present(
    client, tmp_path, monkeypatch
):
    html = client.get("/help/trends/", HTTP_ACCEPT_LANGUAGE="fr").content.decode()
    assert "This guide is not yet translated, so it is shown in English." in html
    assert 'lang="en"' in html  # the article is marked as English
    root = tmp_path / "guides"
    (root / "en").mkdir(parents=True)
    (root / "fr").mkdir()
    for slug in GUIDE_ORDER:
        (root / "en" / f"{slug}.md").write_text(
            (guides.GUIDES_DIR / "en" / f"{slug}.md").read_text()
        )
    (root / "fr" / "trends.md").write_text(
        "title: Tendances\nsummary: Résumé\n\n## Pente {#pente}\n"
    )
    monkeypatch.setattr(guides, "GUIDES_DIR", root)
    html = client.get("/help/trends/", HTTP_ACCEPT_LANGUAGE="fr").content.decode()
    assert "<h1>Tendances</h1>" in html and "not yet translated" not in html
    with translation.override("fr"):
        assert get_guide("trends").language == "fr"
        assert get_guide("faq").fallback


# ---- Tour --------------------------------------------------------------------------------


def test_home_page_offers_the_tour(client):
    html = client.get("/").content.decode()
    assert "/static/climpact_web/js/tour.js" in html
    assert re.search(r'<div class="alert alert--info tour-invite" hidden data-tour-invite>', html)
    steps = json.loads(
        re.search(
            r'<script id="tour-steps" type="application/json">(.*?)</script>', html, re.S
        ).group(1)
    )
    assert len(steps) == 5
    ids = parse(html).ids
    for step in steps:
        assert step["title"] and step["text"]
        target = step["target"]
        if target.startswith("#"):
            assert target[1:] in ids, target
        else:
            key = re.search(r"data-nav='(\w+)'", target).group(1)
            assert f'data-nav="{key}"' in html, target
    labels = re.search(r'<template id="tour-labels"[^>]*>', html).group(0)
    assert "{step}" in labels and "{total}" in labels


def test_tour_script_remembers_the_choice():
    js = (PACKAGE / "core" / "static" / "climpact_web" / "js" / "tour.js").read_text()
    assert '"climpact-tour"' in js and "localStorage" in js
    assert "Escape" in js and 'aria-modal", "false"' in js

"""The help as documentation (#319): the index reference (a page per index), the
command-line guide built from the ``climpact`` parser, the file-format pages, and what
search engines see (titles, descriptions, canonical links, sitemap and robots.txt)."""

import re
from html import unescape

import pytest
from django.test import override_settings

from climpact_web.help import command_line, reference
from climpact_web.help.guides import GUIDE_ORDER, get_guide, search
from climpact_web.help.indices import by_short, catalogue
from climpact_web.help.seo import help_urls
from climpact_web.stations.themes import THEMES

pytestmark = pytest.mark.django_db

FORMATS = ("station-file", "batch-metadata", "gridded-inputs", "sector-data")


def _head(html: str) -> str:
    return re.search(r"<head>(.*?)</head>", html, re.S).group(1)


# ---- The index reference ------------------------------------------------------------------


def test_every_index_has_a_page_built_from_the_catalogue(client):
    for info in catalogue():
        url = f"/help/indices/{info.short.lower()}/"
        response = client.get(url)
        assert response.status_code == 200, url
        html = unescape(response.content.decode())
        assert f'<span class="help-index-header__code">{info.name}</span>' in html, url
        head = _head(html)
        assert f"<title>{info.name} " in head and ": definition · Climpact</title>" in head
        # At a glance: the core's definition word for word, R's name, and the rest.
        assert f"<dd>{info.definition}</dd>" in html, url
        assert f"<dd>{info.long_name}</dd>" in html, url
        for heading in ("How it is calculated", "In the result files", "On the command line"):
            assert heading in html, (url, heading)
        assert 'href="/add/">Get started</a>' in html  # Calculate it


def test_every_index_has_a_lead_and_a_kind_in_the_notes():
    """The hand-written part of each page (guides/en/index-notes.md) covers every index of
    the core's file, and names no index that does not exist."""
    known = by_short()
    kinds, notes = reference._notes("en")
    assert set(notes) == set(known)
    for short, found in notes.items():
        assert found.lead.startswith("<p>") and len(reference.lead_text(known[short])) > 40, short
    assert set(reference.KIND_OF) == set(known)
    assert set(reference.KINDS) - {"heatwave"} <= set(kinds)


def test_an_index_page_names_its_setting_files_and_option():
    page = reference.page(by_short()["rxdday"])
    facts = dict(page["facts"])
    assert "--rx-days" in facts["Settings"] and "rx7day" in facts["Settings"]
    assert ("Station, yearly", "indices/<station>_rx3day_ANN.csv") in page["files"]
    assert ("Station, monthly", "indices/<station>_rx3day_MON.csv") in page["files"]
    assert page["command_line"][0]["text"] == "climpact run sydney.txt --out results --rx-days 7"
    assert "sydney_rx7day_ANN.csv" in page["command_line"][1]["text"]
    spi = reference.page(by_short()["spi"])
    assert spi["name"] == "Standardised precipitation index"  # R's long name
    assert "24month_spi" in spi["files"][0][1]
    assert "sydney_36month_spi_MON.csv" in spi["command_line"][1]["text"]
    assert spi["caveat"] and spi["previous"] is None and spi["next"]["code"] == "SPEI"
    # Related: the counterpart first, then the nearest neighbours.
    assert [r["code"] for r in reference.page(by_short()["tx90p"])["related"]][0] == "TX10p"


def test_other_spellings_and_output_names_redirect_to_the_index(client):
    for code, slug in [("TX90p", "tx90p"), ("wsdi3", "wsdid"), ("rx3day", "rxdday"),
                       ("24month_spi", "spi"), ("hwEHF", "hwehf"), ("r30mm", "rnnmm")]:  # fmt: skip
        response = client.get(f"/help/indices/{code}/")
        assert response.status_code == 301, code
        assert response["Location"] == f"/help/indices/{slug}/"
    assert client.get("/help/indices/rx5day/").status_code == 200  # an index of its own
    assert client.get("/help/indices/no-such-index/").status_code == 404


def test_the_index_list_groups_every_index_by_theme(client):
    html = client.get("/help/indices/").content.decode()
    links = re.findall(r'<th scope="row" class="help-indices__code"><a href="([^"]+)">', html)
    assert sorted(links) == sorted(f"/help/indices/{i.short.lower()}/" for i in catalogue())
    themes = re.findall(r'<section class="help-indices__theme[^"]*"[^>]*id="([a-z]+)"', html)
    assert themes == [t.key for t in THEMES if t.shorts]
    assert "Showing all 55" in html and 'href="/help/indices/climate.indices.csv"' in html
    # Find and the theme pills are a GET form; the script filters in place.
    assert 'method="get" action="/help/indices/"' in html and 'name="q"' in html
    assert 'name="theme" value="heat"' in html and "js/help-indices.js" in html


def test_the_index_list_filters_without_javascript(client):
    html = client.get("/help/indices/?theme=drought").content.decode()
    assert "Showing 3 of 55" in html
    assert re.search(r'id="heat" data-theme="heat" hidden', html)
    assert 'value="drought" class="theme-pill hue-drought" aria-pressed="true"' in html
    html = client.get("/help/indices/?q=warm+spell").content.decode()
    shown = re.findall(r'<tr data-search="[^"]*">\s*<th scope="row" class="help-indices__code">'
                       r'<a href="/help/indices/([a-z0-9]+)/"', html)  # fmt: skip
    assert shown == ["wsdi", "wsdid"]
    assert "No index matches" in html and "data-help-indices-none hidden" in html


def test_the_definitions_file_is_served(client):
    response = client.get("/help/indices/climate.indices.csv")
    assert response.status_code == 200
    assert response.content.decode().startswith("Short.name")


# ---- The command line ---------------------------------------------------------------------


def test_the_command_line_guide_covers_every_command_and_option(client):
    """A test that fails when the CLI gains or loses a command the guide does not cover:
    each command needs its own section (a marker in command-line.md), and every option
    of the parser appears in the page."""
    text = command_line.commands()
    source = (reference.GUIDES_DIR / "en" / "command-line.md").read_text()
    assert command_line.markers(source) == set(text)
    html = unescape(client.get("/help/command-line/").content.decode())
    for name in text:
        assert f'id="{name}"' in html, name
        for option in command_line.options(name):
            assert option in html, (name, option)
    assert "climpact run [options] --out OUT station_file" in html
    # Index settings link to their index pages.
    assert '<a href="/help/indices/wsdid/">WSDId</a>' in html
    # On this page lists the commands, not each option table.
    toc = re.search(r'<nav class="help-toc help-toc--rail".*?</nav>', html, re.S).group(0)
    assert 'href="#run"' in toc and 'href="#run-station"' not in toc


def test_option_text_comes_from_the_parser():
    option, default, text = next(
        command_line.describe(a)
        for a in command_line.commands()["run"]._actions
        if a.dest == "wsdi_days"
    )
    assert (option, default, text) == (
        "--wsdi-days DAYS",
        "1",
        "Days in a row for WSDId (wsdi<n>).",
    )
    out = next(a for a in command_line.commands()["run"]._actions if a.dest == "out")
    assert command_line.describe(out)[1] == "required"


# ---- File formats -------------------------------------------------------------------------


@pytest.mark.parametrize("slug", FORMATS)
def test_every_file_format_has_a_page(client, slug):
    html = client.get(f"/help/formats/{slug}/").content.decode()
    assert '<pre id="example">' in html
    assert 'href="#example"' in html and 'href="#other-formats"' in html
    assert html.count('class="card card--link help-card"') == len(FORMATS) - 1
    assert '<nav aria-label="Breadcrumb" class="breadcrumb text-sm">' in html
    assert 'href="/help/formats/">File formats</a>' in html


def test_the_formats_list_and_the_guides_link_to_them(client):
    html = client.get("/help/formats/").content.decode()
    for slug in FORMATS:
        assert f'href="/help/formats/{slug}/"' in html
    assert "guide:" not in get_guide("command-line").html


def test_the_guide_to_the_indices_moved(client):
    """The index reference took /help/indices/; the guide is at /help/about-the-indices/."""
    assert get_guide("indices").url == "/help/about-the-indices/"
    assert client.get("/help/about-the-indices/").status_code == 200
    assert client.get("/help/command-line/").status_code == 200
    # Reference pages are not guides: no address of their own under /help/<slug>/.
    assert client.get("/help/format-station-file/").status_code == 404


def test_search_finds_the_index_and_reference_pages():
    titles = {r.url: r.title for r in search("TX90p")}
    assert titles.get("/help/indices/tx90p/") == "TX90p Warm days"
    assert any(r.url == "/help/command-line/" for r in search("climpact batch"))
    assert any(
        r.url.startswith("/help/formats/station-file/") for r in search("station file format")
    )


# ---- Search engines -----------------------------------------------------------------------


@override_settings(IS_HOSTED=True, PUBLIC_URL="https://climpact.example.org")
def test_hosted_help_pages_have_a_title_description_and_canonical_link(client):
    titles = set()
    for url in help_urls():
        html = client.get(url).content.decode()
        head = _head(html)
        title = re.search(r"<title>(.*?)</title>", head, re.S).group(1)
        assert title not in titles, url
        titles.add(title)
        assert re.search(r'<meta name="description" content="[^"]{30,}">', head), url
        assert f'<link rel="canonical" href="https://climpact.example.org{url}">' in head, url
        assert 'name="robots"' not in head, url


@override_settings(IS_HOSTED=True, PUBLIC_URL="")
def test_hosted_filtered_and_search_pages_are_not_indexed(client):
    head = _head(client.get("/help/indices/?theme=heat").content.decode())
    assert '<meta name="robots" content="noindex">' in head
    assert '<link rel="canonical" href="http://testserver/help/indices/">' in head
    for url in ("/help/search/?q=base", "/help/sections/load.details/"):
        assert '<meta name="robots" content="noindex">' in _head(client.get(url).content.decode())


@override_settings(IS_HOSTED=True, PUBLIC_URL="https://climpact.example.org")
def test_hosted_sitemap_and_robots(client):
    response = client.get("/sitemap.xml")
    assert response.status_code == 200 and response["Content-Type"] == "application/xml"
    locs = re.findall(r"<loc>([^<]+)</loc>", response.content.decode())
    expected = {"/help/", "/help/indices/", "/help/indices/tx90p/", "/help/command-line/",
                "/help/formats/", "/help/formats/station-file/", "/help/topics/",
                "/help/about-the-indices/"}  # fmt: skip
    assert {f"https://climpact.example.org{u}" for u in expected} <= set(locs)
    assert len(locs) == len(set(locs)) == 1 + len(GUIDE_ORDER) + 1 + 55 + 1 + 1 + 4 + 1
    robots = client.get("/robots.txt").content.decode()
    assert "Allow: /help/" in robots
    for path in ("/station/", "/batch/", "/w/", "/jobs/", "/gridded/", "/help/search/"):
        assert f"Disallow: {path}\n" in robots
    assert "Sitemap: https://climpact.example.org/sitemap.xml" in robots


def test_local_mode_is_not_indexed(client):
    head = _head(client.get("/help/indices/tx90p/").content.decode())
    assert '<meta name="robots" content="noindex">' in head
    assert "canonical" not in head
    assert client.get("/sitemap.xml").status_code == 404
    assert client.get("/robots.txt").content.decode() == "User-agent: *\nDisallow: /\n"

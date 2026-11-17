"""Guide pages (#81): Markdown files rendered by Django, one folder per language.

``guides/<language>/<slug>.md`` starts with ``title:`` and ``summary:`` lines (the Markdown
``meta`` extension), then the text. A guide missing in the current language falls back to
English, and the page says so. Headings get ids from their text (``toc`` extension), which
are the anchors help topics link to; the page's table of contents lists the ``##`` and
``###`` headings.

Links between pages are written with two schemes the renderer resolves, so that guides do
not depend on where the app is mounted:

- ``guide:<slug>#<anchor>`` for another guide (``guide:#<anchor>`` for the same one);
- ``url:<url name>`` for a page of the app, e.g. ``url:stations:new``; a page that does
  not exist yet (gridded, #85) leaves the link text without a link.

The indices guide has a generated catalogue: the line ``[[index-catalogue]]`` is replaced
with Markdown built from the core's ``climate.indices.csv`` before rendering, so the
catalogue's entries are in the search and get anchors (``index-<short name>``).

The Markdown is the app's own text, never user input, so it is rendered as trusted HTML.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import markdown
from django.urls import NoReverseMatch, reverse
from django.utils.translation import get_language, gettext

from climpact_web.help.indices import GROUPS, INDEX_PARAMS, UNITS, catalogue

GUIDES_DIR = Path(__file__).with_name("guides")
DEFAULT_LANGUAGE = "en"

# The guides, in reading order.
GUIDE_ORDER = (
    "station-file",
    "base-period",
    "quality-control",
    "indices",
    "trends",
    "batch",
    "sector",
    "gridded",
    "faq",
    "accessibility",  # the accessibility statement (#83), linked from every page's footer
)

CATALOGUE_MARKER = "[[index-catalogue]]"


@dataclass
class Section:
    """A ``##`` or ``###`` section, for the search."""

    anchor: str
    title: str
    text: str


@dataclass
class Guide:
    slug: str
    language: str  # the language of the text shown
    fallback: bool  # True when shown in English because no translation exists
    title: str
    summary: str
    html: str
    toc: list[dict]  # [{"id", "name", "children": [...]}] for ## and ###
    anchors: set[str] = field(default_factory=set)
    sections: list[Section] = field(default_factory=list)

    @property
    def url(self) -> str:
        return reverse("help:guide", args=[self.slug])


def language_candidates(language: str | None) -> list[str]:
    """``pt-br`` -> ``["pt-br", "pt", "en"]``."""
    out = []
    if language:
        language = language.lower()
        out.append(language)
        if "-" in language:
            out.append(language.split("-", 1)[0])
    out.append(DEFAULT_LANGUAGE)
    return list(dict.fromkeys(out))


def guide_path(slug: str, language: str | None = None) -> tuple[Path, str] | None:
    if slug not in GUIDE_ORDER:
        return None
    for code in language_candidates(language):
        path = GUIDES_DIR / code / f"{slug}.md"
        if path.is_file():
            return path, code
    return None


def get_guide(slug: str, language: str | None = None) -> Guide | None:
    language = language or get_language() or DEFAULT_LANGUAGE
    found = guide_path(slug, language)
    if found is None:
        return None
    path, code = found
    guide = _render(slug, code, path.stat().st_mtime_ns, get_language() or DEFAULT_LANGUAGE)
    wanted = language_candidates(language)[0]
    guide.fallback = code != wanted and wanted.split("-")[0] != code
    return guide


def all_guides(language: str | None = None) -> list[Guide]:
    return [g for g in (get_guide(slug, language) for slug in GUIDE_ORDER) if g]


@lru_cache(maxsize=64)
def _render(slug: str, language: str, mtime: int, active_language: str) -> Guide:
    """Render once per file version, file language and interface language (the generated
    catalogue is in the interface language)."""
    path = GUIDES_DIR / language / f"{slug}.md"
    text = path.read_text(encoding="utf-8")
    if CATALOGUE_MARKER in text:
        text = text.replace(CATALOGUE_MARKER, catalogue_markdown())
    md = markdown.Markdown(
        extensions=["meta", "tables", "fenced_code", "attr_list", "def_list", "toc", "sane_lists"],
        extension_configs={"toc": {"toc_depth": "2-3", "permalink": False}},
        output_format="html",
    )
    body = md.convert(text)
    meta = {k: " ".join(v) for k, v in md.Meta.items()}
    body = resolve_links(body, slug)
    body = wrap_tables(body)
    anchors = set(re.findall(r'\bid="([^"]+)"', body))
    return Guide(
        slug=slug,
        language=language,
        fallback=False,
        title=meta.get("title", slug),
        summary=meta.get("summary", ""),
        html=body,
        toc=md.toc_tokens,
        anchors=anchors,
        sections=split_sections(body),
    )


_LINK = re.compile(r'href="(guide|url):([^"]*)"')


def resolve_links(body: str, slug: str) -> str:
    def replace(match: re.Match) -> str:
        scheme, target = match.group(1), html.unescape(match.group(2))
        if scheme == "guide":
            name, _, anchor = target.partition("#")
            url = reverse("help:guide", args=[name or slug])
            return f'href="{url}{"#" + anchor if anchor else ""}"'
        try:
            return f'href="{reverse(target)}"'
        except NoReverseMatch:
            return 'data-unavailable="true"'

    body = _LINK.sub(replace, body)
    # A link to a page that does not exist yet keeps its text, without the link.
    return re.sub(r'<a data-unavailable="true">(.*?)</a>', r"\1", body, flags=re.S)


def wrap_tables(body: str) -> str:
    """Wide tables scroll in their own focusable region, as the table component does. The
    region is named by the heading above the table (a focusable region needs a name, #83)."""
    out, last = [], 0
    heading = re.compile(r'<h[2-6] id="([^"]+)"')
    for match in re.finditer(r"<table>.*?</table>", body, flags=re.S):
        before = body[last : match.start()]
        out.append(before)
        ids = heading.findall(body, 0, match.start())
        named = f' aria-labelledby="{ids[-1]}"' if ids else ""
        table = match.group(0).replace("<table>", '<table class="table">', 1)
        out.append(f'<div class="table-wrap" tabindex="0" role="region"{named}>{table}</div>')
        last = match.end()
    out.append(body[last:])
    return "".join(out)


def split_sections(body: str) -> list[Section]:
    parts = re.split(r'(<h[23] id="[^"]+">.*?</h[23]>)', body, flags=re.S)
    sections = []
    for heading, content in zip(parts[1::2], parts[2::2], strict=False):
        anchor = re.search(r'id="([^"]+)"', heading).group(1)
        sections.append(Section(anchor, strip_tags(heading), strip_tags(content)))
    return sections


def strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))).strip()


# ---- The index catalogue ---------------------------------------------------------------


def catalogue_markdown() -> str:
    """The indices grouped as in :data:`GROUPS`, one ``####`` entry each (anchored
    ``index-<short>``), in the current language."""
    by_short = {info.short: info for info in catalogue()}
    lines = []
    for key, label, shorts in GROUPS:
        lines += [f"### {label} {{#{key}}}", ""]
        for short in shorts:
            info = by_short[short]
            from climpact_web.help.topics import r_name_sentence

            # Codes first (#218): "TXx Hottest day", then R's long name after the definition.
            name = info.short_name()
            lines += [f"#### {info.name} {name} {{#{info.anchor}}}", ""]
            lines += [gettext(info.definition) + "." + r_name_sentence(info.long_name, name), ""]
            facts = [gettext("Units: %(units)s") % {"units": UNITS.get(info.units, info.units)}]
            if info.annual and info.monthly:
                facts.append(gettext("yearly and monthly values"))
            elif info.monthly:
                facts.append(gettext("monthly values"))
            elif info.annual:
                facts.append(gettext("yearly values"))
            if info.base_period:
                facts.append(gettext("uses the base period"))
            line = "; ".join(str(f) for f in facts) + "."
            if short in INDEX_PARAMS:
                what = "*d*" if INDEX_PARAMS[short].endswith("_days") else "*n*"
                if short == "rnnmm":
                    what = "*nn*"
                elif short in ("spi", "spei"):
                    what = gettext("an extra time scale")
                choose = gettext("You choose %(what)s in the index settings, in Your inputs.")
                line += " " + choose % {"what": what}
            lines += [line, "{: .index-facts }", ""]
    return "\n".join(lines)


# ---- Search ------------------------------------------------------------------------------


@dataclass
class Result:
    title: str
    url: str
    excerpt: str
    context: str  # the guide's title, or "Help topic"
    score: int


def search(query: str, language: str | None = None, limit: int = 30) -> list[Result]:
    """Every guide section and help topic containing all the words of ``query`` (case and
    accents as typed are ignored only for case). Matches in titles rank first."""
    from climpact_web.help.topics import topics

    words = [w for w in re.split(r"\s+", query.lower().strip()) if w]
    if not words:
        return []
    results: list[Result] = []
    for guide in all_guides(language):
        for section in guide.sections:
            title, text = section.title.lower(), section.text.lower()
            if all(w in title or w in text for w in words):
                score = sum(3 if w in title else 1 for w in words)
                results.append(
                    Result(
                        title=section.title,
                        url=f"{guide.url}#{section.anchor}",
                        excerpt=excerpt(section.text, words),
                        context=guide.title,
                        score=score,
                    )
                )
    for topic in topics().values():
        title, text = str(topic.title), str(topic.text)
        if all(w in title.lower() or w in text.lower() for w in words):
            score = sum(3 if w in title.lower() else 1 for w in words)
            results.append(
                Result(title, topic.url, excerpt(text, words), gettext("Help topic"), score)
            )
    results.sort(key=lambda r: -r.score)
    return results[:limit]


def excerpt(text: str, words: list[str], width: int = 180) -> str:
    lower = text.lower()
    positions = [lower.find(w) for w in words if lower.find(w) >= 0]
    start = max(0, min(positions) - 60) if positions else 0
    snippet = text[start : start + width].strip()
    return ("… " if start else "") + snippet + (" …" if start + width < len(text) else "")

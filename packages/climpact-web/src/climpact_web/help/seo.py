"""The help as documentation for search engines (#319, the HelpFlow board).

Every help page has a unique title (its template's), a description (``page_meta``) and,
in hosted mode, a canonical link built from ``CLIMPACT_WEB_PUBLIC_URL`` (else the
request's origin). The help's search, its section pages (the drawer's) and a filtered
index list are ``noindex``, the filtered list with a canonical link to the plain one.
``/sitemap.xml`` lists every indexable help page and ``/robots.txt`` keeps crawlers out of
the workspaces, jobs, uploads and gridded runs.

Only the hosted site is indexed: local mode (``climpact-web`` on someone's computer) sends
``noindex`` on every page (``core.context_processors.site``), serves no sitemap and a
``robots.txt`` that disallows everything.
"""

from __future__ import annotations

from django.conf import settings
from django.http import Http404, HttpResponse
from django.urls import reverse
from django.utils.html import escape
from django.views.decorators.http import require_safe

# The private areas: workspaces and their stations and batches, jobs, uploads, gridded runs.
DISALLOWED = ("/station/", "/batch/", "/w/", "/jobs/", "/gridded/", "/help/search/")


def absolute(request, path: str) -> str:
    if settings.PUBLIC_URL:
        return settings.PUBLIC_URL + path
    return request.build_absolute_uri(path)


def page_meta(request, description: str, *, index: bool = True, canonical: str | None = None):
    """The ``page_meta`` of a help page: its description, whether search engines may index
    it, and (hosted mode) its canonical address, ``canonical`` or the page's own path."""
    meta = {"description": " ".join(str(description).split()), "noindex": not index}
    if settings.IS_HOSTED and (index or canonical):
        meta["canonical"] = absolute(request, canonical or request.path)
    return meta


def help_urls() -> list[str]:
    """Every indexable help page, in the order of the help's contents."""
    from climpact_web.help.contents import REFERENCE
    from climpact_web.help.guides import GUIDE_ORDER, guide_url
    from climpact_web.help.indices import catalogue
    from climpact_web.help.reference import index_url

    urls = [reverse("help:index")]
    urls += [guide_url(slug) for slug in GUIDE_ORDER]
    for item in REFERENCE:
        urls.append(item.url)
        if item.key == "index-reference":
            urls += [index_url(info) for info in catalogue()]
        urls += [child.url for child in item.children]
    urls.append(reverse("help:topics"))
    return [u for u in urls if u]


@require_safe
def sitemap(request):
    if not settings.IS_HOSTED:
        raise Http404
    entries = "".join(
        f"<url><loc>{escape(absolute(request, url))}</loc></url>" for url in help_urls()
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>\n'
    )
    return HttpResponse(body, content_type="application/xml")


@require_safe
def robots(request):
    if not settings.IS_HOSTED:
        return HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")
    lines = ["User-agent: *", "Allow: /help/"]
    lines += [f"Disallow: {path}" for path in DISALLOWED]
    lines += ["", f"Sitemap: {absolute(request, '/sitemap.xml')}", ""]
    return HttpResponse("\n".join(lines), content_type="text/plain")

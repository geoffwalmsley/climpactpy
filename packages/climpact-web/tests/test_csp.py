"""The Content Security Policy (#137): the header, its settings, and templates free of the
inline code it forbids. The browser test in test_accessibility.py checks that no page
breaks the policy at run time."""

import base64
import hashlib
import re
from pathlib import Path

import pytest
from django.test import override_settings
from django.utils.csp import CSP
from test_settings import HOSTED, load_settings  # noqa: F401 (a fixture)

import climpact_web
from climpact_web.core import tokens
from climpact_web.settings import (
    TURNSTILE_ORIGIN,
    WEB_ANALYTICS_REPORT_ORIGIN,
    WEB_ANALYTICS_SCRIPT_ORIGIN,
    content_security_policy,
)

PACKAGE = Path(climpact_web.__file__).parent
TEMPLATES = sorted(PACKAGE.glob("**/templates/**/*.html"))
CSS = (PACKAGE / "core" / "static" / "climpact_web" / "css" / "climpact.css").read_text()
TURNSTILE_KEYS = {
    "CLIMPACT_WEB_TURNSTILE_SITE_KEY": "1x00000000000000000000AA",
    "CLIMPACT_WEB_TURNSTILE_SECRET_KEY": "1x0000000000000000000000000000000AA",
}


def directives(header: str) -> dict[str, list[str]]:
    out = {}
    for part in header.split(";"):
        name, *values = part.split()
        out[name] = values
    return out


NONCE = re.compile(r"'nonce-[A-Za-z0-9_-]{22}'")


def nonce_of(policy: dict[str, list[str]]) -> str:
    """The one nonce in ``script-src`` (the header carries it in place of CSP.NONCE)."""
    nonces = [v for v in policy["script-src"] if NONCE.fullmatch(v)]
    assert len(nonces) == 1, policy["script-src"]
    return nonces[0]


def assert_strict(policy: dict[str, list[str]]) -> None:
    for name, values in policy.items():
        assert CSP.UNSAFE_INLINE not in values, name
        assert CSP.UNSAFE_EVAL not in values, name
        assert CSP.UNSAFE_HASHES not in values, name
        if name != "script-src":
            assert not any(NONCE.fullmatch(v) for v in values), name
    assert policy["default-src"] == ["'self'"]
    assert policy["object-src"] == ["'none'"]
    assert policy["base-uri"] == ["'none'"]
    assert policy["frame-ancestors"] == ["'none'"]
    assert policy["form-action"] == ["'self'"]


# ---- The header ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/", "/add/", "/help/", "/no-such-page/"])
def test_every_response_has_an_enforced_policy(client, path):
    response = client.get(path)
    assert "Content-Security-Policy-Report-Only" not in response
    policy = directives(response["Content-Security-Policy"])
    assert_strict(policy)
    assert policy["script-src"] == ["'self'", nonce_of(policy)]
    assert policy["style-src"][0] == "'self'"
    assert policy["img-src"] == ["'self'", "data:"]
    assert policy["connect-src"] == ["'self'"]
    assert policy["frame-src"] == ["'none'"]
    # Old browsers that ignore frame-ancestors still get X-Frame-Options.
    assert response["X-Frame-Options"] == "DENY"


@pytest.mark.django_db
def test_turnstile_pages_allow_cloudflare(client):
    """With Turnstile on, its script and challenge frame load from Cloudflare, and the
    policy is otherwise as strict."""
    policy = content_security_policy(turnstile=True)
    with override_settings(SECURE_CSP=policy):
        header = directives(client.get("/add/")["Content-Security-Policy"])
    assert_strict(header)
    assert header["script-src"] == ["'self'", nonce_of(header), TURNSTILE_ORIGIN]
    assert header["frame-src"] == [TURNSTILE_ORIGIN]
    assert header["connect-src"] == ["'self'"]
    assert TURNSTILE_ORIGIN not in header["style-src"]


@pytest.mark.django_db
def test_every_page_gets_a_fresh_nonce(client):
    """Each HTML page's header has its own nonce, though no template reads it (Django adds
    one only when something does), so Cloudflare always has one to copy to the scripts its
    edge injects (#164). No page is cached, so no page is served with an old nonce."""
    seen = set()
    for path in ["/", "/", "/add/", "/help/", "/no-such-page/"]:
        response = client.get(path)
        assert response["Content-Type"].startswith("text/html")
        seen.add(nonce_of(directives(response["Content-Security-Policy"])))
        assert "private" in response["Cache-Control"] or "no-cache" in response["Cache-Control"]
    assert len(seen) == 5


@pytest.mark.django_db
def test_report_only_header_has_the_nonce(client, settings):
    """Report-only mode (the first deployment) sends the nonce too, in the header Cloudflare
    reads (it ignores nonces in meta tags)."""
    settings.SECURE_CSP, settings.SECURE_CSP_REPORT_ONLY = {}, content_security_policy(False)
    response = client.get("/")
    assert "Content-Security-Policy" not in response
    assert_strict(policy := directives(response["Content-Security-Policy-Report-Only"]))
    nonce_of(policy)


def test_non_html_answers_get_no_nonce(rf, settings):
    """A nonce is forced only on HTML pages; other answers keep Django's lazy behaviour."""
    from django.http import HttpResponse

    from climpact_web.middleware import ContentSecurityPolicyMiddleware

    settings.SECURE_CSP = content_security_policy(False)
    middleware = ContentSecurityPolicyMiddleware(
        lambda request: HttpResponse("{}", content_type="application/json")
    )
    policy = directives(middleware(rf.get("/x.json"))["Content-Security-Policy"])
    assert policy["script-src"] == ["'self'"]


@pytest.mark.django_db
def test_web_analytics_allowance(client):
    """With Web Analytics allowed (hosted mode), Cloudflare's beacon script and reports are
    allowed from its two hosts and nothing else changes."""
    policy = content_security_policy(turnstile=True, analytics=True)
    with override_settings(SECURE_CSP=policy):
        header = directives(client.get("/")["Content-Security-Policy"])
    assert_strict(header)
    assert header["script-src"] == [
        "'self'",
        nonce_of(header),
        TURNSTILE_ORIGIN,
        WEB_ANALYTICS_SCRIPT_ORIGIN,
    ]
    assert header["connect-src"] == ["'self'", WEB_ANALYTICS_REPORT_ORIGIN]
    assert header["frame-src"] == [TURNSTILE_ORIGIN]
    assert header["img-src"] == ["'self'", "data:"]


def test_the_error_page_style_hash_matches(settings):
    """The stand-alone 500 page's one inline <style> is allowed by its hash."""
    html = (PACKAGE / "core" / "templates" / "500.html").read_text()
    css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(css.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in settings.SECURE_CSP["style-src"]


# ---- The settings -------------------------------------------------------------------------


def test_policy_enforced_by_default_in_both_modes(load_settings):  # noqa: F811
    for env, hosted in (({}, False), (HOSTED, True)):
        s = load_settings(**env)
        # Web Analytics is allowed by default in hosted mode, never in local mode.
        assert s.SECURE_CSP == content_security_policy(turnstile=False, analytics=hosted)
        assert s.SECURE_CSP_REPORT_ONLY == {}
        assert CSP.NONCE in s.SECURE_CSP["script-src"]
        assert "climpact_web.middleware.ContentSecurityPolicyMiddleware" in s.MIDDLEWARE
        assert "django.middleware.csp.ContentSecurityPolicyMiddleware" not in s.MIDDLEWARE


def test_web_analytics_switch(load_settings):  # noqa: F811
    """CLIMPACT_WEB_CF_WEB_ANALYTICS=false drops the allowance in hosted mode; in local
    mode it never applies."""
    off = load_settings(**HOSTED, CLIMPACT_WEB_CF_WEB_ANALYTICS="false")
    assert off.SECURE_CSP == content_security_policy(turnstile=False)
    assert WEB_ANALYTICS_SCRIPT_ORIGIN not in off.SECURE_CSP["script-src"]
    assert off.SECURE_CSP["connect-src"] == [CSP.SELF]
    local = load_settings(CLIMPACT_WEB_CF_WEB_ANALYTICS="true")
    assert local.SECURE_CSP == content_security_policy(turnstile=False)


def test_report_only_switch(load_settings):  # noqa: F811
    s = load_settings(CLIMPACT_WEB_CSP_REPORT_ONLY="true")
    assert s.SECURE_CSP == {}
    assert s.SECURE_CSP_REPORT_ONLY == content_security_policy(turnstile=False)


def test_turnstile_keys_extend_the_policy_in_hosted_mode_only(load_settings):  # noqa: F811
    hosted = load_settings(**HOSTED, **TURNSTILE_KEYS)
    assert hosted.SECURE_CSP == content_security_policy(turnstile=True, analytics=True)
    assert TURNSTILE_ORIGIN in hosted.SECURE_CSP["script-src"]
    assert hosted.SECURE_CSP["frame-src"] == [TURNSTILE_ORIGIN]
    # Turnstile is never on in local mode (core/limits.py), so neither is Cloudflare.
    local = load_settings(**TURNSTILE_KEYS)
    assert local.SECURE_CSP == content_security_policy(turnstile=False)


# ---- The templates ------------------------------------------------------------------------

INLINE = {
    "inline script": re.compile(r"<script(?![^>]*\bsrc=)[^>]*>"),
    "inline style": re.compile(r"<style\b"),
    "style attribute": re.compile(r"\sstyle="),
    "event handler attribute": re.compile(r"\son[a-z]+=", re.I),
    "htmx eval": re.compile(r"hx-on|js:|javascript:|\[[^\]]*document\."),
}


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: str(p.relative_to(PACKAGE)))
def test_templates_have_no_inline_code(path):
    """No template has what the policy blocks: inline scripts, inline styles (except the
    500 page's, allowed by hash), style or event handler attributes, or htmx attributes
    that need eval (js: values, hx-on, JavaScript trigger filters)."""
    text = re.sub(
        r"\{#.*?#\}|\{% comment %\}.*?\{% endcomment %\}", "", path.read_text(), flags=re.S
    )
    found = [
        what
        for what, pattern in INLINE.items()
        if pattern.search(text) and not (path.name == "500.html" and what == "inline style")
    ]
    assert not found, f"{path.name}: {found}"


def test_every_chart_token_has_a_swatch_class():
    for name in tokens.theme_tokens()["light"]:
        if name.startswith("chart-"):
            assert f".swatch-{name}{{--swatch:var(--{name})}}" in CSS, name


def test_every_chart_height_has_a_class():
    used = {"16rem"}  # chart_frame.html's default
    for path in TEMPLATES:
        used |= set(re.findall(r'height="(\d+(?:\.\d+)?rem)"', path.read_text()))
    for height in used:
        assert f".chart-height-{height}{{" in CSS, height


def test_markup_built_in_python_or_javascript_has_no_style_attributes():
    """The SVG plots drawn in Python (QC, sector) and the markup built in the scripts take
    their colours from classes too: a style attribute would be blocked."""
    sources = [
        *PACKAGE.glob("**/*.py"),
        *(PACKAGE / "core" / "static").glob("climpact_web/js/*.js"),
    ]
    for path in sources:
        text = path.read_text()
        assert not re.search(r"""style=['"\\]|setAttribute\(['"]style""", text), path.name

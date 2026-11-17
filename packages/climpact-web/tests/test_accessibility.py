"""Accessibility checks of every page type in a real browser (#83, WCAG 2.1 AA).

The app runs as a user runs it (``climpact-web`` on a free port, with its worker), and
headless Chrome (``browser.py``, over the DevTools protocol) goes through the sample
station (steps 1 to 5 and the downloads), the sample batch and the sample grid, so every
page is checked with real results. On each page:

- **axe** (axe-core, vendored in ``assets/axe-core``): every WCAG 2.1 A and AA rule and
  axe's best practices in the light theme and in a 320 px wide viewport, and the contrast
  rules again in the dark theme. A serious or critical violation fails
  ``test_axe_every_page``; ``test_no_axe_violations_at_all`` fails on any;
- **reflow**: no horizontal scrolling at 320 px wide (WCAG 1.4.10, the same as 400% zoom)
  and at 200% zoom (1.4.4);
- **keyboard**: Tab through the whole page: the skip link comes first and works, every
  stop is visible and has a visible focus indicator, focus never gets stuck and comes back
  round to the start (2.1.1, 2.1.2, 2.4.1, 2.4.3, 2.4.7); the same in forced colours
  (Windows high contrast), where box shadows disappear;
- **reduced motion**: no animation or transition longer than 0.1 s (2.3.3);
- the page's language, title, one ``main`` and one ``h1``.

The widgets (tabs, dialog, drop zone, charts, the tour, the gridded map) are worked by
keyboard in their own tests, and the progress regions are checked for live announcements.

Chrome is the one already installed (``CHROME`` names another); without one the tests
skip, unless ``CLIMPACT_A11Y_REQUIRE_CHROME`` is set (CI), when they fail.
``CLIMPACT_A11Y_REPORT=<folder>`` saves a JSON report and screenshots there.

The module is marked ``browser``, which the default ``addopts`` deselect (it takes about
2.5 minutes); run it with ``uv run pytest -m browser``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import pytest
from browser import Chrome, DevToolsError, find_chrome

pytestmark = pytest.mark.browser

ASSETS = Path(__file__).parent / "assets" / "axe-core"
AXE = ASSETS / "axe.min.js"
AXE_VERSION = "4.14.0"
AXE_SHA256 = "20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878"
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]
FAILING_IMPACTS = {"serious", "critical"}
REPORT = os.environ.get("CLIMPACT_A11Y_REPORT")

STATION = "sydney_observatory_hill_1936-2015"


def test_vendored_axe_is_the_pinned_release():
    """The vendored axe-core is the release recorded in its README, unmodified."""
    assert hashlib.sha256(AXE.read_bytes()).hexdigest() == AXE_SHA256
    assert AXE.read_text(encoding="utf-8").startswith(f"/*! axe v{AXE_VERSION}")
    readme = (ASSETS / "README.md").read_text(encoding="utf-8")
    assert AXE_VERSION in readme and AXE_SHA256 in readme
    assert "Mozilla Public License" in (ASSETS / "LICENSE").read_text(encoding="utf-8")


# ---- The browser and the app ---------------------------------------------------------------


@pytest.fixture(scope="module")
def chrome():
    pytest.importorskip("websocket", reason="websocket-client is needed (a dev dependency)")
    executable = find_chrome()
    if not executable and os.environ.get("CLIMPACT_A11Y_REQUIRE_CHROME"):
        pytest.fail("CLIMPACT_A11Y_REQUIRE_CHROME is set but no Chrome was found (set CHROME)")
    if not executable:
        pytest.skip(
            "No Chrome or Chromium found, so the browser accessibility checks (#83) did not "
            "run. Install Chrome, or set CHROME to its executable."
        )
    browser = Chrome(executable)
    yield browser
    browser.close()


@contextmanager
def running_app(data: Path, **env: str):
    """``climpact-web`` on a free port with its worker, in the data folder ``data``, with
    extra environment variables; yields its URL."""
    inherited = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("CLIMPACT_WEB_") and k != "DJANGO_SETTINGS_MODULE"
    }
    env = {**inherited, "CLIMPACT_WEB_PATTERN_LIBRARY": "true", **env}
    proc = subprocess.Popen(
        [sys.executable, "-m", "climpact_web", "--no-browser", "--port", "0"]
        + ["--data-dir", str(data)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    url, output, deadline = None, [], time.monotonic() + 120
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        output.append(line)
        if "is running at " in line:
            url = line.rsplit(" ", 1)[1].strip()
            break
    if not url:
        proc.kill()
        pytest.fail("climpact-web did not start:\n" + "".join(output))
    try:
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(30)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """``climpact-web`` on a free port with its worker, in a fresh data folder."""
    with running_app(tmp_path_factory.mktemp("a11y-data")) as url:
        yield url


# What happened while the jobs ran, for the tests of progress pages: axe on each progress
# page while its job was running, what the announcer said, and whether keyboard focus on
# the batch's cancel button survived the progress polls.
WHILE_RUNNING: dict[str, dict] = {}


def wait_for(
    c: Chrome, predicate: str, timeout: float = 600, what: str = "", heard: list | None = None
) -> None:
    """Wait until a JavaScript expression is true (pages may navigate meanwhile); with
    ``heard``, collect what the page's announcer (#announcer) says meanwhile, including
    once more when the expression comes true: the swap that makes it true may also have
    announced (a job's end), after the announcer was last read."""

    def listen() -> None:
        if heard is not None:
            said = c.evaluate("(document.getElementById('announcer') || {}).textContent")
            if said and (not heard or heard[-1] != said):
                heard.append(said)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            listen()
            if c.evaluate(predicate):
                c.settle()
                listen()
                return
        except DevToolsError:
            pass  # the page is navigating
        time.sleep(0.25)
    raise AssertionError(
        f"timed out waiting for {what or predicate} on {c.evaluate('location.href')}"
    )


# A station file of two years, readable.
GOOD_FILE = "".join(
    f"{d.year} {d.month} {d.day} 0 20 10\n"
    for d in (dt.date(2000, 1, 1) + dt.timedelta(days=k) for k in range(731))
)


def setup_sample(c: Chrome, open_url) -> None:
    """The Sydney sample on its station's setup page (``/station/sample``, the old New
    station's sample, which Add stations replaced, #233): the page a station's new file
    that needs new details comes back to."""
    c.navigate(open_url("/add/"))
    c.evaluate(
        "var f = document.createElement('form'); f.method = 'post';"
        " f.action = '/station/sample'; f.id = 'old-sample';"
        " f.appendChild(document.querySelector('[name=csrfmiddlewaretoken]').cloneNode());"
        " document.body.appendChild(f)"
    )
    submit(c, "#old-sample")


def choose_file(c: Chrome, input: str, name: str, text: str) -> None:
    """Choose a file in a file input (a CSS selector) as the file picker would, and wait
    for the page the change sends the form to (the New station page's, #201)."""
    c.events.clear()
    c.evaluate(
        "(function () { var t = new DataTransfer();"
        f" t.items.add(new File([{json.dumps(text)}], {json.dumps(name)}));"
        f" var i = document.querySelector({json.dumps(input)}); i.files = t.files;"
        " i.dispatchEvent(new Event('change', {bubbles: true})); })()"
    )
    c.wait_event("Page.loadEventFired", timeout=120)
    c.settle()


def submit(c: Chrome, form: str, submitter: str | None = None) -> None:
    """Submit a form (a CSS selector) as a click would, and wait for the next page."""
    c.events.clear()
    button = f"document.querySelector({json.dumps(submitter)})" if submitter else "undefined"
    c.evaluate(f"document.querySelector({json.dumps(form)}).requestSubmit({button})")
    c.wait_event("Page.loadEventFired", timeout=120)
    c.settle()


def here(c: Chrome) -> str:
    return c.evaluate("location.href")


def while_running(c: Chrome, name: str) -> list:
    """axe on a progress page as its job runs; returns the list the announcer fills."""
    WHILE_RUNNING[name] = {"axe": run_axe(c), "heard": []}
    return WHILE_RUNNING[name]["heard"]


@pytest.fixture(scope="module")
def site(chrome, server):
    """Every page type, with real results: name -> URL, or a function that opens a page
    which has no URL of its own (a form's answer). Built once by going through the sample
    station, batch and grid in the browser; the worker runs the jobs."""
    c = chrome
    pages: dict[str, object] = {}

    def open_url(path):
        return urljoin(server, path)

    # Pages that need no data.
    for name, path in [
        ("landing", "/"),
        ("pattern library", "/patterns/"),
        ("add stations", "/add/"),
        ("gridded start", "/gridded/"),
        ("help", "/help/"),
        ("help guide", "/help/quality-control/"),
        ("help indices", "/help/indices/"),
        ("help topics", "/help/topics/"),
        ("help search", "/help/search/?q=base+period"),
        ("accessibility statement", "/help/accessibility/"),
        ("not found", "/no-such-page/"),
    ]:
        pages[name] = open_url(path)

    def upload_errors(c):
        """Add stations sent without a file: it asks for one (#233)."""
        c.navigate(open_url("/add/"))
        c.evaluate("document.querySelector('[data-nojs]').hidden = false")
        submit(c, "#add-form", "#add-form button[value=files]")

    def file_errors(c):
        """Files chosen (so sent at once), one that cannot be read and one with no
        coordinates: the review table says so, every problem at once (#233)."""
        c.navigate(open_url("/add/"))
        choose_file(c, "[data-add-files]", "bad.txt", "2000 1 1 0 20 10\n2000 1 2 0.4 21\n")
        choose_file(c, "[data-add-files]", "good.txt", GOOD_FILE)

    pages["add stations, errors"] = upload_errors
    pages["add stations, file errors"] = file_errors

    # Station steps 1-5 with the Sydney sample, from a station's own setup page (a new
    # file that needs new details; Add stations' sample opens Quality at once).
    setup_sample(c, open_url)
    load = pages["station sample loaded"] = here(c)

    def metadata_errors(c):
        c.navigate(load)
        c.evaluate(
            "document.querySelector('[name=latitude]').value = '123';"
            "document.querySelector('[name=base_end]').value = '1960'"
        )
        submit(c, "#new-station", "#new-station button[value=go]")

    pages["station details, errors"] = metadata_errors

    # The rest on a second sample, so the first stays on its details page: once they are
    # confirmed, its address leads to Quality (#198). Add stations' sample (#233).
    c.navigate(open_url("/add/"))
    submit(c, "#sample-form")
    heard = while_running(c, "station quality checks")
    wait_for(c, "!!document.querySelector('form[action$=\"/quality/continue\"]')",
             what="the quality checks", heard=heard)  # fmt: skip
    pages["station quality results"] = here(c)
    # "Use this data" opens the results of the run queued with the checks (#178), or its
    # progress until it has finished.
    submit(c, "form[action$='/quality/continue']")
    wait_for(c, "!!document.querySelector('[data-results-filter]')",
             what="the speculative station run")  # fmt: skip
    results = pages["station results"] = here(c).split("?")[0].split("#")[0]
    back = "?next=" + quote(urlparse(results).path)
    # The thresholds and index settings sheets as pages, as without JavaScript (#199): the
    # long one gets the full audit. The sheets themselves: test_settings_sheet_by_keyboard.
    pages["station edit, thresholds"] = results.replace("/indices", "/inputs/thresholds") + back
    pages["station edit, settings"] = results.replace("/indices", "/inputs/settings") + back

    def settings_errors(c):
        c.navigate(pages["station edit, settings"])
        c.evaluate("document.querySelector('[name=hdd_base]').value = 'warm'")
        submit(c, "#input-form")

    pages["station edit, settings, errors"] = settings_errors
    # New settings from the sheet: the results they replace under their progress, then
    # the new results.
    c.navigate(results)
    c.evaluate("document.querySelector('[data-sheet-open=\"sheet-settings\"]').click();"
               "document.querySelector('#sheet-settings-form').rx_days.value = '4'")  # fmt: skip
    submit(c, "#sheet-settings-form")
    heard = while_running(c, "station run")
    wait_for(c, "!!document.querySelector('[data-results-filter]')"
             " && !document.querySelector('[data-stale-banner], .recalculation')",
             what="the station run", heard=heard)  # fmt: skip
    # An input's form on its own page, as without JavaScript (#198).
    pages["station edit, base period"] = results.replace("/indices", "/inputs/base-period") + back
    pages["station index"] = results + "/txx"
    pages["station index, spi"] = results + "/spi"
    pages["station index, monthly anomalies"] = results + "/txx?series=txx_MON&view=anomaly"
    pages["station downloads"] = results.replace("/indices", "/downloads")
    sector = results.replace("/indices", "/sector")
    pages["station sector"] = sector
    c.navigate(sector)
    submit(c, "form[action$='/sector']", "button[name=sample]")
    heard = while_running(c, "sector comparison")
    wait_for(c, "!!document.querySelector('.sector-plot')", what="the sector comparison",
             heard=heard)  # fmt: skip
    pages["station sector results"] = sector

    # Out of date (#179), on a second sample station so the pages above keep their state:
    # a new base period in the Inputs panel's sheet (#198), its run's progress over the old
    # results, then that run cancelled, which leaves the old results out of date under
    # "Recalculate".
    c.navigate(open_url("/add/"))
    submit(c, "#sample-form")
    wait_for(c, "!!document.querySelector('form[action$=\"/quality/continue\"]')",
             what="the second station's checks")  # fmt: skip
    submit(c, "form[action$='/quality/continue']")
    wait_for(c, "!!document.querySelector('[data-results-filter]')"
             " && !document.querySelector('[data-stale-banner]')",
             what="the second station's run")  # fmt: skip
    c.evaluate("document.querySelector('[data-sheet-open=\"sheet-base-period\"]').click();"
               "var f = document.getElementById('sheet-base-period-form');"
               "f.base_start.value = '1981'; f.base_end.value = '2010'")  # fmt: skip
    submit(c, "#sheet-base-period-form")
    while_running(c, "station results, updating")
    submit(c, "[data-stale-banner] form[action$='/cancel']")
    wait_for(c, "!!document.querySelector('[data-stale-banner] input[name=recalculate]')",
             what="the out-of-date results")  # fmt: skip
    pages["station results, out of date"] = here(c).split("#")[0]

    # The jobs.
    pages["jobs"] = open_url("/jobs/")
    c.navigate(pages["jobs"])
    job = c.evaluate(
        'document.querySelector(\'a[href^="/jobs/"][href$="/"]:not([href="/jobs/"])\').href'
    )
    pages["job"] = job

    # The sample batch, from the help: its two files reviewed on Add stations (#233), then
    # added, which runs them as a batch.
    c.navigate(open_url("/help/"))
    submit(c, "form[action$='/add/sample-batch']")
    pages["add stations, review"] = here(c)
    submit(c, "#add-form", "#add-form button[value=add]")
    heard = while_running(c, "batch")
    # Keyboard focus on the cancel button stays there while the progress is polled: the
    # mark goes when the progress replaces itself (the first poll, or the batch's end).
    cancel = "#workspace-progress form[action$='/cancel'] button"
    c.evaluate(
        f"document.querySelector({json.dumps(cancel)}).focus();"
        "document.querySelector('#workspace-progress').dataset.a11yMark = '1'"
    )
    swapped = "!(document.querySelector('#workspace-progress') || {dataset: {}}).dataset.a11yMark"
    wait_for(c, swapped, timeout=10, what="the batch's progress to update", heard=heard)
    WHILE_RUNNING["batch"]["focus"] = c.evaluate(
        "({swapped: !document.querySelector('#workspace-progress').dataset.a11yMark,"
        " running: document.querySelector('#workspace-progress').dataset.status !== 'finished',"
        f" kept: document.activeElement === document.querySelector({json.dumps(cancel)})}})"
    )
    wait_for(c, "document.querySelector('#workspace-progress') &&"
             " document.querySelector('#workspace-progress').dataset.status === 'finished'",
             what="the batch", heard=heard)  # fmt: skip
    # The workspace's overview (#234), its settings and Rename.
    pages["workspace overview"] = here(c).split("#")[0]
    pages["workspace settings"] = pages["workspace overview"] + "settings/"
    pages["workspace setting"] = pages["workspace overview"] + "settings/base-period"
    pages["workspace rename"] = pages["workspace overview"] + "rename"

    # The sample grid: thresholds, then three indices.
    c.navigate(open_url("/gridded/"))
    submit(c, "form[action$='/gridded/sample']")
    pages["gridded set-up"] = here(c)
    c.evaluate(
        "document.querySelectorAll('input[name=indices]').forEach(function (box) {"
        " box.checked = ['txx', 'fd', 'spi'].indexOf(box.value) >= 0 })"
    )
    submit(c, "form[action$='/']:has(input[name=indices])")
    heard = while_running(c, "gridded run")
    wait_for(c, "!!document.querySelector('.gmap')", what="the gridded run", heard=heard)
    pages["gridded results"] = here(c)

    # The error pages without a URL.
    def too_large(c):
        """The 413 page, as the server answers an upload over the limit."""
        html = c.evaluate(
            "fetch('/station/new', {method: 'POST', body: new Uint8Array(51 * 1024 * 1024)})"
            ".then(function (r) { return r.text() })",
            await_promise=True,
        )
        c.navigate(open_url("/station/new"))
        c.set_content(html)

    def server_error(c):
        from django.template.loader import render_to_string

        c.navigate(open_url("/station/new"))
        c.set_content(render_to_string("500.html"))

    pages["upload too large"] = too_large
    pages["server error"] = server_error
    return pages


def open_page(c: Chrome, page) -> None:
    if callable(page):
        page(c)
    else:
        c.navigate(page)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def set_mode(c: Chrome, width: int = 1280, scheme: str = "light", scale: float = 1, **media):
    c.viewport(width, 900, scale)
    c.media(prefers_color_scheme=scheme, **media)


def run_axe(c: Chrome, rules: list[str] | None = None) -> list[dict]:
    """axe's violations on the page as it is now (all WCAG 2.1 A/AA and best-practice
    rules, or only the rules named)."""
    if not c.evaluate("typeof axe !== 'undefined'"):
        c.evaluate(AXE.read_text(encoding="utf-8"))
    run_only = {"type": "rule", "values": rules} if rules else {"type": "tag", "values": AXE_TAGS}
    options = json.dumps({"runOnly": run_only, "resultTypes": ["violations"]})
    return c.evaluate(
        f"axe.run(document, {options}).then(function (r) {{ return r.violations.map("
        "function (v) { return {id: v.id, impact: v.impact, help: v.help,"
        " nodes: v.nodes.map(function (n) { return {target: n.target.join(' '),"
        " summary: n.failureSummary, html: n.html.slice(0, 200)} })} }) })",
        await_promise=True,
    )


# ---- What each check reads from the page ---------------------------------------------------

OVERFLOW = """(function () {
  var width = document.documentElement.clientWidth;
  var wide = [];
  document.querySelectorAll('body *').forEach(function (el) {
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.right <= width + 1) return;
    for (var p = el.parentElement; p; p = p.parentElement) {
      var o = getComputedStyle(p).overflowX;
      if (o === 'auto' || o === 'scroll' || o === 'hidden' || o === 'clip') return;
    }
    wide.push(el.tagName.toLowerCase() + '.' + String(el.getAttribute('class') || '')
      .trim().split(/\\s+/).join('.') + ' ' + Math.round(r.right));
  });
  return {scroll: document.documentElement.scrollWidth, width: width, wide: wide.slice(0, 5)};
})()"""

# The focused element: a path to it, whether it (or, for a visually hidden input such as
# the drop zone's, the control drawn for it) is visible, and whether it or a near ancestor
# draws a focus outline. In forced colours box shadows are not drawn, so only an outline
# counts; "auto" is the browser's own focus ring.
FOCUSED = """(function (forced) {
  var el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  if (el.hasAttribute('data-a11y-start')) return {start: true};
  function path(e) {
    var parts = [];
    for (; e && e.nodeType === 1 && e !== document.body; e = e.parentElement) {
      var i = 1, s = e;
      while ((s = s.previousElementSibling)) if (s.tagName === e.tagName) i++;
      parts.unshift(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + ':nth-of-type(' + i + ')');
    }
    return parts.join('>');
  }
  function sized(e) {
    var r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width >= 4 && r.height >= 4 && s.opacity !== '0';
  }
  function ring(e) {
    var s = getComputedStyle(e);
    var outline = s.outlineStyle !== 'none' &&
      (s.outlineStyle === 'auto' || parseFloat(s.outlineWidth) >= 2);
    return outline || (!forced && s.boxShadow !== 'none');
  }
  var shown = el;
  for (var n = 0; shown && !sized(shown) && n < 4; n++) shown = shown.parentElement;
  var indicator = false;
  for (var e = el, i = 0; e && i < 4; e = e.parentElement, i++) {
    if (ring(e)) { indicator = true; break; }
  }
  var hidden = !shown;
  for (var h = shown; h; h = h.parentElement) {
    var hs = getComputedStyle(h);
    if (hs.visibility === 'hidden' || hs.display === 'none' || hs.opacity === '0') hidden = true;
  }
  return {key: path(el), tag: el.tagName.toLowerCase(),
    text: (el.getAttribute('aria-label') || el.innerText || el.value || '').trim().slice(0, 50),
    visible: !hidden && sized(shown), indicator: indicator,
    skip: el.classList.contains('skip-link')};
})(%s)"""

# Sequential focus starts from a marker at the top of the body that is not itself a Tab
# stop (blurring would leave the starting point wherever focus last was).
START = """(function () {
  var old = document.querySelector('[data-a11y-start]');
  if (old) old.remove();
  var start = document.createElement('span');
  start.setAttribute('data-a11y-start', '');
  start.tabIndex = -1;
  document.body.insertBefore(start, document.body.firstChild);
  window.scrollTo(0, 0);
  start.focus();
})()"""

MOTION = """(function () {
  function longest(list) {
    return Math.max.apply(null, list.split(',').map(function (t) {
      t = t.trim(); return t.endsWith('ms') ? parseFloat(t) / 1000 : parseFloat(t) || 0; }));
  }
  var moving = [];
  document.querySelectorAll('*').forEach(function (el) {
    [null, '::before', '::after'].forEach(function (pseudo) {
      var s = getComputedStyle(el, pseudo);
      var runs = s.animationIterationCount === 'infinite' ? 1000 :
        parseFloat(s.animationIterationCount);
      var a = s.animationName !== 'none' ? longest(s.animationDuration) * runs : 0;
      var t = longest(s.transitionDuration);
      if (a > 0.1 || t > 0.1) {
        moving.push(el.tagName.toLowerCase() + '.' + el.getAttribute('class') + (pseudo || ''));
      }
    });
  });
  var smooth = getComputedStyle(document.documentElement).scrollBehavior;
  return {moving: moving.slice(0, 5), smooth: smooth};
})()"""

STRUCTURE = """(function () {
  var skip = document.querySelector('.skip-link');
  var named = function (el) {
    return el.getAttribute('aria-label') || el.getAttribute('aria-labelledby'); };
  return {lang: document.documentElement.lang, title: document.title.trim(),
    mains: document.querySelectorAll('main, [role=main]').length,
    h1: document.querySelectorAll('h1').length,
    skipTarget: !skip || !!document.querySelector(skip.getAttribute('href')),
    unnamed: Array.prototype.filter.call(document.querySelectorAll(
      '[role=region], [role=group][tabindex], [role=toolbar], nav, [role=tablist]'),
      function (el) { return !named(el); }).map(function (el) {
        return el.tagName.toLowerCase() + '.' + (el.getAttribute('class') || ''); })};
})()"""

MAX_TABS = 1500


def tab_through(c: Chrome, forced: bool = False) -> tuple[list[dict], str | None]:
    """Tab from the top of the page until focus comes back round; returns the stops and
    a problem (a trap, or no way round), or None."""
    c.evaluate(START)
    stops, seen = [], set()
    for _ in range(MAX_TABS):
        c.press("Tab")
        info = c.evaluate(FOCUSED % ("true" if forced else "false"))
        if info is None or info.get("start"):  # out of the page: the cycle is complete
            return stops, None
        if info["key"] in seen:
            if info["key"] == stops[0]["key"]:
                return stops, None
            return stops, f"focus came back to {info['key']} ({info['text']!r}): a loop"
        seen.add(info["key"])
        stops.append(info)
    return stops, f"{MAX_TABS} stops without coming back round"


def skip_link_works(c: Chrome) -> bool:
    c.evaluate(START)
    c.press("Tab")
    c.press("Enter")
    time.sleep(0.1)
    return c.evaluate("document.activeElement.id") == "main"


# ---- The audit: every page once, every check ------------------------------------------------


@pytest.fixture(scope="module")
def audit(chrome, site):
    """Each page opened once, and everything the tests below assert on read from it:
    name -> {check: findings}. Saved to CLIMPACT_A11Y_REPORT with screenshots."""
    c = chrome
    found: dict[str, dict] = {}
    shots = Path(REPORT) / "screenshots" if REPORT else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    for name, page in site.items():
        f = found[name] = {}
        set_mode(c)
        open_page(c, page)
        f["structure"] = c.evaluate(STRUCTURE)
        f["positive tabindex"] = c.evaluate(
            'document.querySelectorAll(\'[tabindex]:not([tabindex^="-"]):not([tabindex="0"])\')'
            ".length"
        )
        # axe: every rule in the light theme and at 320 px; contrast again in dark.
        f["axe light"] = run_axe(c)
        if shots:
            c.screenshot(shots / f"{slug(name)}-light.png")
        set_mode(c, scheme="dark")
        c.transitions_done()  # colour transitions run to their end
        f["axe dark"] = run_axe(c, ["color-contrast", "link-in-text-block"])
        if shots:
            c.screenshot(shots / f"{slug(name)}-dark.png")
        # Keyboard, then the same in forced colours.
        set_mode(c)
        f["tab stops"], f["tab problem"] = tab_through(c)
        has_skip = c.evaluate("!!document.querySelector('.skip-link')")
        f["skip link"] = skip_link_works(c) if has_skip else None
        set_mode(c, forced_colors="active")
        f["tab stops forced"], f["tab problem forced"] = tab_through(c, forced=True)
        if shots:
            c.screenshot(shots / f"{slug(name)}-forced-colours.png")
        # Reduced motion.
        set_mode(c, prefers_reduced_motion="reduce")
        f["motion"] = c.evaluate(MOTION)
        # Reflow: 200% zoom, then 320 px (where axe runs again: content changes there).
        set_mode(c, 640, scale=2)
        c.settle(0.1)
        f["reflow 200% zoom"] = c.evaluate(OVERFLOW)
        set_mode(c, 320)
        c.settle(0.1)
        f["reflow 320px"] = c.evaluate(OVERFLOW)
        f["axe 320px"] = run_axe(c)
        if shots:
            c.screenshot(shots / f"{slug(name)}-320px.png")
    set_mode(c)
    if REPORT:
        summary = {
            name: {k: (len(v) if k.startswith("tab stops") else v) for k, v in checks.items()}
            for name, checks in found.items()
        }
        summary["while running"] = WHILE_RUNNING
        Path(REPORT, "report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return found


def test_axe_every_page(audit):
    """No serious or critical axe violation on any page, in the light theme, the dark
    theme (contrast) or 320 px wide. Minor and moderate ones are in the report."""
    failures = []
    for name, checks in audit.items():
        for mode in ("light", "dark", "320px"):
            for v in checks[f"axe {mode}"]:
                if v["impact"] in FAILING_IMPACTS:
                    targets = "; ".join(n["target"] for n in v["nodes"][:5])
                    failures.append(
                        f"{name} ({mode}): {v['id']} [{v['impact']}] {v['help']}: {targets}"
                    )
    assert not failures, "\n".join(failures)


def test_no_axe_violations_at_all(audit):
    """Not even minor or moderate ones (the issue's acceptance criterion)."""
    found = sorted(
        {f"{name}: {v['id']} [{v['impact']}]" for name, checks in audit.items()
         for mode in ("light", "dark", "320px") for v in checks[f"axe {mode}"]}
    )  # fmt: skip
    assert not found, "\n".join(found)


def test_reflow_at_320px_and_200_percent_zoom(audit):
    """No horizontal scrolling at 320 CSS px (WCAG 1.4.10, the same as 400% zoom of a
    1280 px window) nor at 200% zoom (1.4.4); wide tables and maps scroll inside their own
    region."""
    failures = [
        f"{name} ({mode}): {r['scroll']} px wide in {r['width']} px: {r['wide']}"
        for name, checks in audit.items()
        for mode in ("320px", "200% zoom")
        if (r := checks[f"reflow {mode}"])["scroll"] > r["width"] + 1
    ]
    assert not failures, "\n".join(failures)


def test_keyboard_every_page(audit):
    """Tab reaches the skip link first, then every control in turn, each visible with a
    focus indicator (also in forced colours), and comes back round: no trap (WCAG 2.1.1,
    2.1.2, 2.4.3, 2.4.7); the skip link moves focus to the main content (2.4.1); no
    positive tabindex."""
    failures = []
    for name, checks in audit.items():
        if checks["positive tabindex"]:
            failures.append(f"{name}: an element has a positive tabindex")
        for suffix, label in (("", name), (" forced", f"{name} (forced colours)")):
            if checks[f"tab problem{suffix}"]:
                failures.append(f"{label}: {checks[f'tab problem{suffix}']}")
            for stop in checks[f"tab stops{suffix}"]:
                if not stop["visible"]:
                    failures.append(
                        f"{label}: focus on something not visible: {stop['key']} {stop['text']!r}"
                    )
                elif not stop["indicator"]:
                    failures.append(
                        f"{label}: no focus indicator on {stop['key']} {stop['text']!r}"
                    )
        if checks["skip link"] is None:
            if name != "server error":  # the one page without the page shell
                failures.append(f"{name}: no skip link")
        elif not checks["tab stops"] or not checks["tab stops"][0]["skip"]:
            failures.append(f"{name}: the first Tab stop is not the skip link")
        elif not checks["skip link"]:
            failures.append(f"{name}: the skip link does not move focus to the main content")
    assert not failures, "\n".join(failures)


def test_reduced_motion_every_page(audit):
    """With prefers-reduced-motion, nothing animates or transitions for longer than 0.1 s
    and scrolling is not smooth (WCAG 2.3.3)."""
    failures = []
    for name, checks in audit.items():
        if checks["motion"]["moving"]:
            failures.append(f"{name}: moves with reduced motion: {checks['motion']['moving']}")
        if checks["motion"]["smooth"] == "smooth":
            failures.append(f"{name}: smooth scrolling with reduced motion")
    assert not failures, "\n".join(failures)


def test_structure_every_page(audit):
    """Every page has a language, a title, one main landmark, one h1, a working skip
    link target and names on its regions, groups, toolbars and navigation (WCAG 1.3.1,
    2.4.1, 2.4.2, 3.1.1, 4.1.2)."""
    failures = []
    for name, checks in audit.items():
        s = checks["structure"]
        problems = [
            "no lang" if not s["lang"] else "",
            "no title" if not s["title"] else "",
            f"{s['mains']} main landmarks" if s["mains"] != 1 else "",
            f"{s['h1']} h1 headings" if s["h1"] != 1 else "",
            "the skip link's target is missing" if not s["skipTarget"] else "",
            f"unnamed: {s['unnamed']}" if s["unnamed"] else "",
        ]
        failures += [f"{name}: {p}" for p in problems if p]
    assert not failures, "\n".join(failures)


# ---- Progress while a job runs -------------------------------------------------------------


def test_progress_pages_while_running(site):
    """The progress pages pass axe while their job runs; the stages are announced through
    the page's announcer (a live region that stays, as the polled fragment replaces
    itself), the batch's end too; and keyboard focus on the cancel button survives the
    polls (WCAG 4.1.3, 2.4.3)."""
    failures = []
    for name, seen in WHILE_RUNNING.items():
        for v in seen["axe"]:
            failures.append(f"{name} (running): {v['id']} [{v['impact']}] {v['help']}")
    for name in ("station run", "batch", "gridded run"):
        if not WHILE_RUNNING[name]["heard"]:
            failures.append(f"{name}: nothing was announced while it ran")
    batch = WHILE_RUNNING["batch"]
    if not any("calculated" in said for said in batch["heard"]):
        failures.append(f"batch: its end was not announced: {batch['heard']}")
    focus = batch["focus"]
    if focus["swapped"] and focus["running"] and not focus["kept"]:
        failures.append("batch: focus on the cancel button was lost when the progress updated")
    assert not failures, "\n".join(failures)


# ---- Widgets by keyboard -------------------------------------------------------------------


def focus(c: Chrome, selector: str) -> None:
    c.evaluate(f"document.querySelector({json.dumps(selector)}).focus()")


def active(c: Chrome, expression: str = "document.activeElement"):
    return c.evaluate(
        f"(function (el) {{ return el && (el.id || el.textContent.trim()) }})({expression})"
    )


def test_tabs_by_keyboard(chrome, site):
    """The tabs component: arrow keys, Home and End move between tabs and show the panel."""
    c = chrome
    c.navigate(site["pattern library"])
    tabs = c.evaluate(
        "Array.prototype.map.call(document.querySelectorAll('[role=tablist]')[0]"
        ".querySelectorAll('[role=tab]'), function (t) { return t.id })"
    )
    assert len(tabs) >= 3
    focus(c, f"#{tabs[0]}")
    state = (
        "(function () { var t = document.activeElement;"
        " var panel = document.getElementById(t.getAttribute('aria-controls'));"
        " return [t.id, t.getAttribute('aria-selected'), t.tabIndex, !panel.hidden] })()"
    )
    c.press("ArrowRight")
    assert c.evaluate(state) == [tabs[1], "true", 0, True]
    c.press("End")
    assert c.evaluate(state) == [tabs[-1], "true", 0, True]
    c.press("Home")
    assert c.evaluate(state) == [tabs[0], "true", 0, True]
    c.press("ArrowLeft")
    assert c.evaluate(state)[0] == tabs[-1]  # wraps round
    # Only the selected tab is a Tab stop; Tab goes on into its panel.
    assert (
        c.evaluate(
            "Array.prototype.filter.call(document.querySelectorAll('[role=tablist]')[0]"
            ".querySelectorAll('[role=tab]'), function (t) { return t.tabIndex === 0 }).length"
        )
        == 1
    )


def test_workspace_tabs_by_keyboard(chrome, site):
    """The workspace tabs (#179): links in a named navigation, one Tab stop each in order,
    each named with its status in words (Quality's with the verdict, #222); the current one
    is aria-current="page", and Enter opens a section. A tab not available yet is not a Tab
    stop."""
    c = chrome
    c.navigate(site["station results, out of date"])
    tabs = (
        "Array.prototype.map.call(document.querySelectorAll('nav[aria-label=\"Station"
        " sections\"] [data-tab]'), function (t) { var n = t.cloneNode(true);"
        " n.querySelectorAll('[aria-hidden=true]').forEach(function (h) { h.remove() });"
        " return [t.dataset.tab, t.tagName, n.textContent.replace(/\\s+/g, ' ').trim(),"
        " t.getAttribute('aria-current')] })"
    )  # each tab's name as read: what is aria-hidden (the icon, the count) left out
    found = c.evaluate(tabs)
    assert [t[0] for t in found] == ["quality", "results", "files"]
    assert all(t[1] == "A" for t in found)
    assert found[1][2] == "Indices Out of date" and found[1][3] == "page"
    # Quality's is its verdict (#222): the Sydney sample's is amber, 5 values look wrong.
    assert found[0][2] == "Quality Usable, 5 values look wrong"
    assert found[2][2] == "Files Out of date"
    focus(c, "[data-tab=quality]")
    for key in ("results", "files"):
        c.press("Tab")
        assert c.evaluate("document.activeElement.dataset.tab") == key
    c.press("Tab", shift=True)
    c.press("Tab", shift=True)
    assert c.evaluate("document.activeElement.dataset.tab") == "quality"
    c.press("Enter")
    c.settle(0.5)
    assert here(c).split("#")[0].endswith("/quality")
    assert c.evaluate("document.querySelector('[aria-current=page][data-tab]').dataset.tab") == (
        "quality"
    )
    # The first visit (the pattern library's example): only Quality is a link.
    c.navigate(site["pattern library"])
    first = "nav[aria-label='Example: the first visit']"
    assert c.evaluate(
        f"Array.prototype.map.call(document.querySelectorAll({json.dumps(first + ' [data-tab]')}),"
        " function (t) { return t.tagName + ':' + t.tabIndex })"
    ) == ["A:0", "SPAN:-1", "SPAN:-1"]


def test_dialog_by_keyboard(chrome, site):
    """The dialog opens from the keyboard with focus inside, keeps focus inside, closes
    with Escape and gives focus back to the button that opened it."""
    c = chrome
    c.navigate(site["pattern library"])
    opener = "[data-dialog-open]"
    focus(c, opener)
    c.press("Enter")
    time.sleep(0.1)
    inside = "document.querySelector('dialog[open]') && document.querySelector('dialog[open]')" \
        ".contains(document.activeElement)"  # fmt: skip
    assert c.evaluate(inside), "focus did not move into the dialog"
    for _ in range(8):
        c.press("Tab")
        assert c.evaluate(inside) or c.evaluate("document.activeElement === document.body"), \
            "Tab left the open dialog"  # fmt: skip
    c.press("Escape")
    time.sleep(0.1)
    assert not c.evaluate("!!document.querySelector('dialog[open]')")
    assert c.evaluate(f"document.activeElement === document.querySelector('{opener}')")


def test_input_sheet_by_keyboard(chrome, site):
    """#198: Tab reaches the Inputs panel's Edit, Enter opens its sheet, a modal dialog
    with focus on the form's first field; Tab stays inside it; Escape closes it, discards
    what was typed and gives focus back to the Edit. No axe violation with the sheet
    open, in light and dark and at 320 px, where it fills the width without scrolling
    the page sideways."""
    c = chrome
    c.viewport(1280, 900)
    try:
        # The panel is beside Files; the Indices and Quality have "Edit inputs" (#263, #264).
        c.navigate(site["station downloads"])
        edit = "[data-sheet-open='sheet-base-period']"
        c.evaluate("document.activeElement.blur(); window.scrollTo(0, 0)")
        for _ in range(80):
            c.press("Tab")
            if c.evaluate(f"document.activeElement.matches({json.dumps(edit)})"):
                break
        else:
            raise AssertionError("Tab never reached the base period's Edit")
        start = c.evaluate("document.querySelector('[name=base_start]').value")
        c.press("Enter")
        time.sleep(0.1)
        sheet = "document.getElementById('sheet-base-period')"
        assert c.evaluate(f"{sheet}.open && {sheet}.matches(':modal')")
        assert c.evaluate("document.activeElement.name") == "base_start"
        c.evaluate("document.activeElement.value = '1990'")
        inside = f"{sheet}.contains(document.activeElement)"
        for _ in range(10):
            c.press("Tab")
            assert c.evaluate(inside) or c.evaluate("document.activeElement === document.body"), \
                "Tab left the open sheet"  # fmt: skip
        failures = [f"light: {v['id']}" for v in run_axe(c)]
        c.media(prefers_color_scheme="dark")
        c.transitions_done()
        failures += [f"dark: {v['id']}" for v in run_axe(c, ["color-contrast"])]
        c.media(prefers_color_scheme="light")
        c.viewport(320, 700)
        c.settle(0.1)
        failures += [f"320px: {v['id']}" for v in run_axe(c)]
        assert not failures, failures
        assert c.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert c.evaluate(f"{sheet}.getBoundingClientRect().width") <= 321
        c.viewport(1280, 900)
        c.press("Escape")
        time.sleep(0.1)
        assert not c.evaluate(f"{sheet}.open")
        assert c.evaluate(f"document.activeElement.matches({json.dumps(edit)})")
        assert c.evaluate("document.querySelector('[name=base_start]').value") == start
        # Cancel closes it too; nothing was applied.
        c.evaluate(f"document.querySelector({json.dumps(edit)}).click()")
        c.evaluate(f"{sheet}.querySelector('button[data-sheet-close]:not(.button--icon)').click()")
        assert not c.evaluate(f"{sheet}.open")
        assert c.evaluate("location.pathname").endswith("/downloads")
    finally:
        c.media(prefers_color_scheme="light")
        c.viewport(1280, 900)


STATION_PAGES = (
    "station sample loaded",
    "station quality results",
    "station results",
    "station index",
    "station downloads",
    "station sector results",
)


def test_help_drawer_by_keyboard(chrome, site):
    """#177: Tab to a section's ⓘ, Enter opens the drawer beside the content with focus
    on its title, the page stays usable (no trap: Tab goes on past the drawer), Escape
    closes it and focus returns to the ⓘ. On a phone the drawer is below the content."""
    c = chrome
    c.viewport(1280, 800)
    try:
        c.navigate(site["station sample loaded"])
        button = "[data-drawer-open^='help-load-details']"
        assert c.evaluate("document.querySelector('[data-help-link]').hidden")
        c.evaluate("document.activeElement.blur(); window.scrollTo(0, 0)")
        for _ in range(60):
            c.press("Tab")
            if c.evaluate(f"document.activeElement.matches({json.dumps(button)})"):
                break
        else:
            raise AssertionError("Tab never reached the Station details ⓘ")
        c.press("Enter")
        time.sleep(0.1)
        drawer = "document.getElementById('help-drawer')"
        assert c.evaluate(f"!{drawer}.hidden")
        assert c.evaluate("document.activeElement.id") == "help-drawer-title"
        assert c.evaluate("document.activeElement.textContent") == "Help: Station details"
        assert c.evaluate(f"document.querySelector({json.dumps(button)}).ariaExpanded") == "true"
        topic = json.dumps('[data-help-topic="station.latitude"]')
        assert c.evaluate(f"{drawer}.querySelector({topic}) !== null")
        # Beside the content, not over it, and no backdrop or modal dialog.
        assert c.evaluate(
            f"{drawer}.getBoundingClientRect().left"
            " >= document.querySelector('main').getBoundingClientRect().right - 1"
        )
        assert not c.evaluate("!!document.querySelector('dialog[open]')")
        # Not a trap: Tab leaves the drawer after its controls.
        for _ in range(6):
            c.press("Tab")
        assert not c.evaluate(f"{drawer}.contains(document.activeElement)")
        c.evaluate(f"{drawer}.querySelector('[data-drawer-close]').focus()")
        c.press("Escape")
        time.sleep(0.1)
        assert c.evaluate(f"{drawer}.hidden")
        assert c.evaluate(f"document.activeElement.matches({json.dumps(button)})")
        assert c.evaluate(f"document.querySelector({json.dumps(button)}).ariaExpanded") == "false"
        # On a phone the drawer comes after the content.
        c.viewport(320, 800)
        c.evaluate(f"document.querySelector({json.dumps(button)}).click()")
        time.sleep(0.1)
        assert c.evaluate(
            f"{drawer}.getBoundingClientRect().top"
            " >= document.querySelector('main').getBoundingClientRect().bottom - 1"
        )
        assert c.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        c.press("Escape")
    finally:
        c.viewport(1280, 900)


# What of the sticky workspace header is in the window: from its top, or from the top of
# the window where it sticks above it (on a phone only the tabs and the Inputs bar stay).
SHOWN_HEADER = (
    "(function () { var b = document.querySelector('[data-context-bar]')"
    ".getBoundingClientRect(); return {top: Math.max(b.top, 0), bottom: b.bottom}; })()"
)


def test_sticky_context_bar_never_covers_focus(chrome, site):
    """#197, #227: the context bar (name, tabs, actions) stays at the top as the page
    scrolls, and Tab never leaves the focused element under it (WCAG 2.4.11): the page's
    scroll padding is the header's height. On a phone (#203) only the tabs and the Inputs
    bar stay: the name scrolls away, and the padding is what stays."""
    c = chrome
    header = "document.querySelector('[data-context-bar]')"
    tabs = f"{header}.querySelector('nav')"
    try:
        for width in (1280, 320):
            c.viewport(width, 700)
            for name in ("station results", "station quality results"):
                c.navigate(site[name])
                c.evaluate("document.activeElement.blur(); window.scrollTo(0, 0)")
                assert c.evaluate(f"getComputedStyle({header}).position") == "sticky", name
                furthest = 0  # Tab may come back round to the top before the 80th press
                for _ in range(80):
                    c.press("Tab")
                    time.sleep(0.02)
                    furthest = max(furthest, c.evaluate("window.scrollY"))
                    hidden = c.evaluate(
                        f"(function () {{ var h = {header}, a = document.activeElement;"
                        " if (!a || h.contains(a) || a === document.body) return false;"
                        " if (a.closest('dialog')) return false;"
                        f" var r = a.getBoundingClientRect(), b = {SHOWN_HEADER};"
                        " if (r.height === 0) return false;"
                        # Taller than the window under the header (the Indices' table,
                        # #236): enough that part of it shows.
                        " if (r.height > innerHeight - b.bottom) return r.bottom <= b.bottom;"
                        " return r.top < b.bottom - 1 && r.bottom > b.top; })()"
                    )
                    assert not hidden, (
                        name,
                        width,
                        c.evaluate("document.activeElement.outerHTML.slice(0, 120)"),
                    )
                assert furthest > 300, (name, width)  # the page scrolled under it
                c.evaluate("window.scrollTo(0, 1200)")
                time.sleep(0.05)
                if width == 1280:
                    assert abs(c.evaluate(f"{header}.getBoundingClientRect().top")) <= 1, name
                else:
                    # The tabs at the top, the Inputs bar under them, the name gone.
                    assert abs(c.evaluate(f"{tabs}.getBoundingClientRect().top")) <= 1, name
                    bar = c.evaluate(
                        "document.querySelector('[data-inputs-bar]').getBoundingClientRect().top"
                    )
                    assert 30 < bar < 80, (name, bar)
        c.viewport(640, 440)  # a short window: it scrolls away with the page
        assert c.evaluate(f"getComputedStyle({header}).position") == "static"
    finally:
        c.viewport(1280, 900)


# Elements that stay in the window as the page scrolls (sticky or fixed), and are shown.
STUCK = """(function () {
  var out = [];
  document.querySelectorAll('body *').forEach(function (el) {
    var p = getComputedStyle(el).position;
    if ((p !== 'sticky' && p !== 'fixed') || !el.checkVisibility()) return;
    if (el.closest('dialog:not([open])')) return;
    // Only what sticks to the window: one inside a scrolling box (a table's header row
    // in its region) moves with the page; overflow: clip makes no scrolling box (the page
    // clips the context bar's edges, #227). Nor what is visually hidden (clipped).
    for (var a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      var st = getComputedStyle(a);
      if (/auto|scroll|hidden/.test(st.overflowX + ' ' + st.overflowY)) return;
      if (st.clipPath !== 'none') return;
    }
    var r = el.getBoundingClientRect();
    if (r.width && r.height) out.push(el);
  });
  return out;
})()"""


def test_no_overlapping_sticky_elements_on_phones(chrome, site):
    """#203: at 320 and 375 px, as each station page scrolls, no element that stays in
    view (sticky or fixed) covers another, apart from one inside the other; and the page
    never scrolls sideways."""
    c = chrome
    check = (
        f"(function () {{ var els = {STUCK}, bad = [];"
        " els.forEach(function (a, i) { els.slice(i + 1).forEach(function (b) {"
        "  if (a.contains(b) || b.contains(a)) return;"
        "  var r = a.getBoundingClientRect(), s = b.getBoundingClientRect();"
        "  var top = Math.max(r.top, 0), stop = Math.max(s.top, 0);"
        "  if (r.left < s.right - 1 && s.left < r.right - 1 && top < s.bottom - 1"
        "   && stop < r.bottom - 1)"
        "   bad.push(a.tagName + '.' + a.className + ' / ' + b.tagName + '.' + b.className"
        "    + ' ' + (b.parentElement || {}).className); }); });"
        " return bad; })()"
    )
    try:
        for width in (320, 375):
            c.viewport(width, 700)
            # An index's page has nothing sticky (#237); the reflow test covers it.
            for name in ("station quality results", "station results",
                         "station downloads", "station sector results"):  # fmt: skip
                c.navigate(site[name])
                height = c.evaluate("document.documentElement.scrollHeight")
                for y in range(0, height, 350):
                    c.evaluate(f"window.scrollTo(0, {y})")
                    time.sleep(0.03)
                    assert c.evaluate(check) == [], (name, width, y)
                # Not vacuous: the workspace header was among them.
                assert c.evaluate(
                    f"{STUCK}.some(function (e) {{ return e.matches('[data-context-bar]') }})"
                ), name
                assert c.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                    name,
                    width,
                )
    finally:
        c.viewport(1280, 900)


def test_phone_inputs_bar_opens_the_sheets(chrome, site):
    """#203: on a phone the Inputs panel is one line under the tabs, the base period and
    whether the settings are the defaults. Its Edit (Enter) opens the inputs in a sheet
    that fills the screen; an input's Edit there opens that input's sheet over it; Escape
    goes back to the list, with focus on that Edit, then to the page, with focus on the
    bar's Edit. No axe violation with either sheet open. At 1280 px the panel is back
    beside Files and the bar is gone; on the Indices and Quality "Edit inputs" on the
    provenance line takes the bar's place (#263, #264) and opens the same sheet, focus
    returning to it."""
    c = chrome
    bar = "document.querySelector('[data-inputs-bar]')"
    panel = "document.querySelector('[data-inputs-panel]')"
    edit = "[data-inputs-bar] button[data-sheet-open='sheet-inputs']"
    listed = "#sheet-inputs [data-sheet-open='sheet-base-period']"
    try:
        c.viewport(375, 812)
        c.navigate(site["station results"])
        assert c.evaluate(f"{bar}.checkVisibility()")
        assert not c.evaluate(f"{panel}.checkVisibility()")
        assert c.evaluate(f"{bar}.textContent").split()[:3] == ["Inputs:", "1971–2000", "·"]
        # The site's results use one setting of their own (rx_days).
        assert "1 setting not the default" in c.evaluate(f"{bar}.textContent")
        c.evaluate(f"document.querySelector({json.dumps(edit)}).focus()")
        c.press("Enter")
        time.sleep(0.1)
        inputs = "document.getElementById('sheet-inputs')"
        assert c.evaluate(f"{inputs}.open && {inputs}.matches(':modal')")
        assert c.evaluate(f"{inputs}.contains(document.activeElement)")
        assert c.evaluate(f"{inputs}.getBoundingClientRect().width") == 375
        failures = [f"inputs: {v['id']}" for v in run_axe(c)]
        c.evaluate(f"document.querySelector({json.dumps(listed)}).focus()")
        c.press("Enter")
        time.sleep(0.1)
        sheet = "document.getElementById('sheet-base-period')"
        assert c.evaluate(f"{sheet}.open && {inputs}.open")
        assert c.evaluate("document.activeElement.name") == "base_start"
        assert c.evaluate(f"{sheet}.getBoundingClientRect().width") == 375
        failures += [f"base period: {v['id']}" for v in run_axe(c)]
        c.viewport(320, 700)
        c.settle(0.1)
        failures += [f"320px: {v['id']}" for v in run_axe(c)]
        assert not failures, failures
        c.viewport(375, 812)
        c.press("Escape")
        time.sleep(0.1)
        assert not c.evaluate(f"{sheet}.open") and c.evaluate(f"{inputs}.open")
        assert c.evaluate(f"document.activeElement.matches({json.dumps(listed)})")
        c.press("Escape")
        time.sleep(0.1)
        assert not c.evaluate(f"{inputs}.open")
        assert c.evaluate(f"document.activeElement.matches({json.dumps(edit)})")
        c.viewport(1280, 900)
        c.settle(0.1)
        assert not c.evaluate(f"{bar}.checkVisibility()")
        assert not c.evaluate(f"{panel}.checkVisibility()")
        line_edit = ".context-bar__provenance a[data-sheet-open='sheet-inputs']"
        assert c.evaluate(f"document.querySelector({json.dumps(line_edit)}).checkVisibility()")
        c.evaluate(f"document.querySelector({json.dumps(line_edit)}).focus()")
        c.press("Enter")
        time.sleep(0.1)
        assert c.evaluate(f"{inputs}.open && {inputs}.contains(document.activeElement)")
        c.press("Escape")
        time.sleep(0.1)
        assert not c.evaluate(f"{inputs}.open")
        assert c.evaluate(f"document.activeElement.matches({json.dumps(line_edit)})")
        c.viewport(375, 812)
        c.settle(0.1)
        assert not c.evaluate(f"document.querySelector({json.dumps(line_edit)}).checkVisibility()")
        c.viewport(1280, 900)
        c.navigate(site["station quality results"])
        assert not c.evaluate(f"{bar}.checkVisibility()")
        assert not c.evaluate(f"{panel}.checkVisibility()")
        assert c.evaluate(f"document.querySelector({json.dumps(line_edit)}).checkVisibility()")
        c.navigate(site["station downloads"])
        assert not c.evaluate(f"{bar}.checkVisibility()")
        assert c.evaluate(f"{panel}.checkVisibility()")
    finally:
        c.viewport(1280, 900)


def test_page_menu_by_keyboard(chrome, site):
    """#203: on a phone Results' actions are in the header's ⋯ menu, a disclosure: Enter
    opens it, Tab reaches each action, Escape closes it and gives focus back to its
    button, and a click elsewhere closes it. The name and the menu share one line. At
    1280 px the actions are buttons in the header and the menu is gone."""
    c = chrome
    menu = "document.querySelector('[data-page-menu]')"
    button = "[data-page-menu] > summary"
    try:
        c.viewport(375, 812)
        c.navigate(site["station results"])
        assert not c.evaluate("document.querySelector('.context-bar__actions')"
                              ".checkVisibility()")  # fmt: skip
        middle = "(function (r) {{ return r.top + r.height / 2 }})({}.getBoundingClientRect())"
        name = c.evaluate(middle.format("document.querySelector('.context-bar__name')"))
        dots = c.evaluate(middle.format(f"document.querySelector({json.dumps(button)})"))
        assert c.evaluate(
            "document.querySelector('.context-bar__name').getBoundingClientRect().right"
        ) <= c.evaluate(
            f"document.querySelector({json.dumps(button)}).getBoundingClientRect().left"
        )
        assert abs(name - dots) < 30, (name, dots)
        assert c.evaluate(f"document.querySelector({json.dumps(button)}).textContent.trim()") \
            == "Page actions"  # fmt: skip
        c.evaluate(f"document.querySelector({json.dumps(button)}).focus()")
        c.press("Enter")
        assert c.evaluate(f"{menu}.open") is True
        assert c.evaluate(f"document.querySelector({json.dumps(button)}).ariaExpanded"
                          " !== 'false'")  # fmt: skip
        assert run_axe(c) == []
        reached = []
        for _ in range(2):
            c.press("Tab")
            reached.append(c.evaluate("document.activeElement.textContent.trim()"))
        assert reached[0] == "Compare with sector data", reached
        assert reached[1].startswith("Download all"), reached
        c.press("Escape")
        assert c.evaluate(f"{menu}.open") is False
        assert c.evaluate(f"document.activeElement.matches({json.dumps(button)})")
        c.press("Enter")
        assert c.evaluate(f"{menu}.open") is True
        c.evaluate("document.querySelector('main h2, main p').click()")
        assert c.evaluate(f"{menu}.open") is False
        c.viewport(1280, 900)
        assert not c.evaluate(f"{menu}.checkVisibility()")
        assert c.evaluate("document.querySelector('.context-bar__actions')"
                          ".checkVisibility()")  # fmt: skip
    finally:
        c.viewport(1280, 900)


def test_help_reachable_from_every_section_of_the_station_pages(chrome, site):
    """#177: every ⓘ on every station page opens the drawer with its section's help."""
    c = chrome
    for name in STATION_PAGES:
        open_page(c, site[name])
        count = c.evaluate("document.querySelectorAll('[data-drawer-open]').length")
        assert count, f"{name}: no section help"
        for i in range(count):
            title = c.evaluate(
                f"(function () {{ var b = document.querySelectorAll('[data-drawer-open]')[{i}];"
                " b.scrollIntoView(); b.click();"
                " var d = document.getElementById('help-drawer');"
                " return !d.hidden && d.querySelector('.drawer__content') !== null"
                " ? document.getElementById('help-drawer-title').textContent : null; })()"
            )
            assert title and title.startswith("Help: "), (name, i)
            c.press("Escape")
            assert c.evaluate("document.getElementById('help-drawer').hidden"), (name, i)


def test_drop_zone_by_keyboard(chrome, site):
    """Add stations' file input (#233) is a Tab stop, shows its focus on its button, and
    Space or Enter opens the file chooser."""
    c = chrome
    c.navigate(site["add stations"])
    c.evaluate(START)
    for _ in range(40):
        c.press("Tab")
        if c.evaluate("document.activeElement.type === 'file'"):
            break
    else:
        raise AssertionError("Tab never reached the file input")
    ring = c.evaluate("getComputedStyle(document.activeElement.closest('label')).outlineStyle")
    assert ring != "none", "the file button shows no focus"
    c.send("Page.setInterceptFileChooserDialog", enabled=True)
    try:
        c.events.clear()
        c.press(" ")
        c.wait_event("Page.fileChooserOpened", timeout=5)
    finally:
        c.send("Page.setInterceptFileChooserDialog", enabled=False)


# The focused element's name ("name" for "name-0") or, for a button, its intent.
NAME_OF_FOCUSED = (
    "(function (e) { return e.name === 'intent' ? e.value"
    " : (e.name || '').replace(/-\\d+$/, '') })(document.activeElement)"
)
CHANGED = "document.activeElement.dispatchEvent(new Event('change', {bubbles: true}))"


def test_add_stations_by_keyboard(chrome, site, server):
    """#233: Add stations' review in Tab order (the files, the sample, then each row's
    name, latitude and longitude, then Cancel and Add); a chosen file is sent at once; the
    table is checked as it is typed (the button's count and the row's Read column change);
    Enter in a cell moves down a row; no axe violation in light, dark and at 320 px; Enter
    on the Add button lands on the station's Quality. The details' errors on a station's
    own setup page take focus to their summary."""
    c = chrome
    open_page(c, site["station details, errors"])
    assert c.evaluate("document.activeElement.hasAttribute('data-error-summary')")
    c.navigate(urljoin(server, "/add/"))
    assert c.evaluate("document.querySelector('[data-nojs]').hidden")  # sent on choosing
    choose_file(c, "[data-add-files]", "keyboard_hill_2000-2001.txt", GOOD_FILE)
    assert "/add/" in c.evaluate("location.pathname")
    button = "document.querySelector('[data-add-button]')"
    assert c.evaluate(f"{button}.textContent") == "Add 0 stations and check them"
    c.evaluate(START)
    order = []
    for _ in range(40):
        c.press("Tab")
        el = c.evaluate(NAME_OF_FOCUSED)
        if el in ("files", "sample", "name", "lat", "lon", "cancel", "add"):
            order.append(el)
        if el == "add":
            break
    assert order == ["files", "sample", "name", "lat", "lon", "cancel", "add"]
    for cell, value in (("latitude", "-35.3"), ("longitude", "149.1")):
        focus(c, f"[data-cell={cell}]")
        c.evaluate(f"document.activeElement.value = '{value}'; {CHANGED}")
    wait_for(c, f"{button}.textContent === 'Add 1 station and check it'",
             what="the table checked as it is typed")  # fmt: skip
    assert c.evaluate("document.querySelector('[data-status]').textContent").startswith("Read")
    try:
        for scheme, width in (("light", 1280), ("dark", 1280), ("light", 320)):
            c.media(prefers_color_scheme=scheme)
            c.viewport(width, 900)
            c.transitions_done()  # colour transitions run to their end
            assert run_axe(c) == [], (scheme, width)
            assert c.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        c.media(prefers_color_scheme="light")
        c.viewport(1280, 900)
    focus(c, "[data-add-button]")
    c.events.clear()
    c.press("Enter")
    c.wait_event("Page.loadEventFired", timeout=60)
    c.settle()
    assert c.evaluate("location.pathname").endswith("/quality")
    assert "Keyboard Hill" in c.evaluate("document.querySelector('h1').textContent")


def test_chart_by_keyboard(chrome, site):
    """An interactive chart's plot is a Tab stop; + zooms in, arrows move, 0 resets, and
    each change is announced in the chart's status (Quality's daily charts; an index's
    page draws its chart on the server since #237)."""
    c = chrome
    c.navigate(site["station quality results"])
    c.evaluate("document.getElementById('daily').open = true")
    chart = "#" + c.evaluate("document.querySelector('.qc-charts [data-chart]').id")
    c.evaluate(f"document.querySelector('{chart}').scrollIntoView()")  # drawn when in view
    wait_for(c, f"!!document.querySelector('{chart} [data-chart-plot] canvas')", timeout=60,
             what="the chart")  # fmt: skip
    focus(c, f"{chart} [data-chart-plot]")
    status = f"document.querySelector('{chart} [data-chart-status]').textContent"
    c.press("+")
    wait_for(c, f"!!{status}", timeout=5, what="zooming in to be announced")
    zoomed = c.evaluate(status)
    c.press("ArrowLeft")
    wait_for(c, f"{status} !== {json.dumps(zoomed)}", timeout=5, what="moving to be announced")
    moved = c.evaluate(status)
    c.press("0")
    wait_for(c, f"{status} !== {json.dumps(moved)}", timeout=5, what="the reset to be announced")
    assert c.evaluate("document.activeElement.hasAttribute('data-chart-plot')")


def test_index_page_views_and_citation(chrome, site):
    """#237: on an index's page the Values / Anomaly links switch the chart in place: the
    other chart shows, the link is marked current, the address keeps ?view= and the
    Annual / Monthly links keep it. With JavaScript, "Copy citation" is a button in place
    of the disclosure. No axe violation in either view, in both themes."""
    c = chrome
    c.navigate(site["station index"])
    shown = (
        "[...document.querySelectorAll('[data-index-view]')]"
        ".filter(s => !s.hasAttribute('hidden')).map(s => s.dataset.indexView)"
    )
    assert c.evaluate(shown) == ["values"]
    focus(c, "[data-index-view-link='anomaly']")
    c.press("Enter")
    time.sleep(0.1)
    assert c.evaluate(shown) == ["anomaly"]
    assert c.evaluate("document.activeElement.getAttribute('aria-current')") == "true"
    assert c.evaluate("location.search") == "?view=anomaly"
    assert "view=anomaly" in c.evaluate("document.querySelector('[data-index-period]').href")
    for scheme in ("light", "dark"):
        set_mode(c, scheme=scheme)
        c.transitions_done()
        assert run_axe(c) == [], scheme
    set_mode(c)
    copy = "document.querySelector('.context-bar__actions [data-citation-copy]')"
    assert c.evaluate(f"!{copy}.hidden")
    assert c.evaluate("document.querySelector('.context-bar__actions .citation__details').hidden")
    assert c.evaluate("document.querySelector('[data-citation-text]').textContent").startswith(
        "Sydney Observatory Hill, TXx (Hottest day), 1936–2015"  # the sample's name (#219)
    )


def test_tour_by_keyboard(chrome, site):
    """The landing page's tour starts from the keyboard, takes focus, moves on with its
    buttons and closes with Escape, giving focus back."""
    c = chrome
    c.navigate(site["landing"])
    c.evaluate("try { localStorage.clear() } catch (e) {}")
    c.navigate(site["landing"])
    wait_for(c, "!document.querySelector('[data-tour-invite]').hidden", timeout=5,
             what="the tour invitation")  # fmt: skip
    focus(c, "[data-tour-start]")
    c.press("Enter")
    time.sleep(0.2)
    in_tour = "!!document.activeElement.closest('.tour')"
    assert c.evaluate(in_tour), "focus did not move to the tour"
    c.press("Escape")
    time.sleep(0.2)
    assert not c.evaluate(in_tour)
    assert c.evaluate("document.activeElement !== document.body"), "focus was dropped"


def test_help_search_announces_results(chrome, site):
    """Typing in the help search updates the results in place and announces their count."""
    c = chrome
    c.navigate(site["help"])
    focus(c, "#help-q")
    c.send("Input.insertText", text="outliers")
    wait_for(c, "/result/.test(document.getElementById('announcer').textContent)", timeout=10,
             what="the announcement of the results")  # fmt: skip
    assert c.evaluate("document.activeElement.id") == "help-q", "typing lost focus"


def test_gridded_explorer_keeps_focus(chrome, site):
    """Changing a select of the gridded explorer swaps the map in place; focus stays on
    the select, so a keyboard user can go on choosing."""
    c = chrome
    c.navigate(site["gridded results"])
    focus(c, "#explore-t")
    c.evaluate(
        "var s = document.getElementById('explore-t'); s.selectedIndex = 0;"
        " s.dispatchEvent(new Event('change', {bubbles: true}))"
    )
    wait_for(c, "document.getElementById('explore-t').selectedIndex === 0 &&"
             " !document.querySelector('.htmx-request')", timeout=10)  # fmt: skip
    assert c.evaluate("document.activeElement.id") == "explore-t"


def test_results_catalogue_filters_and_sorts_by_keyboard(chrome, site):
    """The Indices' table (#200, #236): filtered as you type by the rail's search, a theme
    and "Significant only", and sorted by its column headers, which are buttons here
    (links without JavaScript): Enter sorts, again reverses, aria-sort moves to the sorted
    column, and the live line says how many rows show and how they are sorted. The order is
    the server's, and the state is kept in the address. It opens sorted by the size of the
    trend (#263), which no column has and the address leaves out."""
    c = chrome
    rows = "[...document.querySelectorAll('[data-results-table] tbody tr')]"
    shown = rows + ".filter(function (r) { return !r.hidden })"
    keys = shown + ".map(function (r) { return r.id.slice(6) })"
    said = "document.getElementById('results-count').textContent.trim()"
    sorted_by = (
        "[...document.querySelectorAll('[data-results-table] th[aria-sort]')]"
        ".map(function (th) { return th.dataset.sortKey + ' ' + th.getAttribute('aria-sort') })"
    )
    c.navigate(site["station results"] + "?sort=name&dir=ascending")
    by_name = c.evaluate(keys)  # the server's order
    c.navigate(site["station results"])
    assert c.evaluate(f"{shown}.length") == 80 and c.evaluate(sorted_by) == []
    sizes = c.evaluate(
        shown + ".filter(function (r) { return r.dataset.trend !== '' })"
        ".map(function (r) { return Math.abs(Number(r.dataset.trend)) })"
    )
    assert sizes == sorted(sizes, reverse=True) and len(sizes) > 60
    assert c.evaluate("document.getElementById('results-count').getAttribute('aria-live')") == (
        "polite"
    )
    assert c.evaluate("document.querySelectorAll('thead button.sort').length") == 4
    assert c.evaluate("document.querySelectorAll('thead a.sort').length") == 0
    assert c.evaluate("document.querySelector('[data-results-submit]').hidden")

    # The search, as you type.
    focus(c, "#results-q")
    c.send("Input.insertText", text="frost")
    wait_for(c, f"{shown}.length === 1", timeout=10, what="the search to filter")
    size = "Sorted by the size of the trend, largest first."
    assert c.evaluate(said) == f"Showing 1 of 80 indices. {size}" and "q=frost" in here(c)
    assert "sort=" not in here(c)
    c.evaluate("var q = document.getElementById('results-q'); q.value = '';"
               " q.dispatchEvent(new Event('input', {bubbles: true}))")  # fmt: skip
    assert c.evaluate(f"{shown}.length") == 80 and "q=" not in here(c)

    # A theme chip and "Significant only", from the keyboard.
    focus(c, "input[name=theme][value=heat]")
    c.press(" ")
    wait_for(c, f"{shown}.length === 30", timeout=10, what="the Heat chip")
    assert set(c.evaluate(shown + ".map(function (r) { return r.dataset.chip })")) == {"heat"}
    focus(c, "input[name=significant]")
    c.press(" ")
    wait_for(c, f"{shown}.length === 9", timeout=10, what="Significant only")
    assert c.evaluate(said) == f"Showing 9 of 80 indices. {size}"
    assert "theme=heat" in here(c) and "significant=1" in here(c)

    # Sorting by keyboard: Enter on a header sorts, again reverses; announced.
    focus(c, "th[data-sort-key=trend] button")
    c.press("Enter")
    assert c.evaluate(sorted_by) == ["trend descending"]
    assert c.evaluate(said) == "Showing 9 of 80 indices. Sorted by Slope per decade, descending."
    slopes = c.evaluate(shown + ".map(function (r) { return Number(r.dataset.trend) })")
    assert slopes == sorted(slopes, reverse=True)
    assert c.evaluate("document.activeElement.textContent") == "Slope per decade"
    c.press("Enter")
    assert c.evaluate(sorted_by) == ["trend ascending"]
    assert c.evaluate(said).endswith("Sorted by Slope per decade, ascending.")
    assert "sort=trend" in here(c) and "dir=ascending" in here(c)

    # Every row again, sorted by name: the server's order.
    focus(c, "input[name=theme][value='']")
    c.press(" ")
    focus(c, "input[name=significant]")
    c.press(" ")
    focus(c, "th[data-sort-key=name] button")
    c.press("Enter")
    wait_for(c, f"{shown}.length === 80", timeout=10, what="every row")
    assert c.evaluate(sorted_by) == ["name ascending"]
    assert c.evaluate(keys) == by_name

    # Reloaded, the address gives the same page without the script's help.
    c.navigate(here(c))
    assert c.evaluate(sorted_by) == ["name ascending"] and c.evaluate(keys) == by_name


def test_indices_table_and_detail_by_keyboard(chrome, site):
    """#236: each row's code is a link; Enter shows its index in the detail pane in place,
    marks the row, puts ?show= in the address and announces the index's name, focus
    staying on the row. Beside the table the pane stays in view: the last row's detail is
    in the viewport. On a narrow screen the detail follows the table, focus moves to it,
    and "Back to the list" returns it to the row. At 1280 x 1180, the board's size, at
    least 25 rows are in view. No axe violation with every detail shown, in both themes."""
    c = chrome
    items = "[...document.querySelectorAll('[data-index-item]')]"
    shown = "[...document.querySelectorAll('[data-index-detail]')].filter(d => !d.hidden).map(d => d.dataset.indexDetail)"  # noqa: E501
    current = "[...document.querySelectorAll('[data-index-item][aria-current=true]')].map(a => a.dataset.indexItem)"  # noqa: E501
    said = "document.querySelector('[data-index-said]').textContent"
    c.navigate(site["station results"])
    keys = c.evaluate(f"{items}.map(a => a.dataset.indexItem)")
    assert len(keys) == 80
    assert c.evaluate(shown) == [keys[0]] and c.evaluate(current) == [keys[0]]
    for key in (keys[5], keys[40], keys[-1]):
        focus(c, f"[data-index-item='{key}']")
        c.press("Enter")
        assert c.evaluate(shown) == [key] and c.evaluate(current) == [key], key
        title = f"document.getElementById('detail-{key}-title').textContent.trim()"
        wait_for(c, f"{said} === {title}", timeout=5, what=f"the announcement of {key}")
        assert c.evaluate("document.activeElement.dataset.indexItem") == key
        assert f"show={key}" in here(c)
    # Reloaded, the address shows the same detail.
    c.navigate(here(c))
    assert c.evaluate(shown) == [keys[-1]]
    # The last row, scrolled to: its detail beside it in the viewport, in both themes.
    for scheme in ("light", "dark"):
        set_mode(c, scheme=scheme)
        c.navigate(site["station results"])
        last = f"document.querySelector(\"[data-index-item='{keys[-1]}']\")"
        c.evaluate(f"{last}.scrollIntoView({{block: 'end'}})")
        focus(c, f"[data-index-item='{keys[-1]}']")
        c.press("Enter")
        c.settle()
        box = c.evaluate(
            "(function (r) { return [r.top, r.bottom, innerHeight] })"
            f"(document.getElementById('detail-{keys[-1]}').getBoundingClientRect())"
        )
        assert 0 <= box[0] < box[2], (scheme, box)
    set_mode(c)
    # At the board's size, 25 rows or more in view, and the table needs no sideways scroll.
    c.viewport(1280, 1180)
    try:
        c.navigate(site["station results"])
        rows = c.evaluate(
            "[...document.querySelectorAll('[data-results-table] tbody tr')].filter(t => {"
            " var b = t.getBoundingClientRect(); return b.top >= 0 && b.bottom <= innerHeight"
            " }).length"
        )
        assert rows >= 25, rows
        region = "document.querySelector('.indices__main .table-wrap')"
        assert c.evaluate(f"{region}.scrollWidth <= {region}.clientWidth")
    finally:
        c.viewport(1280, 900)
    # Narrow: the detail after the table; focus moves to its title, and back.
    c.viewport(375, 900)
    try:
        c.navigate(site["station results"])
        focus(c, f"[data-index-item='{keys[3]}']")
        c.press("Enter")
        assert c.evaluate("document.activeElement.id") == f"detail-{keys[3]}-title"
        focus(c, f"[data-index-back='{keys[3]}']")
        c.press("Enter")
        assert c.evaluate("document.activeElement.dataset.indexItem") == keys[3]
    finally:
        c.viewport(1280, 900)
    # Every detail shown (axe skips hidden content), in both themes.
    for scheme in ("light", "dark"):
        set_mode(c, scheme=scheme)
        c.navigate(site["station results"])
        c.evaluate(
            "document.querySelectorAll('[data-index-detail]').forEach(d => { d.hidden = false })"
        )  # noqa: E501
        c.settle()
        assert run_axe(c) == [], scheme
    set_mode(c)


def test_quality_list_and_detail_by_keyboard(chrome, site):
    """#202, #264: the rail's checks are links, Tab moves between them and Enter shows
    the check's detail in place, marks it, puts ?show= in the address and announces the
    detail's title; on a narrow screen focus moves to the detail below the rail, and
    "Back to the list" returns it to the check (#235). Beside the detail the rail stays in
    view: the last check's detail is in the viewport. A value's date selects it in place
    (htmx), focus staying on it, its title announced; "Table" shows the months as a
    table. "Show on the daily chart" opens the daily charts and focuses the chart
    (#174)."""
    c = chrome
    c.navigate(site["station quality results"])
    items = "[...document.querySelectorAll('[data-qc-item]')]"
    shown = "[...document.querySelectorAll('[data-qc-detail]')].filter(d => !d.hidden).map(d => d.dataset.qcDetail)"  # noqa: E501
    current = "[...document.querySelectorAll('[data-qc-item][aria-current=true]')].map(a => a.dataset.qcItem)"  # noqa: E501
    said = "document.querySelector('[data-qc-said]').textContent"
    ids = c.evaluate(f"{items}.map(a => a.dataset.qcItem)")
    assert len(ids) > 4  # Sydney: its "look wrong" checks, then 4 groups
    assert c.evaluate(shown) == [ids[0]] and c.evaluate(current) == [ids[0]]  # the first
    # Tab moves along the list.
    focus(c, f"[data-qc-item='{ids[0]}']")
    c.press("Tab")
    assert c.evaluate("document.activeElement.dataset.qcItem") == ids[1]
    # Every row by keyboard: Enter shows its detail, announced; focus stays on the row.
    for i in ids:
        focus(c, f"[data-qc-item='{i}']")
        c.press("Enter")
        assert c.evaluate(shown) == [i] and c.evaluate(current) == [i], i
        title = f"document.querySelector('[data-qc-detail=\"{i}\"] .qc-detail__title').textContent.replace(/\\s+/g, ' ').trim()"  # noqa: E501
        wait_for(c, f"{said} === {title}", timeout=5, what=f"the announcement of {i}")
        assert c.evaluate("document.activeElement.dataset.qcItem") == i
        assert f"show={i}" in here(c)
    # A check's detail has its values table, paged with htmx.
    group = ids[-1]
    assert c.evaluate(f"!!document.querySelector('[data-qc-detail=\"{group}\"] [data-qc-table]')")
    # A value selected by keyboard: in place, focus on its date, its title announced, the
    # When chart's ring on it, its address kept.
    detail = f"document.querySelector('[data-qc-detail=\"{group}\"]')"
    dates = c.evaluate(
        f"[...{detail}.querySelectorAll('[data-qc-value]')].map(a => a.dataset.qcValue)"
    )
    if len(dates) > 1:
        focus(c, f"[data-qc-detail='{group}'] [data-qc-value='{dates[1]}']")
        c.press("Enter")
        wait_for(c, f"{detail}.querySelector('[data-qc-table]').dataset.selected === '{dates[1]}'",
                 timeout=10, what="the value selected")  # fmt: skip
        assert c.evaluate("document.activeElement.dataset.qcValue") == dates[1]
        value = f"{detail}.querySelector('[data-qc-value-title]').textContent"
        value += ".replace(/\\s+/g, ' ').trim()"
        wait_for(c, f"{said} === {value}", timeout=5, what="the value's announcement")
        assert f"_value={dates[1]}" in here(c)
        ring = c.evaluate(f"{detail}.querySelector('[data-qc-ring]').getAttribute('cx')")
        # On the value, or out of sight for a value with nothing to draw.
        ring_x = f"{detail}.querySelector('[data-qc-table]').dataset.ringX || '-20'"
        assert ring == c.evaluate(ring_x)
    # By calendar month as a table.
    focus(c, f"[data-qc-detail='{group}'] [data-qc-months-toggle]")
    c.press("Enter")
    assert c.evaluate(f"{detail}.querySelector('[data-qc-months-table]').checkVisibility()")
    assert not c.evaluate(f"{detail}.querySelector('[data-qc-months-chart]').checkVisibility()")
    # Reloaded, the address shows the same detail.
    c.navigate(here(c))
    assert c.evaluate(shown) == [group] and c.evaluate(current) == [group]
    # The last row of the list, scrolled to: its detail is in the viewport beside it, in
    # light and dark (#216, #235).
    for scheme in ("light", "dark"):
        set_mode(c, scheme=scheme)
        c.navigate(site["station quality results"])
        focus(c, f"[data-qc-item='{ids[-1]}']")
        last = f"document.querySelector(\"[data-qc-item='{ids[-1]}']\")"
        c.evaluate(f"{last}.scrollIntoView({{block: 'end'}})")
        c.press("Enter")
        c.settle()
        box = c.evaluate(
            "(function (r) { return [r.top, r.bottom, innerHeight] })"
            f"(document.querySelector('[data-qc-detail=\"{ids[-1]}\"]').getBoundingClientRect())"
        )
        assert box[0] >= 0 and box[0] < box[2], (scheme, box)
        row = c.evaluate(
            f"document.querySelector(\"[data-qc-item='{ids[-1]}']\").getBoundingClientRect().bottom"
        )
        assert 0 < row <= box[2], (scheme, row)
        assert c.evaluate("document.activeElement.dataset.qcItem") == ids[-1]
    set_mode(c)
    # "Show on the daily chart" from a finding's detail.
    focus(c, f"[data-qc-item='{ids[0]}']")
    c.press("Enter")
    assert not c.evaluate("document.getElementById('daily').open")
    focus(c, "[data-qc-detail]:not([hidden]) [data-qc-show]")
    c.press("Enter")
    wait_for(c, "!!(document.activeElement && document.activeElement.closest('[data-chart-plot]'))",
             timeout=30, what="focus on the daily chart")  # fmt: skip
    assert c.evaluate("document.getElementById('daily').open")
    # Narrow: the detail follows the list, and focus moves to its title.
    c.viewport(320, 900)
    try:
        c.navigate(site["station quality results"])
        focus(c, f"[data-qc-item='{ids[1]}']")
        c.press("Enter")
        assert c.evaluate("document.activeElement.classList.contains('qc-detail__title')")
        assert c.evaluate(
            "document.querySelector('.qc-rail').getBoundingClientRect().bottom"
            " <= document.activeElement.getBoundingClientRect().top"
        )
        # "Back to the list" returns focus to the row.
        focus(c, f"[data-qc-detail='{ids[1]}'] [data-qc-back]")
        c.press("Enter")
        assert c.evaluate("document.activeElement.dataset.qcItem") == ids[1]
    finally:
        c.viewport(1280, 900)
    # Every detail shown, with every disclosure open (axe skips hidden content), in both
    # themes.
    for scheme in ("light", "dark"):
        set_mode(c, scheme=scheme)
        c.navigate(site["station quality results"])
        c.evaluate(
            "document.querySelectorAll('details').forEach(d => { d.open = true });"
            "document.querySelectorAll('[data-qc-detail]').forEach(d => { d.hidden = false })"
        )
        c.settle()
        assert run_axe(c) == [], scheme
    set_mode(c)
    # "Replace file" is a Tab stop that opens the File sheet (#199), focus on its file
    # input, and Escape gives focus back to it.
    c.navigate(site["station quality results"])
    replace = ".verdict-strip [data-sheet-open='sheet-file']"
    focus(c, replace)
    c.press("Enter")
    time.sleep(0.1)
    assert c.evaluate("document.getElementById('sheet-file').matches(':modal')")
    assert c.evaluate("document.activeElement.type") == "file"
    c.press("Escape")
    time.sleep(0.1)
    assert c.evaluate(f"document.activeElement.matches({json.dumps(replace)})")


def test_one_button_below_its_fields_and_errors_still_focused(chrome, site):
    """#173: the New station page (#201) and the Index settings have one button each,
    below the fields it submits (#114); with an error in a setting, the error summary,
    then its link, focus the field (the settings sheet's page, #199)."""
    c = chrome
    c.viewport(1280, 800)
    try:
        c.navigate(site["station sample loaded"])
        base = "document.querySelector('#new-station [name=base_end]')"
        button = "document.querySelector('#new-station button[value=go]')"
        assert c.evaluate(
            f"{base}.getBoundingClientRect().bottom < {button}.getBoundingClientRect().top"
        )
        c.navigate(site["station edit, settings"])
        run = "#input-form button[type=submit]"
        assert c.evaluate(f"document.querySelectorAll({json.dumps(run)}).length") == 1
        files = "document.querySelector('[aria-labelledby=settings-output-title]')"
        assert c.evaluate(
            f"{files}.getBoundingClientRect().bottom"
            f" < document.querySelector({json.dumps(run)}).getBoundingClientRect().top"
        )
        open_page(c, site["station edit, settings, errors"])
        assert c.evaluate("document.activeElement.hasAttribute('data-error-summary')")
        link = "[data-error-summary] a[href='#id_hdd_base']"
        c.evaluate(f"document.querySelector({json.dumps(link)}).click()")
        assert c.evaluate("document.activeElement.id") == "id_hdd_base"
        assert c.evaluate("document.activeElement.getClientRects().length") > 0
    finally:
        c.viewport(1280, 900)


def test_settings_sheet_by_keyboard(chrome, site):
    """#199: the Index settings sheet, the long one. Its Edit opens it with focus on the
    first field; its body scrolls between the header and the foot, so Apply stays in view
    while Tab goes through every field, each scrolled into view; Tab stays inside. No axe
    violation with it open (every help disclosure open too), in light and dark and at
    320 px. Escape gives focus back to the Edit. The old addresses open it (or the
    thresholds sheet) as the page loads, and closing it focuses the panel's Edit."""
    c = chrome
    c.viewport(1280, 700)
    sheet = "document.getElementById('sheet-settings')"
    apply = f"{sheet}.querySelector('.sheet__foot button[type=submit]')"
    in_view = (
        "(function (el) { var r = el.getBoundingClientRect();"
        " return r.top >= 0 && r.bottom <= window.innerHeight + 1; })"
    )
    try:
        c.navigate(site["station downloads"])  # the panel; the Indices and Quality have the bar
        edit = "[data-inputs-panel] [data-sheet-open='sheet-settings']"
        focus(c, edit)
        c.press("Enter")
        time.sleep(0.1)
        assert c.evaluate(f"{sheet}.open && {sheet}.matches(':modal')")
        assert c.evaluate("document.activeElement.name") == "plot_title"
        body = f"{sheet}.querySelector('.sheet__body')"
        assert c.evaluate(f"{body}.scrollHeight > {body}.clientHeight"), "nothing to scroll"
        reached_apply = False
        for _ in range(60):
            c.press("Tab")
            time.sleep(0.02)
            assert c.evaluate(f"{sheet}.contains(document.activeElement)") or c.evaluate(
                "document.activeElement === document.body"
            ), "Tab left the open sheet"
            assert c.evaluate(f"{in_view}({apply})"), "Apply scrolled out of view"
            if c.evaluate("document.activeElement !== document.body"):
                assert c.evaluate(f"{in_view}(document.activeElement)"), c.evaluate(
                    "document.activeElement.outerHTML.slice(0, 120)"
                )
            if c.evaluate(f"document.activeElement === {apply}"):
                reached_apply = True
                break
        assert reached_apply, "Tab never reached Apply"
        c.evaluate(f"{sheet}.querySelectorAll('details').forEach(function (d) {{ d.open = true }})")
        failures = [f"light: {v['id']}" for v in run_axe(c)]
        c.media(prefers_color_scheme="dark")
        c.transitions_done()
        failures += [f"dark: {v['id']}" for v in run_axe(c, ["color-contrast"])]
        c.media(prefers_color_scheme="light")
        c.viewport(320, 700)
        c.settle(0.1)
        failures += [f"320px: {v['id']}" for v in run_axe(c)]
        assert not failures, failures
        assert c.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert c.evaluate(f"{in_view}({apply})")
        c.viewport(1280, 700)
        c.press("Escape")
        time.sleep(0.1)
        assert not c.evaluate(f"{sheet}.open")
        assert c.evaluate(f"document.activeElement.matches({json.dumps(edit)})")
        # The old addresses: ?settings=open and #adjust on Results, #thresholds on Quality.
        for url, key in [
            (site["station results"] + "?settings=open", "settings"),
            (site["station results"] + "#adjust", "settings"),
            (site["station quality results"].split("#")[0] + "#thresholds", "thresholds"),
        ]:
            c.navigate("about:blank")
            c.navigate(url)
            wait_for(c, f"document.getElementById('sheet-{key}').open", timeout=5, what=url)
            assert c.evaluate(f"document.getElementById('sheet-{key}').matches(':modal')")
            c.press("Escape")
            time.sleep(0.1)
            # The first visible link that opens it: on the Indices the settings line's in
            # the rail (#236), on Quality (no panel since #264) the thresholds line's.
            back = f"[data-inputs-panel] [data-sheet-open='sheet-{key}']"
            if "/indices" in url:
                back = f"[data-settings-line] [data-sheet-open='sheet-{key}']"
            if "/quality" in url:
                back = f"#thresholds [data-sheet-open='sheet-{key}']"
            assert c.evaluate(f"document.activeElement.matches({json.dumps(back)})"), url
    finally:
        c.media(prefers_color_scheme="light")
        c.viewport(1280, 900)


def header_is_one_row(c: Chrome) -> bool:
    """The phone header's brand, tools and menu button share one row (their vertical
    centres within 4px) and nothing in it overflows the window."""
    return c.evaluate(
        "(function () { var h = document.querySelector('.site-header__inner');"
        " var mid = ['.brand', '.site-header__tools', '.site-menu > summary'].map(function (s) {"
        " var r = document.querySelector(s).getBoundingClientRect();"
        " return r.top + r.height / 2; });"
        " return Math.max.apply(null, mid) - Math.min.apply(null, mid) <= 4"
        " && h.scrollWidth <= h.clientWidth"
        " && document.documentElement.scrollWidth <= window.innerWidth; })()"
    )


def test_polish_layout_menu_and_flag_toggle(chrome, site):
    """#115: the workspace tabs (#179; the step indicator before) start where the header and
    the content do; below 600px
    the main links are in a one-row header's "Menu" (a <details>, so it works without
    JavaScript); the results' action row is one line at 1280px; the quality checks' charts
    toggle their QC rings from the legend, by keyboard; the CSV button keeps its place. (The
    unflagged series of "Your data", #173, shows only while the checks run since #235; its
    ``?flags=0`` is checked in test_qc_review.py.)"""
    c = chrome
    left = "Math.round(document.querySelector({}).getBoundingClientRect().left)"
    visible = "document.querySelector({}).checkVisibility()"
    try:
        for width in (1280, 390):
            c.viewport(width, 900)
            c.navigate(site["station quality results"])
            first_tab = c.evaluate(left.format(json.dumps("main [data-tab]")))
            assert first_tab == c.evaluate(left.format(json.dumps("main h1"))), width
        # 390px: one row of header, the links behind the menu, then shown by it.
        assert header_is_one_row(c)
        assert not c.evaluate(visible.format(json.dumps(".site-nav")))
        assert c.evaluate(visible.format(json.dumps(".site-menu > summary")))
        assert not c.evaluate(visible.format(json.dumps(".site-menu__panel a")))
        c.evaluate("document.querySelector('.site-menu > summary').focus()")
        c.press("Enter")
        assert c.evaluate("document.querySelector('.site-menu').open") is True
        # A station page is under Workspaces (#227): aria-current="true", not "page".
        assert c.evaluate(visible.format(json.dumps(".site-menu__panel a[aria-current]")))
        assert run_axe(c) == []
        c.evaluate("document.querySelector('.site-menu').open = false")
        c.viewport(320, 900)
        assert header_is_one_row(c)
        # Font metrics differ between systems (CI's Linux fonts are wider than macOS's):
        # with a wide font the row still holds, at both widths.
        c.evaluate("document.body.style.fontFamily = 'Verdana, \"DejaVu Sans\", sans-serif';"
                   "document.body.style.letterSpacing = '0.04em'")  # fmt: skip
        for width in (320, 390):
            c.viewport(width, 900)
            assert header_is_one_row(c), width
        c.evaluate("document.body.removeAttribute('style')")

        c.viewport(1280, 900)
        c.navigate(site["station results"])
        middles = (
            "[...document.querySelectorAll('.context-bar__actions .results-actions > *')]"
            ".map(e => Math.round(e.getBoundingClientRect().top + e.offsetHeight / 2))"
        )
        tops = c.evaluate(middles)
        assert max(tops) - min(tops) <= 2, tops
        c.evaluate("document.body.style.fontFamily = 'Verdana, \"DejaVu Sans\", sans-serif'")
        tops = c.evaluate(middles)  # one line with a wide font too (CI's Linux fonts)
        assert max(tops) - min(tops) <= 2, tops
        c.evaluate("document.body.removeAttribute('style')")

        # "Your data"'s series without flags (#198) shows only while the checks run since
        # #235: the checks' own charts have the flags' toggle.
        c.navigate(site["station quality results"])
        c.evaluate("document.getElementById('daily').open = true")  # the charts (#174, #235)
        chart = c.evaluate("document.querySelector('.qc-charts [data-chart]').id")
        c.evaluate(f"document.getElementById({json.dumps(chart)}).scrollIntoView()")
        wait_for(c, f"!!document.querySelector('#{chart} [data-chart-flags]')", 60)
        csv = f"Math.round(document.querySelector('#{chart} [data-chart-csv]')"
        csv += f".getBoundingClientRect().top - document.getElementById('{chart}')"
        csv += ".getBoundingClientRect().top)"
        assert c.evaluate(csv) < 40  # in the header's top-right slot, beside the title
        shown = (
            f"ClimpactCharts.get('{chart}').plots.every(u => u.series.every("
            "s => s.label !== {} || s.show === {}))"
        )
        label = json.dumps("Flagged by the quality checks")
        assert c.evaluate(shown.format(label, "true"))
        c.evaluate(f"document.querySelector('#{chart} [data-chart-flags]').focus()")
        c.press("Enter")
        toggle = f"document.querySelector('#{chart} [data-chart-flags]')"
        assert c.evaluate(f"{toggle}.getAttribute('aria-pressed')") == "false"
        assert c.evaluate(shown.format(label, "false"))
        c.press(" ")
        assert c.evaluate(f"{toggle}.getAttribute('aria-pressed')") == "true"
        assert c.evaluate(shown.format(label, "true"))
    finally:
        c.viewport(1280, 900)


# ---- Content Security Policy (#137) --------------------------------------------------------


def policy_of(c: Chrome) -> str | None:
    return c.evaluate(
        "fetch(location.href).then(function (r) {"
        " return r.headers.get('content-security-policy') })",
        await_promise=True,
    )


def test_no_content_security_policy_violations(chrome, site):
    """No page breaks the Content Security Policy (#137). The violations are collected for
    the whole module (browser.py), so this covers every page and flow the tests above went
    through: the station steps, the htmx progress polls, the results filters, the charts,
    the sector comparison, the batch, the grid, help, the jobs and the error pages. Every
    page is opened once more, here, in case this test runs on its own."""
    c = chrome
    for page in site.values():
        open_page(c, page)
    c.navigate(site["station results"])
    policy = policy_of(c)
    assert policy and "script-src 'self'" in policy and "unsafe-inline" not in policy
    assert not c.csp_violations, json.dumps(c.csp_violations, indent=2)


@pytest.fixture(scope="module")
def turnstile_server(tmp_path_factory, chrome):
    """The app with Turnstile on (Cloudflare's test keys; turnstile_test_settings.py)."""
    tests = str(Path(__file__).parent)
    path = os.pathsep.join(filter(None, [tests, os.environ.get("PYTHONPATH")]))
    env = {"DJANGO_SETTINGS_MODULE": "turnstile_test_settings", "PYTHONPATH": path}
    with running_app(tmp_path_factory.mktemp("csp-turnstile"), **env) as url:
        yield url


def test_turnstile_widget_within_the_policy(chrome, turnstile_server):
    """With Turnstile on, its widget loads and passes (Cloudflare's test keys) under the
    policy hosted mode then sends, with no violation. Needs to reach Cloudflare: skipped
    when challenges.cloudflare.com cannot be reached, unless the widget was blocked."""
    c = chrome
    c.csp_violations.clear()
    c.navigate(urljoin(turnstile_server, "/add/"))
    assert "https://challenges.cloudflare.com" in (policy_of(c) or "")
    token = "(document.querySelector('[name=cf-turnstile-response]') || {}).value"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not c.evaluate(token) and not c.csp_violations:
        time.sleep(0.25)
    assert not c.csp_violations, json.dumps(c.csp_violations, indent=2)
    if not c.evaluate(token):
        skip_unless_cloudflare_reachable()
        pytest.fail("the Turnstile widget did not give a token within 30 s")
    assert c.evaluate("typeof window.turnstile === 'object'")


def skip_unless_cloudflare_reachable() -> None:
    import urllib.request

    try:
        urllib.request.urlopen("https://challenges.cloudflare.com/turnstile/v0/api.js", timeout=10)
    except OSError as exc:
        pytest.skip(f"Cloudflare Turnstile cannot be reached from here ({exc})")


def test_turnstile_holds_a_form_until_its_token(chrome, turnstile_server):
    """A form sent before its widget has a token waits for it, then goes (#163): the
    sample's "Check and calculate", pressed as soon as its setup page is parsed, reaches
    the quality checks, not
    the "Not accepted" page, with the button marked busy meanwhile and no policy
    violation. Skipped when Cloudflare cannot be reached, as above."""
    c = chrome
    c.csp_violations.clear()
    setup_sample(c, lambda path: urljoin(turnstile_server, path))
    load = here(c)
    assert load.endswith("/setup")
    c.events.clear()
    c.send("Page.navigate", url=load)
    c.wait_event("Page.domContentEventFired")
    top = "document.querySelector('#new-station button[value=go]')"
    form_token = "(document.querySelector('#new-station [name=cf-turnstile-response]') || {}).value"
    early = bool(c.evaluate(form_token))
    c.evaluate(f"{top}.click()")
    if not early:  # held: the usual case, the widget takes a second or two
        assert c.evaluate(f"{top}.getAttribute('aria-busy')") == "true"
        assert c.evaluate("!!document.querySelector('.setup__cta + [role=status]')")
    where = "location.pathname + ' ' + document.title"
    deadline = time.monotonic() + 75
    page = ""
    while time.monotonic() < deadline:
        try:
            page = c.evaluate(where) or ""
        except DevToolsError:
            page = ""  # navigating
        if page.split(" ", 1)[0].endswith("/quality") or "Not accepted" in page:
            break
        time.sleep(0.25)
    assert "Not accepted" not in page, page
    if not page.split(" ", 1)[0].endswith("/quality"):
        skip_unless_cloudflare_reachable()
        pytest.fail(f"the details form was not sent within 75 s ({page})")
    assert not c.csp_violations, json.dumps(c.csp_violations, indent=2)

"""Headless Chrome driven over the DevTools protocol, for the accessibility tests (#83).

No browser is downloaded and nothing is installed: the Chrome already on the machine is
started headless with a temporary profile and a debugging port, and driven over its
WebSocket with ``websocket-client``. Chrome is found from the ``CHROME`` environment
variable, then the usual install locations (macOS, Linux, Windows) and the ``PATH``
(``google-chrome``, ``chromium``). CI uses the runner's preinstalled Google Chrome.

Every Content Security Policy violation the pages report (#137) is kept in
``Chrome.csp_violations``, whatever page was open: the ``securitypolicyviolation`` events
of every document, and the browser's console messages about the policy (eval refused,
for one, which raises no event when htmx catches the error).
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)
PATH_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")


def find_chrome() -> str | None:
    """The Chrome executable, or None when there is none."""
    env = os.environ.get("CHROME")
    if env:
        return env if Path(env).exists() else shutil.which(env)
    for path in CANDIDATES:
        if Path(path).exists():
            return path
    for name in PATH_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


# Reports each securitypolicyviolation event to the test through a DevTools binding.
CSP_BINDING = "__climpactCspViolation"
CSP_LISTENER = """document.addEventListener('securitypolicyviolation', function (e) {
  window.BINDING(JSON.stringify({page: location.href, directive: e.violatedDirective,
    blocked: e.blockedURI, source: e.sourceFile + ':' + e.lineNumber, sample: e.sample,
    disposition: e.disposition}));
}, true);""".replace("BINDING", CSP_BINDING)
CSP_MESSAGE = "Content Security Policy"

# Whether the page is still busy: loading, an htmx request in flight, or a chart that is
# loading. charts.js loads a chart only when it comes within 200px of the viewport (an
# IntersectionObserver), so a chart further down, or in a hidden tab panel, keeps its
# skeleton until it is scrolled to; only charts that have asked for their data, or are in
# view and about to, are waited for (waiting on the others ran to the timeout, #182).
BUSY = """(function () {
  if (document.readyState !== 'complete' || document.querySelector('.htmx-request')) return true;
  var margin = 200, height = window.innerHeight;
  return Array.prototype.some.call(document.querySelectorAll('[data-chart-src]'), function (el) {
    if (!el.querySelector('[data-chart-plot] .skeleton')) return false;
    if (el._chart && el._chart.requested) return true;
    var r = el.getBoundingClientRect();
    return el.getClientRects().length > 0 && r.bottom > -margin && r.top < height + margin;
  });
})()"""


class DevToolsError(RuntimeError):
    pass


class Chrome:
    """One headless Chrome with one page, driven over the DevTools protocol."""

    def __init__(self, executable: str, width: int = 1280, height: int = 900):
        import websocket  # websocket-client, a dev dependency

        self.profile = tempfile.mkdtemp(prefix="climpact-a11y-chrome-")
        self.proc = subprocess.Popen(
            [
                executable,
                "--headless=new",
                "--remote-debugging-port=0",
                f"--user-data-dir={self.profile}",
                f"--window-size={width},{height}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-sync",
                "--disable-gpu",
                "--hide-scrollbars",
                "--mute-audio",
                "--no-sandbox",  # CI runs as a user without the sandbox's privileges
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        port_file = Path(self.profile) / "DevToolsActivePort"
        deadline = time.monotonic() + 30
        while not port_file.exists() or not port_file.read_text().strip():
            if self.proc.poll() is not None or time.monotonic() > deadline:
                self.close()
                raise DevToolsError("Chrome did not start")
            time.sleep(0.05)
        port = port_file.read_text().split()[0]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as r:
            targets = json.load(r)
        page = next(t for t in targets if t["type"] == "page")
        self.ws = websocket.create_connection(
            page["webSocketDebuggerUrl"], timeout=60, suppress_origin=True
        )
        self.ids = itertools.count(1)
        self.events: list[dict] = []
        self.csp_violations: list[dict] = []
        for domain in ("Page", "Runtime", "Network", "DOM", "CSS", "Log"):
            self.send(f"{domain}.enable")
        self.send("Runtime.addBinding", name=CSP_BINDING)
        self.send("Page.addScriptToEvaluateOnNewDocument", source=CSP_LISTENER)
        self.viewport(width, height)

    # ---- the protocol ------------------------------------------------------------------

    def send(self, method: str, **params):
        """Call a DevTools method and return its result; events seen meanwhile are kept."""
        msg_id = next(self.ids)
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == msg_id:
                if "error" in message:
                    raise DevToolsError(f"{method}: {message['error']}")
                return message.get("result", {})
            if "method" in message:
                self.keep(message)

    def keep(self, event: dict) -> None:
        """Keep an event for wait_event, or a CSP violation in csp_violations."""
        params = event.get("params", {})
        if event["method"] == "Runtime.bindingCalled" and params.get("name") == CSP_BINDING:
            self.csp_violations.append(json.loads(params["payload"]))
        elif event["method"] == "Log.entryAdded" and CSP_MESSAGE in params["entry"]["text"]:
            entry = params["entry"]
            self.csp_violations.append({"page": entry.get("url", ""), "message": entry["text"]})
        else:
            self.events.append(event)

    def wait_event(self, method: str, timeout: float = 30) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            for i, event in enumerate(self.events):
                if event["method"] == method:
                    return self.events.pop(i)
            if time.monotonic() > deadline:
                raise DevToolsError(f"timed out waiting for {method}")
            self.ws.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                message = json.loads(self.ws.recv())
            finally:
                self.ws.settimeout(60)
            if "method" in message:
                self.keep(message)

    def evaluate(self, expression: str, await_promise: bool = False):
        """Evaluate JavaScript in the page and return its value (JSON-serialisable)."""
        result = self.send(
            "Runtime.evaluate",
            expression=expression,
            returnByValue=True,
            awaitPromise=await_promise,
        )
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            text = details.get("exception", {}).get("description") or details.get("text")
            raise DevToolsError(f"JavaScript error: {text}")
        return result["result"].get("value")

    # ---- the page ----------------------------------------------------------------------

    def navigate(self, url: str, settle: float = 0.2) -> None:
        """Open a URL, wait for its load event and for htmx and the charts to settle."""
        self.events.clear()
        self.send("Page.navigate", url=url)
        self.wait_event("Page.loadEventFired")
        self.settle(settle)

    def settle(self, pause: float = 0.2, timeout: float = 10) -> None:
        """Wait until no htmx request is in flight and no chart is still loading."""
        time.sleep(pause)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self.evaluate(BUSY):
            time.sleep(0.1)

    def transitions_done(self, timeout: float = 3) -> None:
        """Wait until no CSS transition or finite animation is running (after a theme
        change, the colours have reached their end); waits two frames first, so that
        transitions started by a change just made are counted."""
        moving = (
            "new Promise(function (done) { requestAnimationFrame(function () {"
            " requestAnimationFrame(function () { done(document.getAnimations().some("
            "function (a) { return a.playState === 'running' &&"
            " a.effect.getComputedTiming().endTime !== Infinity })) }) }) })"
        )
        deadline = time.monotonic() + timeout
        while self.evaluate(moving, await_promise=True) and time.monotonic() < deadline:
            time.sleep(0.05)

    def set_content(self, html: str) -> None:
        """Replace the current document (same origin) with the given HTML."""
        frame = self.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
        self.send("Page.setDocumentContent", frameId=frame, html=html)
        self.settle()

    def set_cookie(self, url: str, name: str, value: str) -> None:
        self.send("Network.setCookie", url=url, name=name, value=value)

    def viewport(self, width: int, height: int = 900, scale: float = 1) -> None:
        """The CSS viewport; ``scale`` > 1 is browser zoom (200%: scale 2 at half width)."""
        self.send(
            "Emulation.setDeviceMetricsOverride",
            width=width,
            height=height,
            deviceScaleFactor=scale,
            mobile=False,
        )

    def media(self, **features: str) -> None:
        """Emulated media features, e.g. ``prefers_color_scheme="dark"``."""
        self.send(
            "Emulation.setEmulatedMedia",
            features=[{"name": k.replace("_", "-"), "value": v} for k, v in features.items()],
        )

    def screenshot(self, path: Path, full_page: bool = False) -> None:
        import base64

        params = {"format": "png", "captureBeyondViewport": full_page}
        path.write_bytes(base64.b64decode(self.send("Page.captureScreenshot", **params)["data"]))

    def press(self, key: str, shift: bool = False) -> None:
        """Press and release one key (Tab, Enter, Escape, ArrowRight, Space ...)."""
        codes = {
            "Tab": 9,
            "Enter": 13,
            "Escape": 27,
            " ": 32,
            "End": 35,
            "Home": 36,
            "ArrowLeft": 37,
            "ArrowUp": 38,
            "ArrowRight": 39,
            "ArrowDown": 40,
        }
        common = {
            "key": key,
            "code": "Space" if key == " " else key,
            "windowsVirtualKeyCode": codes.get(key, 0),
            "modifiers": 8 if shift else 0,
        }
        text = {"Enter": "\r", " ": " "}.get(key)
        down = {"type": "keyDown", **common}
        if text:
            down["text"] = text
        self.send("Input.dispatchKeyEvent", **down)
        self.send("Input.dispatchKeyEvent", type="keyUp", **common)

    def close(self) -> None:
        try:
            if getattr(self, "ws", None):
                self.ws.close()
        finally:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            shutil.rmtree(self.profile, ignore_errors=True)

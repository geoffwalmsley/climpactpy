"""The static files ship inside the package; the vendored htmx is the recorded file."""

import hashlib
import re
from pathlib import Path

import pytest

import climpact_web

STATIC = Path(climpact_web.__file__).parent / "core" / "static" / "climpact_web"


def test_static_files_in_package():
    for name in (
        "css/main.css",
        "css/theme-dark.css",
        "css/patterns.css",
        "css/stations.css",
        "js/ui.js",
        "icons/icons.svg",
        "icons/favicon.svg",
        "chart-palette.json",
        "vendor/htmx/htmx.min.js",
    ):
        assert (STATIC / name).is_file(), name


def test_vendored_htmx_matches_readme():
    readme = (STATIC / "vendor" / "htmx" / "README.md").read_text()
    recorded = re.search(r"SHA-256: `([0-9a-f]{64})`", readme).group(1)
    actual = hashlib.sha256((STATIC / "vendor" / "htmx" / "htmx.min.js").read_bytes())
    assert actual.hexdigest() == recorded


@pytest.mark.parametrize("name", ["main.css", "theme-dark.css", "patterns.css", "stations.css"])
def test_css_uses_logical_properties(name):
    """Right-to-left languages: no physical left/right/top/bottom in the stylesheets."""
    css = (STATIC / "css" / name).read_text()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media[^{]*", "", css)  # media queries on the viewport width are fine
    physical = r"(margin|padding|border)-(left|right|top|bottom)|\b(left|right|top|bottom)\s*:"
    assert not re.search(physical, css)
    sizes = r"(?<![\w-])(min-|max-)?(width|height)\s*:"  # inline-size, block-size instead
    assert not re.search(sizes, css)


def test_ui_js_has_no_dependencies():
    """ui.js is plain script: no imports, no network requests."""
    js = (STATIC / "js" / "ui.js").read_text()
    assert not re.search(r"\bimport\b|\brequire\(|fetch\(|XMLHttpRequest|https?://", js)

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
        "css/help.css",
        "js/ui.js",
        "js/tour.js",
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


@pytest.mark.parametrize(
    "name", ["main.css", "theme-dark.css", "patterns.css", "stations.css", "batch.css", "help.css"]
)
def test_css_uses_logical_properties(name):
    """Right-to-left languages: no physical left/right/top/bottom in the stylesheets."""
    css = (STATIC / "css" / name).read_text()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media[^{]*", "", css)  # media queries on the viewport width are fine
    physical = r"(margin|padding|border)-(left|right|top|bottom)|\b(left|right|top|bottom)\s*:"
    assert not re.search(physical, css)
    sizes = r"(?<![\w-])(min-|max-)?(width|height)\s*:"  # inline-size, block-size instead
    assert not re.search(sizes, css)


@pytest.mark.parametrize("name", ["ui.js", "tour.js"])
def test_scripts_have_no_dependencies(name):
    """ui.js and tour.js are plain scripts: no imports, no network requests."""
    js = (STATIC / "js" / name).read_text()
    assert not re.search(r"\bimport\b|\brequire\(|fetch\(|XMLHttpRequest|https?://", js)


def test_help_assets_stay_small():
    """help.css loads on every page and tour.js on the landing page (#81)."""
    assert (STATIC / "css" / "help.css").stat().st_size < 7 * 1024
    assert (STATIC / "js" / "tour.js").stat().st_size < 8 * 1024

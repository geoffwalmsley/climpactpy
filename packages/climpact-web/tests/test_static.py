"""The static files ship inside the package; the vendored htmx is the recorded file."""

import hashlib
import re
from pathlib import Path

import pytest

import climpact_web

STATIC = Path(climpact_web.__file__).parent / "core" / "static" / "climpact_web"


def test_static_files_in_package():
    for name in (
        "css/climpact.css",
        "js/ui.js",
        "js/tour.js",
        "icons/icons.svg",
        "icons/favicon.svg",
        "chart-palette.json",
        "vendor/htmx/htmx.min.js",
        "js/charts.js",
        "vendor/uplot/uPlot.iife.min.js",
        "vendor/uplot/uPlot.min.css",
    ):
        assert (STATIC / name).is_file(), name


def test_vendored_htmx_matches_readme():
    readme = (STATIC / "vendor" / "htmx" / "README.md").read_text()
    recorded = re.search(r"SHA-256: `([0-9a-f]{64})`", readme).group(1)
    actual = hashlib.sha256((STATIC / "vendor" / "htmx" / "htmx.min.js").read_bytes())
    assert actual.hexdigest() == recorded


TAILWIND = STATIC.parents[1] / "tailwind"
TEMPLATES = sorted(Path(climpact_web.__file__).parent.rglob("templates/**/*.html"))


@pytest.mark.parametrize("path", sorted(TAILWIND.rglob("*.css")), ids=lambda p: p.name)
def test_css_uses_logical_properties(path):
    """Right-to-left languages: no physical left/right/top/bottom in the stylesheet source."""
    css = path.read_text()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media[^{]*", "", css)  # media queries on the viewport width are fine
    physical = r"(margin|padding|border)-(left|right|top|bottom)|\b(left|right|top|bottom)\s*:"
    assert not re.search(physical, css)
    sizes = r"(?<![\w-])(min-|max-)?(width|height)\s*:"  # inline-size, block-size instead
    assert not re.search(sizes, css)


# Tailwind utilities on the inline axis that do not flip in right-to-left pages; use
# ps-/pe-, ms-/me-, start-/end-, text-start/end, rounded-s/e, border-s/e instead.
PHYSICAL_UTILITIES = re.compile(
    r"(?<![\w-])(?:[a-z-]+:)*-?(?:pl|pr|ml|mr|left|right|rounded-[lr]|rounded-[tb][lr]"
    r"|border-[lr]|scroll-m[lr]|scroll-p[lr])-[\w.()\[\]/-]+|text-(?:left|right)\b"
)


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_templates_use_logical_utilities(path):
    classes = " ".join(re.findall(r'class="([^"]*)"', path.read_text()))
    assert not PHYSICAL_UTILITIES.findall(classes)


@pytest.mark.parametrize("name", ["ui.js", "tour.js"])
def test_scripts_have_no_dependencies(name):
    """ui.js and tour.js are plain scripts: no imports, no network requests."""
    js = (STATIC / "js" / name).read_text()
    assert not re.search(r"\bimport\b|\brequire\(|fetch\(|XMLHttpRequest|https?://", js)


def test_tour_script_stays_small():
    """tour.js loads on the landing page (#81)."""
    assert (STATIC / "js" / "tour.js").stat().st_size < 8 * 1024

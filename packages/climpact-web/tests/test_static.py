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


# Class names in the templates that no stylesheet rule needs: hooks for scripts and tests,
# and words a template puts after a modifier prefix (alert--{{ kind }} and the like).
HOOK_CLASSES = {
    "batch-progress", "download-group", "download-link", "empty-filter", "file-browser__folder",
    "gmap__cell--selected", "gmap__svg", "gridded-checks__problems", "gridded-explore__help",
    "gridded-map", "gridded-series", "help-page", "index-card__daily", "index-card__meta",
    "job-files", "job-page", "job-progress", "numeric", "param", "qc-charts", "qc-check",
    "qc-page", "result-nav", "results-actions", "results-filter__significant",
    "sector-settings__summary", "series-nav", "tabs", "tabs__panel-heading", "trend-summary",
    "alert--info", "invalid", "ready", "success", "warning",
}  # fmt: skip


def test_every_template_class_is_styled():
    """Each class a template names is in the compiled stylesheet (#118): a utility Tailwind
    generated, or a component; so a mistyped or unscanned utility fails here rather than
    leaving an element unstyled. Rebuild with scripts/build-css.sh after adding classes."""
    css = (STATIC / "css" / "climpact.css").read_text()
    styled = {re.sub(r"\\(.)", r"\1", m) for m in re.findall(r"\.((?:\\.|[\w-])+)", css)}
    unstyled = set()
    for path in TEMPLATES:
        for value in re.findall(r'class="([^"]*)"', path.read_text()):
            value = re.sub(r"\{%.*?%\}|\{\{.*?\}\}", " ", value)  # template tags: dynamic
            unstyled |= {
                f"{path.name}: {name}"
                for name in value.split()
                if name not in styled and name not in HOOK_CLASSES and not name.endswith("--")
            }
    assert not unstyled, sorted(unstyled)

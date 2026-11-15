"""Design tokens (#71, #118): WCAG contrast of every colour pair the components use, in
both themes, computed from the values in the Tailwind theme; the theme's scales; the
compiled stylesheet carries every token and the dark theme, and is up to date with its
source; the chart palette export; the size budget of the stylesheet and script."""

import gzip
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from climpact_web.core import tokens

THEMES = tokens.theme_tokens()
STATIC = tokens.STATIC
COMPILED = STATIC / "css" / "climpact.css"
REPO = Path(__file__).resolve().parents[3]

TEXT = 4.5  # WCAG 2.1 AA, 1.4.3: normal-size text
NON_TEXT = 3.0  # WCAG 2.1 AA, 1.4.11: control borders, focus rings, icons, chart marks

BACKGROUNDS = ("page", "surface", "surface-sunken")

# (foreground, background, minimum ratio): every pairing the components use.
PAIRS = (
    [(fg, bg, TEXT) for bg in BACKGROUNDS for fg in ("text", "text-muted", "accent")]
    + [(fg, bg, TEXT) for bg in BACKGROUNDS for fg in ("success", "warning", "danger")]
    + [(fg, bg, NON_TEXT) for bg in BACKGROUNDS for fg in ("border-strong", "focus")]
    + [("text", f"{k}-soft", TEXT) for k in ("accent", "success", "warning", "danger")]
    + [(k, f"{k}-soft", NON_TEXT) for k in ("accent", "success", "warning", "danger")]
    + [
        ("accent", "accent-soft", TEXT),  # ghost button hover, info badge text
        ("accent-hover", "accent-soft", TEXT),
        ("accent-hover", "surface", TEXT),  # link hover
        ("text-muted", "accent-soft", TEXT),  # muted text in a highlighted table row
        ("accent-contrast", "accent", TEXT),  # primary button
        ("accent-contrast", "accent-hover", TEXT),
        ("danger-contrast", "danger", TEXT),  # danger button
    ]
)

# Chart marks drawn on the chart surface that must stand out without a label.
CHART_MARKS = ("tmax", "tmin", "prcp", "trend", "flag", "axis")


def relative_luminance(hex_colour: str) -> float:
    value = hex_colour.lstrip("#")
    assert re.fullmatch(r"[0-9a-fA-F]{6}", value), hex_colour
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_contrast_formula():
    assert contrast("#000000", "#ffffff") == pytest.approx(21)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("fg, bg, minimum", PAIRS, ids=lambda v: str(v))
def test_colour_pairs_meet_wcag_aa(theme, fg, bg, minimum):
    t = THEMES[theme]
    ratio = contrast(t[f"color-{fg}"], t[f"color-{bg}"])
    assert ratio >= minimum, f"{theme}: {fg} on {bg} is {ratio:.2f}:1, needs {minimum}:1"


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("mark", CHART_MARKS)
def test_chart_marks_stand_out(theme, mark):
    t = THEMES[theme]
    ratio = contrast(t[f"chart-{mark}"], t["color-surface"])
    assert ratio >= NON_TEXT, f"{theme}: --chart-{mark} is {ratio:.2f}:1 on the surface"


def test_dark_theme_only_overrides_known_tokens():
    light = tokens.read_tokens(tokens.LIGHT_CSS)
    dark = tokens.read_tokens(tokens.DARK_CSS)
    assert set(dark) <= set(light), set(dark) - set(light)
    # Every colour changes in the dark theme (a forgotten one would be a light colour on dark)
    colours = {name for name in light if name.startswith(("color-", "chart-"))}
    assert colours <= set(dark), colours - set(dark)


def test_chart_palette_json_matches_the_css():
    on_disk = json.loads(tokens.CHART_PALETTE_JSON.read_text())
    assert on_disk == tokens.chart_palette(), (
        "chart-palette.json is out of date: run uv run python -m climpact_web.core.tokens"
    )
    for theme in ("light", "dark"):
        assert len(on_disk[theme]["categorical"]) == 8
        assert len(on_disk[theme]["sequential"]) == 5
        assert len(on_disk[theme]["diverging"]) == 7


def source_files() -> list[Path]:
    return sorted(tokens.TAILWIND.rglob("*.css"))


def test_no_raw_colours_outside_tokens():
    """Components use tokens: hex colours appear only in the two token blocks."""
    for path in source_files():
        css = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
        if path in tokens.BLOCKS:  # drop the token block itself
            css = re.sub(tokens.BLOCKS[path] + r".*?\}", "", css, count=1, flags=re.S)
        assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", css), path.name


def test_theme_scales():
    """The type scale, spacing step, radii and widths the components were designed with
    (#71): Tailwind's utilities are generated from these (text-sm, p-4, rounded-md)."""
    light = THEMES["light"]
    assert light["spacing"] == "0.25rem"  # p-1 = 0.25rem ... p-16 = 4rem
    assert [light[f"text-{k}"] for k in ("xs", "sm", "base", "md", "lg", "xl", "2xl")] == [
        "0.8125rem", "0.875rem", "1rem", "1.125rem", "1.25rem", "1.5rem", "2rem",
    ]  # fmt: skip
    assert [light[f"radius-{k}"] for k in ("sm", "md", "lg", "full")] == [
        "4px", "8px", "12px", "999px",
    ]  # fmt: skip
    assert light["container-content"] == "72rem" and light["container-prose"] == "42rem"
    assert light["font-weight-bold"] == "650" and light["leading-normal"] == "1.6"


def test_compiled_css_has_every_token_and_the_dark_theme():
    css = COMPILED.read_text()
    names = lambda block: set(re.findall(r"--([\w-]+):", block))  # noqa: E731
    theme = re.search(r":root,:host\{(.*?)\}", css).group(1)
    assert names(theme) == set(THEMES["light"])
    # The dark tokens apply with the OS preference unless the toggle chose light, and
    # whenever the toggle chose dark (ui.js sets data-theme on <html>).
    dark = set(tokens.read_tokens(tokens.DARK_CSS))
    preferred = re.search(
        r"@media \(prefers-color-scheme:dark\)\{:root:not\(\[data-theme=light\]\)\{(.*?)\}", css
    )
    chosen = re.search(r":root\[data-theme=dark\]\{(.*?)\}", css)
    assert preferred and names(preferred.group(1)) == dark
    assert chosen and names(chosen.group(1)) == dark


def tailwind() -> str | None:
    found = os.environ.get("TAILWIND_BIN") or str(REPO / "bin" / "tailwindcss")
    return found if Path(found).is_file() else None


def test_compiled_css_is_up_to_date(tmp_path):
    """static/climpact_web/css/climpact.css is what the Tailwind source builds to (#118):
    rebuild it with scripts/build-css.sh after changing a template's classes or the source.
    Needs the pinned CLI (scripts/fetch-tailwind.sh); CI sets CLIMPACT_REQUIRE_TAILWIND."""
    binary = tailwind()
    if binary is None:
        if os.environ.get("CLIMPACT_REQUIRE_TAILWIND"):
            raise AssertionError("no Tailwind CLI: run scripts/fetch-tailwind.sh")
        pytest.skip("no Tailwind CLI in bin/ (scripts/fetch-tailwind.sh)")
    out = tmp_path / "climpact.css"
    subprocess.run(
        [binary, "--input", "climpact.css", "--output", str(out), "--minify"],
        cwd=tokens.TAILWIND, check=True, capture_output=True,
    )  # fmt: skip
    assert out.read_text() == COMPILED.read_text(), (
        "css/climpact.css is out of date: run scripts/build-css.sh"
    )


# Size budget (#71 aims for a small stylesheet; the page budgets are #82's). One compiled
# stylesheet for every page since #118, replacing main.css, theme-dark.css and the page
# stylesheets.
CSS_BUDGET = 70_000  # bytes, minified
CSS_GZIP_BUDGET = 12_500
JS_BUDGET = 14_000  # ui.js, uncompressed (12 KB before #83)


def test_css_size_budget():
    css = COMPILED.read_bytes()
    assert len(css) <= CSS_BUDGET, len(css)
    assert len(gzip.compress(css)) <= CSS_GZIP_BUDGET, len(gzip.compress(css))


def test_js_size_budget():
    assert len((STATIC / "js" / "ui.js").read_bytes()) <= JS_BUDGET

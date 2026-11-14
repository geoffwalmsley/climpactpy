"""Design tokens (#71): WCAG contrast of every colour pair the components use, in both
themes, computed from the values in the stylesheets; the chart palette export; the size
budget of the stylesheets and script."""

import gzip
import json
import re

import pytest

from climpact_web.core import tokens

THEMES = tokens.theme_tokens()
STATIC = tokens.STATIC

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
        "chart-palette.json is out of date: run .venv/bin/python -m climpact_web.core.tokens"
    )
    for theme in ("light", "dark"):
        assert len(on_disk[theme]["categorical"]) == 8
        assert len(on_disk[theme]["sequential"]) == 5
        assert len(on_disk[theme]["diverging"]) == 7


def test_no_raw_colours_outside_tokens():
    """Components use tokens: hex colours appear only in the token blocks."""
    css = re.sub(r"/\*.*?\*/", "", tokens.LIGHT_CSS.read_text(), flags=re.S)
    after_tokens = css[css.index("}") + 1 :]
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", after_tokens)


# Size budget (#71 aims for a small stylesheet; the page budgets are #82's).
CSS_BUDGET = 36_000  # bytes, main.css + theme-dark.css, uncompressed
CSS_GZIP_BUDGET = 8_500
JS_BUDGET = 12_000  # ui.js, uncompressed


def test_css_size_budget():
    css = b"".join((STATIC / "css" / name).read_bytes() for name in ("main.css", "theme-dark.css"))
    assert len(css) <= CSS_BUDGET, len(css)
    assert len(gzip.compress(css)) <= CSS_GZIP_BUDGET, len(gzip.compress(css))


def test_js_size_budget():
    assert len((STATIC / "js" / "ui.js").read_bytes()) <= JS_BUDGET

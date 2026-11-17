"""The design tokens in the stylesheet source, read back as data (#71, #118).

The Tailwind theme (``tailwind/theme.css``, light) and the ``@variant dark`` block of
``tailwind/base.css`` (dark) are the one source of the colours. This module parses them
for the tests (WCAG contrast of every text/background pair) and writes
``chart-palette.json``, the chart colours for code that cannot read CSS: the static plots
and PDF report (#74, #79) and chart exports (#75).
In the browser, charts read the live values with ``Climpact.chartPalette()`` (ui.js).

Regenerate the JSON after changing a ``--chart-*`` token::

    uv run python -m climpact_web.core.tokens
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static" / "climpact_web"
TAILWIND = HERE / "tailwind"
LIGHT_CSS = TAILWIND / "theme.css"
DARK_CSS = TAILWIND / "base.css"
# The blocks that hold the tokens: the theme, and the dark variant's values.
BLOCKS = {LIGHT_CSS: r"@theme\s+static\s*\{", DARK_CSS: r"@variant\s+dark\s*\{"}
CHART_PALETTE_JSON = STATIC / "chart-palette.json"

CHART_ROLES = ("tmax", "tmin", "prcp", "trend", "trend-band", "flag", "grid", "axis")
# The trend scale (#227), from the strong decrease to the strong increase.
TREND_SCALE = ("decrease-2", "decrease-1", "increase-1", "increase-2")


def read_tokens(path: Path) -> dict[str, str]:
    """``--name: value`` pairs from the token block of theme.css or base.css (BLOCKS)."""
    css = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
    block = re.search(BLOCKS[path] + r"(.*?)\}", css, flags=re.S)
    if block is None:
        raise ValueError(f"no token block in {path}")
    return {
        name: " ".join(value.split())
        for name, value in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", block.group(1))
    }


def theme_tokens() -> dict[str, dict[str, str]]:
    """Light and dark token values; dark falls back to light for tokens it leaves alone."""
    light = read_tokens(LIGHT_CSS)
    return {"light": light, "dark": {**light, **read_tokens(DARK_CSS)}}


def _numbered(tokens: dict[str, str], prefix: str) -> list[str]:
    found = sorted(
        (int(m.group(1)), value)
        for name, value in tokens.items()
        if (m := re.fullmatch(rf"{prefix}-(\d+)", name))
    )
    return [value for _, value in found]


def chart_palette() -> dict:
    """The chart colours for each theme, as written to chart-palette.json."""
    palette = {
        "about": (
            "climpact-web chart colours, generated from the --chart-* tokens in "
            "tailwind/theme.css and tailwind/base.css by climpact_web.core.tokens. "
            "Categorical colours are assigned in this fixed order, never cycled."
        )
    }
    for theme, tokens in theme_tokens().items():
        palette[theme] = {
            "categorical": _numbered(tokens, "chart"),
            "roles": {role: tokens[f"chart-{role}"] for role in CHART_ROLES},
            "sequential": _numbered(tokens, "chart-seq"),
            "diverging": _numbered(tokens, "chart-div"),
            "trend_scale": [tokens[f"chart-{step}"] for step in TREND_SCALE],
            "coverage": _numbered(tokens, "chart-coverage"),
            "surface": tokens["color-surface"],
            "text": tokens["color-text"],
            "text_muted": tokens["color-text-muted"],
        }
    return palette


def chart_palette_json() -> str:
    return json.dumps(chart_palette(), indent=2) + "\n"


def main() -> None:
    CHART_PALETTE_JSON.write_text(chart_palette_json())
    print(f"wrote {CHART_PALETTE_JSON}")


if __name__ == "__main__":
    main()

---
name: build-to-design
description: Use when working on a climpactpy ticket that changes how the web app looks or behaves (label `web`, especially the children of epic #230), before building and again before the pull request. Covers reading the ticket's Design section, DESIGN.md and the design canvas boards, building with the app's tokens and components, comparing the result with the boards in light and dark, and reporting a Design check in the PR.
---

# Building a web ticket to the design

The web app's design has two sources, with different jobs:

- **`DESIGN.md`** holds the rules: tokens, components, the Do and Don't lists, and the
  **Target** marks that say what is still to be built and by which ticket.
- **The design canvas** (<https://claude.ai/artifact/7zEuwY1xA264zmxpq3GFdu>) holds the
  pictures: one board per screen, in light and dark. `DESIGN.md`, "The design canvas",
  lists which board belongs to which ticket.

A board fixes a screen's layout, content, order, density and wording. `DESIGN.md` wins on
rules and tokens. A real conflict between them goes to the maintainer: never pick a side
silently.

## 1. Before building: read

1. **The ticket's Design section:** the boards and `DESIGN.md` sections it must match. If
   it has none, add one (see the `ticket` skill) from the table in `DESIGN.md`.
2. **`DESIGN.md`**, at least the sections named, the Rules and the Agent prompt guide.
3. **Each board named**, with the Artifact tool: `action: "read"`, `url` the canvas,
   `path` `project/<Board>.dc.html` (for example `project/Quality.dc.html`). The dark
   board is the same file with the theme switched, so one read covers both. If the
   Artifact tool is missing or the read is refused, stop and tell the maintainer; don't
   work from memory or from screenshots in old pull requests.
4. **Write down what the board fixes**, region by region, before touching code:
   - the regions and their order (bars, rails, tables, panes, strips);
   - each table's columns, in order, and its row height;
   - every piece of copy: headings, labels, buttons, empty and error text (the wording is
     part of the design; it still goes through `{% translate %}`);
   - the states the board shows (selected row, verdicts, out of date, returning visitor
     and other tweaks in its `data-props`);
   - what is **not** spec: the "Mock-up" banner, illustrative values and names, the
     canvas's own colour values and its IBM Plex font.
5. **Map the board to the app:** its colours to tokens (`DESIGN.md`, Colour, "From the
   canvas to the tokens"); its parts to components in `core/templates/components/` and
   the patterns in `DESIGN.md`, Components. A part with no component becomes a new one,
   added to `/patterns/`.

## 2. While building

- Tokens only, no hex values; new colours get light and dark values and pass
  `test_design_tokens.py`. Ink for actions, blue for links (`--color-link`, from #227), status
  colours for state, theme hues for data.
- **Codes first** (`TXx Hottest day`), **numbers by the rules** in `DESIGN.md`,
  Typography (once #226 lands, through its formatting module only), **slope, 95% interval
  and significance** wherever there is a trend, **axes** on every chart that is read, the
  **provenance line** on workspace and station pages.
- Density as drawn: 30–34px rows, one line each; data pages use the width.
- Keep what the board can't show: no-JS fallbacks, keyboard use, chart text summaries and
  table views, logical CSS properties, no inline scripts or styles (CSP), strings through
  `{% translate %}`. Run `scripts/build-css.sh` after changing classes.
- Build only what the ticket covers. A board often shows parts of other tickets (the
  context bar, short names, number formats); use what has landed, leave the rest as it is,
  and say so in the Design check.

## 3. Before the pull request: compare

1. **Screenshot the built page** with `packages/climpact-web/tests/browser.py`'s `Chrome`
   (`media(prefers_color_scheme=...)`, `viewport(1280, ...)`, `screenshot`), in light and
   dark, plus 375px when the ticket touches the phone layout. Use the data the board
   shows: the Sydney sample; `reference/input/qc_stress_1961-2020.txt` for an amber
   Quality; the sample with TX and TN swapped on every 100th row for a red one.
2. **Compare with each board, region by region,** against the notes from step 1.4: order,
   columns, copy, density, states, both themes. If your browser is signed in to the
   canvas, screenshot the board at the same width; otherwise compare against the board's
   markup.
3. **Sort every difference:**
   - **Required by the rules** (a token instead of a canvas colour, the system font, an
     accessibility or no-JS need): fine; list it.
   - **Not built yet, belongs to another ticket:** fine; list it with the ticket.
   - **Anything else** (a region, column, wording or state that differs): fix it, or ask
     the maintainer before the PR and list it as "needs approval". Never leave one out of
     the list.
4. **Update `DESIGN.md`** in the same branch: take away the Target marks this ticket
   meets, describe the code as it now is, and add new patterns to Components and
   `/patterns/`.

Don't edit the canvas. If the design should change, say so in the PR or to the
maintainer, who updates the board.

## 4. The pull request's Design check

Add this section to the PR body, after "Screenshots" (`CLAUDE.md` on publishing
screenshots with `scripts/pr-screenshots.sh`; include light and dark of the main screen):

```markdown
## Design check
Boards: `Quality.dc.html` (light and dark). DESIGN.md: Layout, Components (Verdict strip, Coverage strip), Rules.

- Matches the board: <regions, columns, copy, states checked>
- Differs, required by the rules: <item: reason>
- Not built here: <item: ticket>
- Needs approval: <item: why> (or "none")

DESIGN.md: <Targets removed, patterns added>
```

The ticket's acceptance criterion "matches its boards in light and dark" is met only when
"Needs approval" is empty or the maintainer has approved each item.

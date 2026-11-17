# Climpact web design language

The design language of the web app (`packages/climpact-web`). It records what the
interface is built from and the rules a change has to keep, so a design review has
something to check against. How the tokens, theme switch, charts and accessibility tests
work is in [`TECHNICAL.md`, "Design system"](TECHNICAL.md#design-system); this file does
not repeat it.

A rule not yet met everywhere is marked **Target**, with the ticket that brings the code
in line; the text around it describes the code as it is. The rules come from three rounds:

1. The UX redesign (#171, phases 1 and 2, #172–#179 and #196–#203), whose mockups are in
   `docs/design/` (superseded, kept for the record). Phase 2 left no Target.
2. **The expert workspace direction (#230), decided on 17 November 2026.** Its Targets
   carry the ticket that builds them. Where it changed an earlier rule, the rule below
   says the new thing and marks it Target.

### The expert workspace direction (#230)

- **Experts first.** The users already work with ET-SCI. Help and plain names are there
  on request, never in the way.
- **Codes first.** `TXx`, `R95p` lead, in mono; a short name follows ("TXx Hottest day").
- **Show the statistics.** Every trend is Sen's slope per decade, its 95% interval and
  whether it is significant (the interval excludes zero). Method and years used are one
  click away. No p-value: Climpact computes none (`climpact/trends.py`).
- **Desktop first,** at 1280–1600px; phones get a usable stacked layout.
- **Everything is a workspace.** A workspace holds stations and the settings they share.
  One station is a workspace of one and opens straight to the station. Every station and
  batch belongs to a workspace since #253, and the base period, thresholds and index
  settings are the workspace's since #254: a change recalculates every station, and can
  be undone while it is on the way. A batch fills its workspace since #255: its stations
  are the workspace's, and its results page stands in as the workspace page until #234.
  Still to come: the workspace URLs (Target: #256), and Workspaces in place of Your
  calculations (Target: #233, #234, #242).
- **Coming back.** Workspaces belong to the browser (hosted, deleted after the retention
  period) or the computer (local: kept until deleted, and the retention notice says so).
  A saved workspace file rebuilds one anywhere (Target: #240).
- **System fonts.** No web fonts (CSP, the bandwidth budget, offline use); tabular
  figures for numbers and `--font-mono` for codes, dates and numbers in tables.

Kept from phase 2: **primary buttons are ink** (near-black, near-white in the dark
theme), and **a station's title is the station name** the user gives, not the file name.
The Inputs panel is replaced by workspace settings and the station's provenance line
(Target: #231, #234).

## The design canvas

The screens of #230 are drawn on a design canvas, in light and dark:
<https://claude.ai/artifact/7zEuwY1xA264zmxpq3GFdu> (private: open it signed in to the
maintainer's account, or read it with the Artifact tool). Each board is a file under
`project/`; read one with the Artifact tool's `read` action and its `path`, for example
`project/Quality.dc.html`. The dark boards (`*Dark.dc.html`) show the same file with the
theme switched.

| Board | Screen | Tickets |
| --- | --- | --- |
| `Main.dc.html` | The brief: users, principles, decisions | #230 |
| `Flow.dc.html` | The flow, from the landing page to an index and back | #230, #231 |
| `Landing.dc.html` | Landing page (first visit; returning bar as a tweak) | #242 |
| `Start.dc.html` | Get started | #242, #233 |
| `WorkspaceList.dc.html` | Workspaces (replaces Your calculations) | #242, #240 |
| `AddStations.dc.html` | Add stations: drop zone and review table | #233 |
| `Workspace.dc.html` | Workspace overview and the trend grid | #234, #238 |
| `Calculate.dc.html` | The workspace overview while its stations calculate and once they have finished (replaces batch results and the batch steps; three states in the board) | #234, #231 |
| `Quality.dc.html` | A station's Quality as a worklist | #235, #222 |
| `Results.dc.html` | A station's Indices: filter rail, table, detail pane | #236, #218, #226 |
| `Index.dc.html` | One index | #237 |
| `Files.dc.html` | Workspace Files and provenance | #239 |

**What a board is, and is not.** A board fixes a screen's layout, content, order, density
and wording. It is not the spec for:

- **Colours and type.** The canvas has its own colour values and draws in IBM Plex. Build
  with the app's tokens ([Colour](#colour)) and the system fonts.
- **Data.** Values, station names and "Mock-up" banners are illustrative.
- **Behaviour the rules below decide** (accessibility, no-JS fallbacks, CSP, help).

**When the canvas and this file disagree,** this file wins on rules and tokens, the
canvas on a screen's layout and content. A real conflict goes to the maintainer; don't
pick one silently. The canvas is read-only for implementers: a change to the design is
agreed with the maintainer, who updates the board.

## Who it is for

**First, people who already speak ET-SCI:** climatologists at national meteorological
services producing monitoring and workshop outputs, and researchers running many
stations, comparing them and citing the method. Then sector analysts (health,
agriculture, water) after a few indices, and students and workshop trainees, who need
the help, on request. Many read English as a second language, some work on slow or
metered connections, and some run the app offline on their own computer. They come with
four questions:

1. Are these my stations, described correctly? (names, coordinates, base period)
2. Is each station's data fit to use, or should I fix the file?
3. What has changed in each station's climate, and how do the stations compare?
4. Where are the files, and the settings that made them?

Screens are organised around these questions, not around the stages of the calculation.

## Visual theme

**Calm, dense, precise: a scientific instrument.** Neutral surfaces, ink for actions and
a strong type hierarchy, so the data carries the colour. Tables before prose: a screen
answers in one line and then shows the data, with the statistics an expert needs beside
each number. It replaces the R Shiny app (shinydashboard boxes, a sidebar menu, tabs as
steps). System fonts only and no web fonts, for bandwidth, offline use and every script
the operating system supports.

## Colour

Tokens live in `core/tailwind/theme.css` (light) and the `@variant dark` block of
`core/tailwind/base.css` (dark). Every colour token has a dark value. Components use
tokens only: a test fails on a hex colour outside the two token blocks.

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| `--color-page` | `#f5f7f9` | `#0d1218` | Page background |
| `--color-surface` | `#ffffff` | `#151c24` | Cards, panels, inputs |
| `--color-surface-sunken` | `#eef2f5` | `#0a0e13` | Table headers, wells |
| `--color-text` | `#16202b` | `#e5ebf1` | Body text |
| `--color-text-muted` | `#4d5966` | `#a3afbb` | Hints, notes, captions |
| `--color-border` | `#d8dee4` | `#2b3540` | Dividers, card edges |
| `--color-border-strong` | `#78838f` | `#7a8794` | Input borders (3:1 against surface) |
| `--color-ink` | `#111827` | `#e6eaef` | Primary buttons, the current tab and step, running state |
| `--color-ink-hover` | `#374151` | `#c3cad3` | Hover on ink |
| `--color-ink-contrast` | `#ffffff` | `#0e1218` | Text on ink |
| `--color-link` | `#1f55a3` | `#8db6f2` | Links, underlined (#227) |
| `--color-link-hover` | `#173f7a` | `#b8d0f6` | Hover on a link |
| `--color-brand` | `#0a5aa8` | `#6db3f2` | The logo only |
| `--color-focus` | `#0b57d0` | `#8ab4f8` | Focus ring |
| `--color-selected` | `#eaf2ff` | `#1c2a3d` | Selected rows, the targeted help topic, text selection |
| `--color-success` / `-soft` | `#17773a` / `#e7f4ea` | `#5cc97e` / `#10291a` | Passed, done |
| `--color-warning` / `-soft` | `#8a5300` / `#fdf3dc` | `#e9b04a` / `#2e2410` | Worth a look, out of date |
| `--color-danger` / `-soft` | `#b3261e` / `#fbeae8` | `#ff8c82` / `#351513` | Errors, destructive actions |
| `--color-heat` / `-soft` | `#c2410c` / `#fff1e8` | `#f2895a` / `#3a1e12` | Theme: Heat |
| `--color-cold` / `-soft` | `#196cd3` / `#eaf2ff` | `#6aa8ff` / `#14253d` | Theme: Cold |
| `--color-rain` / `-soft` | `#077c6e` / `#e5f5f2` | `#3cc3ae` / `#0f2d29` | Theme: Rain |
| `--color-drought` / `-soft` | `#693b04` / `#f6efe6` | `#fcca93` / `#332619` | Theme: Drought |
| `--color-other` / `-soft` | `#222a36` / `#eef1f4` | `#828c97` / `#1c232c` | "Also measured" (neutral) |

**Each colour has one job** (#196):

- **Ink** for actions: primary buttons, the current tab and step, the running state
  (progress bars, spinners, the current stage). Interactive icons (a disclosure's
  chevron, a dropzone's icon) are ink too.
- **Blue for links** (#227), as on the canvas: `--color-link`, underlined, darker on hover
  (lighter on dark) with a thicker line (`--color-link-hover`). At least 4.5:1 on the
  page, surface, sunken surface, the selected tint and the status tints, in both themes.
  Links styled as buttons stay buttons (ink or secondary). The header's links are quiet
  text (muted, the current one ink).
- **Brand blue** only for the logo, focus rings and selection.
- **Status colours** (success, warning, danger) only for the verdict and run state. Info
  is neutral: an info alert or badge is ink on the sunken surface.
- **Theme hues** mark data. Heat, Cold, Rain and Drought each have one hue, and the
  themes under "Also measured" share a neutral. The hue colours the dot of the
  filter rail's theme and of an index's row, the sparklines, the detail pane's chart
  line, and the index page's theme pill, chart line and open points, with its running
  mean a step towards the text colour (`color-mix`, #237) (a `hue-<theme>` class on the
  block, from `stations.themes.hue_of`). The theme's name is always beside the hue.
- Hover is a neutral change (the sunken surface, or a thicker underline on links; a link
  takes its hover shade), never a colour of its own.

**Charts** have their own tokens (`--chart-*`): eight categorical slots in a fixed order,
never cycled; variable roles (`tmax` red, `tmin` blue, `prcp` green, checked as a set
for colour-vision deficiency), which the daily and quality charts keep: the theme hues
are for indices, the variable roles for the station's variables; trend, band, grid and axis; a five-step sequential and a
seven-step diverging scale for maps; the **trend scale** (#227: `--chart-decrease-2`,
`-decrease-1`, `-increase-1`, `-increase-2`, blue for a significant decrease and orange
for an increase, the strong step darker in light and brighter in dark; a cell's value is
written in it, in `--color-surface` on the strong steps and `--color-text` on the weak
ones); and the **coverage steps** (`--chart-coverage-1` to `-3`: complete, 1–3 days
missing, 4 or more, moving away from the surface in lightness). QC flags are hollow rings in ink, told apart by
shape rather than colour. `chart-palette.json` carries the same values (with `trend_scale` and `coverage`) to the static
plots and the PDF report.

**Severity colours mean severity.** Danger is for something that stops the user or is
almost certainly wrong. Warning is for something worth a look. Use neither for "the
check found something" on its own (see Rules).

**From the canvas to the tokens.** The canvas's colours are close to these but not the
same values; build with the tokens:

| On the canvas | Token |
| --- | --- |
| Page background, panel, sunken panel and table header | `page`, `surface`, `surface-sunken` |
| Text, secondary text, muted text | `text`; `text-muted` for both lower levels |
| Hairlines and frames; input and button edges | `border`; `border-strong` |
| Selected row (tint and its ink edge) | `selected`, with an `ink` edge |
| Ready, Usable, Fix first and Checking badges | `success`, `warning`, `danger` on their `-soft` tints; Checking is info (ink on `surface-sunken`) |
| Heat, Cold, Rain, Drought, Also measured | `heat`, `cold`, `rain`, `drought`, `other` |
| The trend scale: two steps of increase (orange) and of decrease (blue) | `--chart-increase-1`, `-2` and `--chart-decrease-1`, `-2`; not significant is a dashed `border-strong` edge on the surface, no fill |
| Coverage: complete, 1–3 days missing, 4 or more | `--chart-coverage-1` to `-3` (the coverage strip, #235) |
| Links (blue, underlined) | `link`, `link-hover` |
| The "Mock-up" banner | Not part of the design |

## Typography

`--font-sans` is the system UI stack; `--font-mono` is used for index codes, file names
and dates in tables. The scale is set by hand (about 1.125 to 1.25 between steps),
font size only; line height is `--leading-normal` 1.6 for text and `--leading-tight`
1.25 for headings.

| Token | Size | Role |
| --- | --- | --- |
| `--text-hero` | clamp(2rem … 3rem) | Home page heading only |
| `--text-2xl` | 2rem | Page title (h1) |
| `--text-xl` | 1.5rem | Section heading (h2) outside a station; a station's name in its context bar |
| `--text-lg` | 1.25rem | Card title, stat value; a section heading (h2) in a section header and on a station's pages |
| `--text-md` | 1.125rem | Lead paragraph under a title |
| `--text-base` | 1rem | Body, controls |
| `--text-sm` | 0.875rem | Table cells, hints, help links |
| `--text-xs` | 0.8125rem | Badges, captions, footer, group labels, the Help pill |

Weights: 400, 500, 600, and 650 for bold. Headings never skip a level.

Small uppercase labels name groups (`group-label`, stat labels: `--text-xs`, 600,
letter-spacing 0.06em, muted); they group without adding boxes. A page's answer is a line,
not a band: Quality's verdict strip (#235), and on a station's Indices one line above the
table ("**22 of 80** indices with a significant trend · TMm +0.19 °C/decade", #236), its
count in bold and the mean temperature's trend muted.

**Numbers** follow one set of rules (#226), written by one module,
`core/numbers.py`, which every page, chart summary and server-drawn chart uses
(`charts.js` repeats the minus and zero rules for its axes, read-out and table):

- **U+2212 for minus** (`−0.22`), in values, intervals, axis ticks and the index names
  that hold a number (`TN below −2 °C`); never "−0.0": a value that rounds to zero has no
  sign (`0.00`). Text the user types or a file holds keeps the hyphen-minus (`-99.9` for
  a missing value), and downloads are written as the files are.
- **Slopes per decade, signed, with their units:** `+0.21 °C/decade`,
  `+5.15 days/decade`; a trend of a percentage is in percentage points, written `pp`
  everywhere (`+1.31 pp/decade`, spelt out in an `abbr` where the markup allows). In
  running text, "rose by 0.19 °C per decade".
- **Places:** two for slopes and intervals in °C, days, % and the unitless indices, one
  in mm and degree-days (`numbers.slope_decimals`); rounded half up from the value as
  written. Intervals are two unsigned bounds, `−0.22 to 0.31`. Anomalies have one
  decimal and a sign (`+0.4`). Other values keep up to two places (one from 10), without
  trailing zeros; the Quality tables show the file's own precision, except the days
  around a finding, which have one decimal (`numbers.fixed`, #235).
- **Coordinates** are `33.86° S 151.21° E`.
- **Counts** are grouped, `65,720` (`numbers.grouped`; Quality's tab, #222).
- **A no-break space** joins a value and its unit (`45.8 °C`; a percentage takes none,
  `12.5%`). It is joined in code (`numbers.with_unit`), never written in a message
  (#205).

In templates, `{% load ui %}` gives `{{ value|decimals:4 }}` and
`{{ lat|coordinates:lon }}`; anything else is formatted in the view with `numbers`.

**Codes and figures (#227).** Numbers in tables, statistics and the provenance line use
tabular figures (`font-variant-numeric: tabular-nums`); index codes, dates, file names
and the provenance line are `--font-mono`. The data table sets its `num` and `code`
cells so, in `--text-xs`; other cells are `--text-sm`. Quality's tables are data tables
(#235), and so is the Indices' (#236), whose headers are sans and whose Index cells are
`--text-sm`. **Target (#234, #239, #242):** each other page's tables move to the data
table with that page.

## Layout

- **Width:** content up to `--container-content` (72rem), reading text up to
  `--container-prose` (42rem); a data page (a station's sections: `data_page` in its
  context) up to `--container-data` (92rem, #227).
- **Spacing:** one step is 0.25rem (`--spacing`), a 4px grid. Common steps: 2 (0.5rem)
  inside controls, 4 to 5 (1–1.25rem) inside cards, 8 to 12 (2–3rem) between sections.
- **Breakpoints:** `sm` 40rem, `md` 52rem, `lg` 60rem, `xl` 64rem. Logical properties
  only, so right-to-left scripts work (checked by `test_static.py`).
- **Page frame:** header (#227: one row about 48px high across the window: the logo and
  "Climpact", which go to the landing page; Workspaces and Gridded; then Index reference,
  Help and the theme toggle at the end. Below 600px the destinations and Index reference
  are in the Menu, and so is the theme toggle, #203. Workspaces opens the list of
  calculations until #242, and is current on station and batch pages too) → step
  indicator for the
  batch and gridded flows → title and one-line lead → content → footer. A new station is
  one narrow page (40rem, centred; #201): "New station", a lead, two numbered steps (Your
  file, Station details) divided by hairlines, then the one call to action. A station is a
  workspace instead: its context bar (#227: its name as the h1, the provenance line, the
  page's actions, then the section tabs, Quality, Indices and Files), then the Inputs
  panel and the section's content side by side (the Indices keep the Inputs bar at every
  width, #236). An index's page (#237) is a drill-down from the Indices instead: its
  context bar has the breadcrumb (station / Indices) with the previous and next index,
  the index as the h1 with its theme, its definition and the provenance line, and its
  files; no tabs and no Inputs panel, and it scrolls away with the page (`flow`), so
  the chart has the width. The h1 is the station name the user
  gives (the file name until there is one). The context bar stays in view as the page
  scrolls (not in a window under 30rem high); the page's scroll padding keeps a focused
  element out from under it (WCAG 2.4.11). On phones only the tabs and the Inputs bar
  stay in view, and the name scrolls away (#203). The Inputs panel
  (16rem) sits at the inline start, in view under the header as the page scrolls, where
  the content has at least 52rem (a container query, so the help drawer counts);
  narrower, the Inputs bar under the tabs takes its place (#203), and without JavaScript
  the panel comes above the content. Quality (#235) is the verdict strip, the coverage
  strip, then the worklist: the "Look wrong" and "Worth a look" tables with the detail pane
  beside them; the checks that found nothing in one line; then the daily charts with the
  flags and the distributions as disclosures, and one line with the thresholds and the
  link to Files. While the checks run, what is in the file ("Your data", #198) takes the
  worklist's place.
- **Sections:** one surface level. A page's sections sit on the page, 48px apart
  (`stack--xl`), each under a section header; a box marks only one object (a chart, a
  data table, a detail pane, a progress card).
- **Controls:** `--control-height` 2.75rem (2.25rem small), so touch targets reach 44px.

**The workspace frame (#230).** The station frame above gives way to this one as #231,
#234 and #236 land; the boards on the canvas show each page. #227 built the
header (above), the context bar, the data width and the data table; #235 Quality's
strips, worklist and detail pane.

- **Context bar** under the header, on every station page (`components/context_bar.html`):
  across the window on the surface over a hairline, the title (the station name), one
  mono line of provenance (coordinates, years and their count, base period, "ET-SCI
  defaults" or how many settings are not the default, the climpact version;
  `stations.workspace.provenance`), the page's actions at the end, then the tabs.
  Quality's line describes the data the checks read instead (#235, as its board draws
  it): the coordinates, the years, the days and variables in the file ("21,915 days ·
  PR TX TN") and the file's name.
  An index's page (#237) uses the breadcrumb (station / Indices) and the previous and
  next index, named codes first. A batch's station starts the breadcrumb with its
  workspace, which leads to the batch results until #234 (#255). **Target:** the
  workspace in the breadcrumb of every workspace of several stations, and the
  previous and next station on a station's pages, once stations belong to a workspace
  (#231, #234); "Edit
  inputs" or "Workspace settings" on the provenance line, which replace the Inputs panel
  (#231, #234); a workspace's own bar, with the station count and deletion date and the
  tabs Overview, Compare an index and Files (#234). The tabs are Quality, Indices (Results
  until #236) and Files; Quality's shows its verdict and count, "Usable · 21" (#222).
- **Data pages use the width.** Desktop first: a station's pages fill the window up to
  92rem (`--container-data`), rather than the 72rem content width, which stays for
  reading pages.
- **Panes:** a filter rail at the inline start (about 14rem), the table, and a detail pane
  at the inline end that stays in view as the list scrolls (`detail-pane`; on Quality,
  #235, 22–30rem, side by side from a 56rem container, sticky under the context bar and
  scrolling inside itself when taller than the window). Narrower, the rail goes above the
  table and the detail after the list, with "Back to the list". The Indices (#236): the
  rail 10rem and sticky, the table, the pane `clamp(17rem, 22%, 26rem)`, side by side from
  a 68rem page; from 48rem the rail beside the table and the pane under it; narrower, the
  rail above (its themes a wrapping row) and the detail after the table. The Inputs bar
  replaces the panel there at every width, so the three have the width.
- **Data tables sit in one frame** (a `border` edge and `--radius-sm`), with hairline rows
  of 32px and a header row on the sunken tint: the exception to "a box marks only one
  object", because the table is one object (`components/table.html`, `table--data`).
  Quality's are (#235), and the Indices' (#236): at 1280 x 1180px (the board's size) 26
  of the Sydney sample's indices are in view, without sideways scroll. **Target:** each
  other page's tables move to it with that page (#234, #239, #242).

## Depth and shape

| Level | Token | Used for |
| --- | --- | --- |
| 0 | none | Page background, a page's sections, content inside a card |
| 1 | `--shadow-raised` | Cards and panels on the page |
| 2 | `--shadow-overlay` | Dialogs, toasts, the tour |

Radii: `--radius-sm` 4px (small elements), `--radius-md` 8px
(buttons, inputs, inner boxes), `--radius-lg` 12px (cards), `--radius-full` (badges,
pills). Motion: one duration, `--duration` 160ms, for hover and focus changes; under
`prefers-reduced-motion` every animation and transition is cut to an instant
(`base.css`).

## Components

Templates in `core/templates/components/`, styles in `core/tailwind/components/`, all
shown on `/patterns/`. Use them rather than composing new markup.

| Component | Level | Purpose | Variants |
| --- | --- | --- | --- |
| `button` | Primitive | Action, or a link styled as one. Primary is ink | primary, secondary, ghost, danger; lg, sm; icon, icon only |
| `badge` | Primitive | Status in words, never colour alone. Info is neutral; `hue` is a theme's pill (its hue on its tint) | info, success, warning, danger, hue |
| `hue-dot`, `hue-*` | Primitive | A theme's colour: `hue-heat`, `hue-cold`, `hue-rain`, `hue-drought`, `hue-other` on a block set `--hue` and `--hue-soft` for what is inside it; `hue-dot` is its dot, always beside the theme's or index's name | — |
| `stat` | Primitive | One number with label and note; the label is a group label | — |
| `group-label` | Primitive | Small, uppercase, muted text that names a group without a box ("Your inputs") | — |
| `section-header` | Component | A section's heading, an optional muted note (`section-header__note`), then the Help pill (`{% section_help %}`) at the end of the row. The pill is 30px high with a ringed question mark and a word: "Help", or a question where it helps (`label="How to read this"`). `quiet=True` makes it a quiet link in the text's size (`help-link`, #235: "How the checks work" on Quality), the same link and drawer | with note, with a specific label, quiet |
| Quality worklist | Pattern | Quality (#235, the Quality board; `stations/_qc_review.html`): the verdict strip and the coverage strip, then "Look wrong" as a data table grouped by check (a group row on the sunken tint, "TN ≥ TX 10"; then Date, Var, Value with its unit, Check, Detail: what the value is checked against, "TX 8.2 °C", "limit 200 mm"; each check's first ten rows, then "All 213 rows of TN ≥ TX"), and "Worth a look" (Check, Var, Values, When: "Mostly May and June", "All year"; By month: twelve small bars, an empty month a thin mark), each a framed table with its heading inside the frame and "How the checks work" as a quiet link. Rows 30px, one line each. Each row's first cell links to `?show=<id>`, so it works without JS and can be linked; with JS the detail changes in place and is announced, the row has the selected tint and an ink edge (`is-selected`, the link `aria-current`). The detail pane beside the tables: for a finding, its date and check in mono, the sentence ("TN 9.5 °C is above TX 8.2 °C", codes first), a chart of the 15 days around it with axes (three values, three dates, the day as a band, the value ringed, a legend "TX °C", "TN °C", "April 1962, daily"), the days-around table (one decimal; the day in bold on the warning tint, other flagged days on a lighter one), "Show on the daily chart" and its line in the file; for a group or a check's every row, its counts by month and its rows, paged. The first finding is selected by default | finding, group, every row of a check |
| Verdict strip | Component | A judgement in one line (`components/verdict_strip.html`, #235): on the status's soft tint with a hairline in its hue, the level in bold and one sentence as the heading ("**Usable.** 21 values look wrong; the indices can run with them as they are."), the counts on one mono line under it, the decision's small buttons at the end. On Quality: "Flagged values (CSV)", "Replace file", "Go to indices" (primary); on red "Go to indices anyway" and "Replace file" (primary); no buttons while the checks are out of date | ready, usable, fix |
| Coverage strip | Component | Missing days per year for each variable (`components/coverage_strip.html`, #235): in a frame, "Coverage" with a muted note (what the annual completeness rule makes of the years) and the key; a row per variable, its code, a cell a year in the three coverage steps (an SVG, `aria-hidden`) and its total; the years under them, evenly spaced. The table view follows as a disclosure. Narrower than 36rem the rows scroll | — |
| Detail pane | Component | The selected row's detail beside its table (`detail-pane`, #235, and the Indices', #236): a frame on the surface, in view under the context bar as the list scrolls and scrolling inside itself; after the list on narrow screens, with "Back to the list", which returns focus to the row | — |
| `field`, `field_errors` | Component | Label, short hint, input, unit, inline error; no help link of its own | narrow, with unit |
| `dropzone` | Component | File input with drag and drop; works without JS | — |
| New station steps | Pattern | The New station page's steps (`setup__step`, #201): a number in an ink circle (a CSS counter, so no text to translate; a success tick once done), the step's section header and its fields, each step under a hairline; then `setup__cta`, the one primary button and a muted note beside it on what it does and what keeps its default. No boxes: the file card is the only one | step done |
| File card | Component | The file read (`stations/_file_card.html`): its name, "✓ Read: first–last year, days" in success, and Replace (a file button inside the page's form) at the end; under it the days with data in each year, an SVG bar a year in success, amber (`--color-warning`) when the year misses more than 15 days (too many for annual index values), with a text alternative naming those years | gaps, no gaps |
| `file_button` | Component | A button that opens the file picker and sends the chosen file at once, for a second upload where a drop zone takes too much room; a file input and a submit button without JS. Unused since Quality's corrected file became the File sheet (#199) | primary, secondary; lg, sm |
| `form_errors` | Component | Error summary that links to each field, focused on load | — |
| `card` | Component | Grouped content; whole-card link | link, muted, with badge |
| `alert`, `messages`, `toasts` | Component | Page and transient feedback | info, success, warning, error; dismissible; live |
| `disclosure` | Component | Content that opens in place (`<details>`): a row between hairlines, not a box | — |
| `dialog` | Component | Native modal with focus kept inside | confirm, danger |
| Inputs panel | Component | Everything the user gave, beside a station's sections (`stations/_inputs.html`): a group label, then each input as a row of its name (muted), its value (semibold) and one link at the end, Edit or Replace, on a sunken tint without a border. The thresholds and index settings read "Defaults" or how many were changed ("2 changed"). An input changed since the checks or results shown has the warning tint and says "changed" after its name; the run of the new inputs shows its progress in a box beneath the list, polled until it finishes. While that run is a change to the workspace's settings (#254), a small secondary "Undo the change" under it, a plain form (`stations/_undo_form.html`). Sticky under the context bar when beside the content | changed; with a run; with undo |
| Inputs bar | Component | The Inputs panel in one line, under the workspace tabs where the content has less than 52rem (`stations/_inputs_bar.html`, the mockups' `.inputsbar`; #203): "Inputs:" then the base period and "defaults" or how many settings are not the default, then each input changed since what is shown (warning colour, and the bar takes the warning tint) and each run under way, and a small secondary Edit at the end, after a small secondary "Undo" while a change to the workspace's settings can be undone (#254). Edit opens the Inputs sheet: the panel's list in a side sheet, which on a phone fills the screen; each input's Edit there opens its own sheet over it, and Escape steps back to the list, then the bar. Only with JavaScript; without it the panel shows above the content. On a phone it reaches the screen's edges, under a hairline | changed; with a run; with undo |
| Page menu (⋯) | Component | On a phone the page's actions (Results: the sector comparison, Download all) move from the context bar into a ⋯ button at the end of the name's line (`page-menu` in `components/context_bar.html`; #203). A disclosure, not an ARIA menu: a native `<details>` whose summary is the button ("Page actions" for screen readers), so it works without JavaScript; Enter or Space opens it, Tab goes through the actions (full-width buttons, one a line, in a raised panel), Escape closes it and returns focus to the button, and a click or focus elsewhere closes it (`js/context-bar.js`) | — |
| Side sheet | Component | One input's form at the inline end, the screen's full height (`stations/_input_sheets.html`, `js/sheet.js`): a title and close button, the form's fields, what applying will update in a warning tint (`impact`), then one primary button, Apply, and Cancel at its foot. **Modal**, unlike the drawer: the form is being edited and applying starts a run, so it is a native `<dialog>` opened with `showModal()`: a backdrop, the page behind inert, focus on the first field and kept inside, Escape, Cancel, close or a click on the backdrop closes it and discards what was typed, and focus returns to the Edit link. Without JS, Edit links to the same form on its own page; a form with errors returns there. A long form (the index settings) scrolls inside the sheet with Apply kept in view at the foot, rather than widening the sheet; its groups are divided by rules, and their help opens in place, since the drawer would be behind the modal | base period, index settings |
| `drawer` | Component | A section's help in a side panel, opened by the Help pill of the section's header (`{% section_help %}`). Not modal: no backdrop, no focus trap. Beside the content from 64rem, below it on narrower screens. Escape or close returns focus to the pill. Without JS the pill links to the same help on its own page. Help at the end of the app bar (a quiet link since #227) opens the page's guide | — |
| `table` (data table) | Component | The framed dense table (#227, `table-wrap--data`, `table--data`): one frame, hairline rows 32px high and one line each, a sticky header on the sunken tint, `num` and `code` cells in mono with tabular figures, the selected row (`aria-current`) in the selected tint with an ink edge, in a keyboard-scrollable region. The plain `.table` (hairline rows, no frame) stays for tables inside a card, a disclosure or a chart until each page moves (Layout) | empty state, selected row |
| Context bar | Component | Under the header on a station's pages (`components/context_bar.html`, #227): a breadcrumb with the previous and next item (when given; an index named codes first, #237), the title, a lead line (`lead_template`), the mono provenance line, the page's actions, the tabs and the Inputs bar under them; across the window and sticky (`js/context-bar.js` keeps the scroll padding to its height). `title_template` draws a title of its own (an index's name and theme pill); `flow` keeps it in the page's flow, for a page without tabs (an index's); `static` shows it in place on `/patterns/` | breadcrumb, sub-page title (a line, not the h1), own title, flow |
| `index_name` | Primitive | An index named codes first (#218): the code in mono, without the code background, then the short name, "TXx Hottest day". In a page title the name is a step lighter. The catalogue puts them in two columns, Code then Index | title |
| `summary_list` | Component | Key–value pairs | — |
| `tabs` | Component | ARIA tablist; all panels show without JS | — |
| `workspace_tabs` | Component | A station's sections as tabs under its name, in the sticky context bar (`stations/_workspace.html`). Each is a page of its own, so they are links in a named `nav` with `aria-current="page"`, not a tablist; Tab moves between them. Each has a status: an icon of its own shape and a word (done `check-circle`, needs attention `warning`, out of date `clock`, running `refresh`, not started `circle`, not available yet `lock`). The word shows for the states that need the user and is read by screen readers for all. Quality's tab reads like its verdict (#222): "Checking…" (`refresh`) while the checks run, then the verdict strip's level and an icon, Ready `check-circle`, Usable `warning` or Fix first `error`, as a small pill in the status colour on its soft tint, with the count of values that look wrong after a middle dot ("Usable · 21", read as "Usable, 21 values look wrong"); a failed check stays "Needs attention". On a phone (under 40rem) the verdict is its icon on the tint, so the three tabs stay on one line at 320px; the word and count are still read. A section not available yet is not a link. Looks like `tabs` | — |
| `progress`, `stages`, `skeleton` | Component | Running jobs and loading content. The label is the stage in words, then the percentage ("Calculating the indices", 7%): `jobs/stages.py` maps each stage to its words and never shows its ids (module, index or file, #226) | determinate, indeterminate |
| `chart_frame` | Pattern | Chart with title, text summary, legend, zoom, PNG/SVG, table view, CSV (Quality's daily charts, the gridded series; the index page draws its own since #237) | — |
| Segmented control | Primitive | One choice of two or three side by side (`segmented`, #237): links in one strip of `border-strong` edges, the current one ink (`aria-current`), so each works without JavaScript. The index page's Values / Anomaly and Annual / Monthly | — |
| Index page | Pattern | One index (#237, the Index board; `stations/result.html`, `stations/index_page.py`): the context bar (breadcrumb station / Indices with the previous and next index; the index as the h1 with its theme pill; its definition, unit and R's name, with "About this index" as a quiet help link; the provenance line; CSV, "PNG (R style)" and "Copy citation", a disclosure without JavaScript); then the chart in a frame beside the Trend statistics (Sen's slope, 95% interval, Significant, Years used, Base-period mean, Record; why any year was left out; the method); then the values as a framed data table, scrolling inside its frame (Year, the value with its unit, Anomaly, Rank, the date of the maximum or minimum where the core gives it, Note: Record or why the value was left out), most recent first. The chart is drawn on the server: the base period as a band, round values and years on the axes, the y axis titled with the code and units, Sen's slope's 95% interval as a shaded bow tie through the slope's middle, the values (bars for SPI and SPEI) with gaps, the 11-year running mean, Sen's slope dashed, each value left out an open point at the base-period mean; the segmented controls switch Values / Anomaly in place (`js/index-page.js`) and Annual / Monthly by link. Below 32rem the chart scrolls inside its region | annual, monthly, anomaly, bars (SPI), day of the year (TX95t: no rank or record), daily (EHF, ECF: the ten highest days) |
| Filter rail | Component | The Indices' filters at the inline start (`filter-rail` in `stations/_indices.html`, #236): "Find", a search that matches the code, the short name and R's names; "Theme", a column of pills (All and each theme with its dot and a mono count; the selected pill ink); "Significant only"; one muted line defining significant ("the 95% interval of Sen's slope excludes zero"); the help as a quiet link; at its foot, under a hairline, the settings line. A GET form without JavaScript, filtering as you type with it (`js/results.js`). Above the table on narrow pages, the pills in a wrapping row | — |
| Indices table | Component | Every index in one data table (`stations/_indices.html`, #200, #236): Code (the theme's dot and the code, a link to `?show=`), Index (the short name; an ellipsis when long), Unit, Slope / decade ("+1.31 pp" for a percentage), 95% interval, Sig. ("yes" with the dot, a dash read "no"), the series as a sparkline headed by its years, Mean. A line that answers above it and the live line ("Showing 80 of 80 indices. Sorted by …"). Code, Index, Slope and Sig. sort it: links without JavaScript, buttons with it, `aria-sort` on the sorted column. Every row is in the page, the filtered ones hidden. On a phone each row is two lines | filtered, sorted, selected row, no match |
| Index detail | Component | The selected index in the detail pane (`stations/_index_detail.html`, #236): code and theme in mono, the short name as a heading, the definition; the series drawn on the server with axes (three values, three years), the base period as a band and Sen's slope dashed (`index_detail.chart`), its caption and text alternative; then Slope, 95% interval, Years used and Method ("Sen's slope (zyp)"), one a line in a narrow pane; then "Open full page", CSV, PNG and "Monthly values" | with a trend, without, daily |
| `download_link` | Primitive | One file to download: a small secondary button with its format and size, the file named for screen readers | — |
| `spark` | Primitive | Decorative sparkline beside a trend given in words | line, bars |
| `steps` | Pattern | Where the user is in the batch or gridded flow; done steps link back. Not used by the station, whose sections are `workspace_tabs` (#179) | — |
| `stale_banner` | Pattern | Results kept on the page after an input changed: what changed, in words, and what happens next. An info alert with the new run's progress while it is on the way; a warning alert with one action ("Recalculate", or a link to fix the input) otherwise. The results below sit in a `stale-content` block: a dashed warning edge and greyed sparklines, the text at full contrast | updating, out of date |
| `empty_state` | Pattern | Nothing to show yet, with the next action | — |
| File group | Pattern | A long list of files behind a closed native `<details>` (`disclosure download-group`): the summary gives the group's name, the count and the total size, and opens to a table with a `download_link` per file; on phones each row becomes a short block. Each index section and the quality checks on Files; markup in `stations/downloads.html` | — |

Patterns built in a page's own templates, not yet in `/patterns/` (the Quality page,
`stations/templates/stations/_qc_*.html`, and the Indices):

| Pattern | Purpose | Built from |
| --- | --- | --- |
| Index chart | The index page's chart (#237), drawn on the server (`index_page.chart`, `stations/_index_chart.html`) in an 860 x 340 box, both views (values and anomalies) in the page. Its text alternative gives the values and the trend; the table under it is its table view and the CSV is in the context bar. | `chart_frame` for interactive charts |
| Finding chart | The days around one value in the Quality detail pane (#235), drawn on the server (`qc_review._chart`): a line per variable in its role colour, gaps where values are missing, the day as a band in the selected tint, the value ringed in `--chart-flag` as on the full charts, three value ticks and three date ticks. Its text alternative names the variables and dates; the days-around table under it is its table view, and "Show on the daily chart" leads to the full chart and its CSV. | `chart_frame` for the full chart |
| Settings line and panel | The settings in one muted line (at the foot of the Indices' filter rail since #236): the defaults, or what was changed, and a link that opens them in place. The form is one closed `disclosure` near the foot of the page, its groups divided by rules, not cards; one button at the end. `stations/_settings_form.html` | `disclosure`, `field`, `button` |
| Recalculation | A run that replaces results already shown, of the same inputs: its progress in a card with an ink edge above the results, which stay until it finishes. A failure says so in the same card, with "Try again". When the inputs changed (#179) the `stale_banner` takes its place, with the same progress inside. | `card`, `progress`, `stages` |

**Target: replaced by #230.** These stay until the ticket named lands, then go (the
theme tiles, `answer-band` and the Catalogue went with the Indices table, #236): the
Inputs panel and Inputs bar (by "Edit inputs" on the
context bar and workspace settings, #231, #234); New station steps, the File card and
`file_button` (by Add stations, #233); `steps` and the batch results page (by the workspace overview's run status line and
Stations table, #231, #234; board `Calculate.dc.html`); the
Settings line and panel (by workspace settings, #231). The Side sheet stays, for
workspace settings.

New patterns of #230 (Target; add each to `/patterns/` when it lands):

| Pattern | Purpose | Ticket |
| --- | --- | --- |
| Trend grid | Stations by indices, each cell Sen's slope; filled when significant on the trend scale, dashed when not, hatched without results | #238 |
| Interval plot | Each station's slope as a dot and its 95% interval as a line, with a zero line | #238 |
| Review table | Add stations' table of files: editable name and coordinates, read status, every problem at once | #233 |
| Stations table | A workspace's stations with their verdict, indices state and significant count; the indices state is live while a run goes (Done, Calculating with its percentage, Waiting, Not run with "Fix quality first", Failed with its fix) | #234 |
| Run status line | One line above the Stations table, never a panel: neutral with a progress bar while stations calculate (done of total, time left, Cancel); quiet when they have finished (how many, how long, Download all, Files); red only when a station failed, naming it, why and the fix. It stays until the workspace is next opened | #234 |
| Workspaces table | Each workspace with its stations, status summary and deletion date | #242 |

Every chart has a text summary, a table view and a CSV download, and can be used by
keyboard. This is not optional. **Every chart that is read has axes** with units and
years; sparklines are only for scanning, beside a number given in text.

## Rules

### Do

- **One primary action per view.** One `button--primary` per screen or decision area, and
  it says what happens next with a verb ("Go to indices", "Calculate"). A form's one
  submit button sits below the fields it confirms, never in the first screen above them.
- **Answer first, detail on request.** Lead with the finding or verdict, then the
  evidence; tables, distributions and file lists go below or behind a disclosure.
- **Keep severity in proportion to the data.** State counts against what was checked
  ("5 of 87,600 values"). Red means "fix this before going on", not "the check found
  something". The Quality verdict has three levels, with the limits in
  `qc_review.VERDICT_LIMITS`. Green, "Ready to use": nothing looks wrong. Amber, "Usable":
  up to 0.1% of the values look wrong. Red, "Fix the file first": more than that, or more
  than 10% of the years too incomplete for annual values. Values that are unusual but may
  be real are counted and never change the level.
- **Write short, plain sentences.** One idea per sentence; no chains of colons and
  semicolons; a verb on every button. Assume the reader is working in a second language.
  A page opens with one or two sentences; anything longer goes in its section's help.
- **Give units with every number,** including stats and trends (`pp`, percentage
  points, for trends of percentage indices), written by the rules in
  [Typography](#typography) through `core/numbers.py`, never formatted by hand in a
  template (#226).
- **Codes first, a short name second** (#218). `TXx Hottest day`: the code in mono, then
  the short name (`components/index_name.html`; in a table, a Code column then an Index
  column). R's long name is the index page's definition line ("Name in Climpact for R: Max
  TX"), when it differs. Never a name without its code, or a code without its name where
  indices are listed. Short names live in `help/indices.py` (`SHORT_NAMES`, approved by
  the maintainer on 17 November 2026), are translatable, and follow the number rules
  ("Days TN < −2 °C"); search finds the code, the short name and R's names. Charts keep
  their own titles and axis labels (`TXx: Annual warmest daily TX`), and output files
  follow R.
- **Show the statistics** (the Indices since #236, the index page since #237). Wherever
  there is a trend: Sen's slope per decade, its 95% interval, and significant yes or no (the interval
  excludes zero). Method and years used on the index page and in the detail pane. Never a
  p-value.
- **Keep the provenance in view.** Every station page has the provenance line in its
  context bar (#227). **Target:** the workspace pages too (#234), and every zip holds
  `climpact_run.json` (#239).
- **Separate what the user enters from what they get.** Inputs live in the Inputs panel,
  each edited in a side sheet that says what applying will update, with one Apply
  button; output pages hold no forms (#198, #199), only the decision, search and filters,
  and small actions such as Delete or Try again. Links elsewhere that change an input
  ("Replace file" on Quality's verdict, "Change the settings" on Results) open the same
  sheet. The base period, thresholds and index settings are the workspace's (#254): their
  sheets say so when the workspace has several stations, and that the change can be undone
  until its replacement is ready. **Target (#233, #234):** they are edited in the
  workspace's settings sheet; a station's name and coordinates are edited from "Edit
  inputs" on its provenance line.
- **Let the user take a change back.** A change to the workspace's settings recalculates
  every station; until that has finished, "Undo the change" beside its progress (the
  Inputs panel's runs, or the Inputs bar) puts the settings and the earlier results back
  (#254). One place per page, and a form that works without JavaScript. **Target
  (#234):** on the workspace's overview, the run status line shows the recalculation's
  progress and offers Undo (`Calculate.dc.html`).
- **Give each colour one job.** Ink for actions, blue for links, the
  brand blue for the logo, focus and selection, status colours for the verdict and run state, theme hues for data (see
  [Colour](#colour)).
- **Make help visible.** A section header is its title, an optional muted note, then a
  labelled Help button at the end of the row (a pill with a word, specific where it helps:
  "How to read this"). At most one per section, none on sections that explain
  themselves; Help at the end of the app bar opens the page's guide.
- **Group by what people ask about, and filter rather than narrate.** The Indices (#236):
  one line answers ("22 of 80 indices with a significant trend"), then the 80 indices as
  one table, filtered by theme (Heat, Cold, Rain, Drought, "Also measured" for the rest,
  each with its count), significance and search, and sortable by column, with no family
  accordions and no theme tiles. "0 of 80" is a finding too. Sentences are templates
  built from the data, never written by hand for a station. The theme mapping lives in
  `stations/themes.py`.
- **Keep it dense.** Rows of 30–34px, one line each, as the data table's 32px (#227, the
  Indices' since #236) and Quality's 30px (#235); a row never wraps to several lines to
  fit a sparkline: a long name ends in an ellipsis.
- **Never change the user's data, and say so.** The app reports; the user decides.

### Don't

- **Don't put cards inside cards.** One surface level on the page: sections are
  separated by space and a heading, not boxes. A box marks only something that is one
  object (a chart, a finding, a detail pane); a data table is one framed object (#227), a
  table inside a card or disclosure has hairline rows and no frame, and disclosures are
  rows between hairlines.
  Inside a card, separate groups with spacing and headings, not another border.
- **Don't offer downloads everywhere.** Files live in one Files section
  (`stations:downloads`); elsewhere at most one "Download all" link, plus each chart's own
  PNG/SVG/CSV. The Indices have the zip, primary in the context bar beside "Compare with
  sector data", the Files tab, and in the detail pane the selected index's CSV and PNG
  (#236, as the Results board draws it); Quality offers its flagged values as one CSV in the
  verdict strip (#235) and has one link to Files under the worklist; an index page offers
  its series' CSV, its R-style PNG and a citation (#237). **Target (#239):** Files is the
  workspace's (each station's files, the all-station CSVs and the provenance file).
- **Don't put a help link under every field.** One Help button per section opens that section's help
  in the drawer (in a modal sheet, a disclosure in place); a field keeps a hint only when
  its value isn't self-explanatory. Section
  help lives in `help/sections.py`: notes plus the fields' help topics.
- **Don't show a step's results before the step.** QC flags belong to the checks, not to
  "Your data"'s daily chart (it asks for `?flags=0`).
- **Don't add a page or step without a decision on it.** A screen that only confirms
  defaults should be an inline action instead. The index settings are "Adjust and
  recalculate" on Results, and the defaults are calculated while the user checks the
  quality (#178). The station is a workspace of three sections beside its inputs, with
  no steps (#179, #198). A first visit is one New station page (#201): the file, the
  station name, latitude and longitude, the base period, then "Check and calculate";
  thresholds and index settings start at their defaults and are changed later in Inputs.
  **Target (#233, #234, #242):** a first visit is the landing page, then Get started,
  then Add stations (one file or many, reviewed in one table). A one-station workspace
  opens straight to its station; the overview appears from two stations.
- **Don't throw work away when an input changes.** A new file, new station details, new
  thresholds or new settings keep the checks and results already made. They show as out
  of date (`stale_banner`, and the section's tab) until their replacement has finished,
  so the user can compare. Mark only what depends on the change: the base period changes
  Results and Files, not Quality.
- **Don't repeat a standing notice on every page** (retention, privacy). Show it once,
  where it matters, as a quiet line at the foot of the page: small muted text
  (`text-sm text-text-muted`) with a lock icon. The New station page says it once (#201).
- **Don't use colour alone.** Badges, flags and chart series carry a word or a shape too,
  and a theme's hue is always beside its name.
- **Don't take the decision out of view.** Quality is a worklist and a detail pane side
  by side under the verdict strip and its buttons (#202, #235): reviewing a finding changes
  the detail in place instead of opening rows down the page, and the pane stays in view as
  the list scrolls, so the page stays short.

## Responsive

**Desktop first** (#230): screens are designed at 1280–1600px, where the work is done.
Phones get the same content, stacked and usable, not a matched design; the accessibility
rules below still hold at every width.

Narrow screens get the same content in one column, in the same order. Below 600px the
header links and the theme toggle become a menu; on narrow screens the step indicator
shows only the current step's label, two-column field groups stack, and wide tables
scroll inside their focusable region rather than the page. Charts keep their table view.

On a phone (below 40rem, #203, proposal 7 of the mockups) a station's context bar is
the name (18px) and the ⋯ page menu on one line, the years under it (the base period
is in the Inputs bar, the file name in the File sheet), then the three tabs on one line
and the Inputs bar. Only the tabs and the bar stay in view as the page scrolls; the
scroll padding is their height, so focus never goes under them. Sheets fill the screen.
The Indices' rows are two lines each and their detail comes after the table, Quality's
detail comes after its list, an index page's statistics come under its chart, which
scrolls inside its region below 32rem,
and the download tables are short blocks. The accessibility tests run every page at
320px and fail on horizontal page scroll; the phone tests check the station pages at
320 and 375px for sticky elements covering each other, the Inputs bar's sheets and the
⋯ menu by keyboard.

## Agent prompt guide

- Work on a web ticket with the `build-to-design` skill: read the ticket's Design
  section, the rules here and the canvas boards it names before building, and compare the
  result with the boards, in light and dark, before the pull request.
- The canvas fixes a screen's layout, content and density; this file fixes rules and
  tokens. Don't copy the canvas's colour values or fonts, and don't pick a side silently
  when the two disagree: ask.
- Use tokens only: no hex values, no Tailwind default colours or sizes (they aren't
  loaded). New colours need light and dark values and pass the contrast test. Ink for
  actions, blue (`--color-link`) for links, `--color-brand` only for the
  logo, focus and selection, status
  colours only for the verdict and run state, `hue-*` for a theme's data.
- Build from `core/templates/components/` and add new parts to `/patterns/`. After
  changing classes, run `scripts/build-css.sh` and commit `css/climpact.css`.
- Format every number shown with `core/numbers.py` (minus, places, units, coordinates);
  never with `floatformat` or an f-string in a page.
- One primary action per view, a one-line answer before the data, severity in
  proportion. Check a new screen against the four user questions above.
- When a Target here is met, take its "Target" mark away in the same pull request, and
  describe the code as it now is.
- Every chart keeps its text summary, table view, CSV and keyboard controls; every page
  passes the axe tests in light and dark (`uv run pytest -m browser`; they are
  deselected by default and CI runs them).
- Logical CSS properties only; strings through `{% translate %}`; no inline scripts or
  styles (Content Security Policy).

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
  are the workspace's. Since #256 a workspace is `/w/<id>/` and its stations
  `/w/<id>/<station>/…`; the workspace's address opens a workspace of one station
  straight away, and one of several on its overview (#234, the Workspace and Calculate
  boards), which replaced the batch results page. Since #241 a station can be copied to
  another workspace or a new one ("Copy to workspace…" on its provenance line and in the
  Stations table, a page of its own); the copy is recalculated with that workspace's
  settings. Workspaces (#242) lists every workspace of the browser in place of Your
  calculations. Add stations (#233) is the one way in, for one station or many: Get
  started leads there, and so do the old New station and batch addresses, whose forms
  went with #271.
- **Coming back.** Workspaces belong to the browser (hosted, deleted after the retention
  period) or the computer (local: kept until deleted, and the retention notice says so).
  A saved workspace file rebuilds one anywhere since #240: Save file on each row of
  Workspaces downloads `climpact_workspace.zip` (the input files, metadata and settings,
  and `climpact_run.json`); "Open a workspace file" (Workspaces) and "Or open a saved
  workspace file" (Get started) lead to a page of its own that rebuilds it in this
  browser, its indices calculated again.
- **System fonts.** No web fonts (CSP, the bandwidth budget, offline use); tabular
  figures for numbers and `--font-mono` for codes, dates and numbers in tables.

Kept from phase 2: **primary buttons are ink** (near-black, near-white in the dark
theme), and **a station's title is the station name** the user gives, not the file name.
The Inputs panel is replaced by workspace settings and the station's provenance line
(Target: #231; Workspace settings are on the workspace's own pages since #234).

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
| `Quality.dc.html` | A station's Quality: the checks as a rail, the selected check's detail wide beside it (redrawn 17 Nov) | #235, #222, #264 |
| `Results.dc.html` | A station's Indices: filter rail, table, detail pane, across the whole window (redrawn 17 Nov) | #236, #218, #226, #263 |
| `Index.dc.html` | One index | #237 |
| `Files.dc.html` | Workspace Files and provenance | #239 |
| `GridFlow.dc.html` | Gridded: the flow from netCDF files to a map, and the name "Gridded" | #289 |
| `GridList.dc.html` | Gridded: your runs (replaces Recent runs on the start page) | #289 |
| `GridNew.dc.html` | Gridded: new run, choosing the files (local and hosted states) | #292, #291 |
| `GridSetup.dc.html` | Gridded: set-up, with its summary panel (ready, a problem, after the run) | #293 |
| `GridRun.dc.html` | A gridded run's stages while it calculates, and a failure (two states) | #294 |
| `GridMap.dc.html` | A gridded run's Map: index rail, map, cell pane; Year, Base mean, Anomaly, Trend | #295, #296, #290 |
| `GridFiles.dc.html` | A gridded run's Files and its record | #289 |

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
are for indices, the variable roles for the station's variables; trend, band, grid and axis; the gridded map's
**eight-bin scales** by the index's kind (#295: `--map-seq-temp-*`, values in °C, blue
through pale yellow to red; `--map-seq-warm-*`, `-cool-*`, `-wet-*` and `-dry-*` for
counts and amounts, moving away from the sunken surface in lightness, darker in light and
brighter in dark; each bin apart from the sunken surface, a cell with no value, and from
its neighbours under protanopia and deuteranopia, `test_map_scales_stand_apart`); a
seven-step diverging scale (anomalies; on the map, SPI and SPEI's standard classes,
reversed so dry is red, **Target:** `--map-div-*` with #296); the **trend scale** (#227: `--chart-decrease-2`,
`-decrease-1`, `-increase-1`, `-increase-2`, blue for a significant decrease and orange
for an increase, the strong step darker in light and brighter in dark; a cell's value is
written in it, in `--color-surface` on the strong steps and `--color-text` on the weak
ones: the trend grid's cells and the interval plot's dots since #238, at least 5.4:1 in
both themes); and the **coverage steps** (`--chart-coverage-1` to `-3`: complete, 1–3 days
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
| The gridded map's ramps (GridMap); its "sea" (no value); its coast | `--map-seq-<kind>-1` to `-8`; `surface-sunken`; `text` over a `surface` halo |
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
  around a value, which have one decimal (`numbers.fixed`, #235), and what the screen
  works out (a month's limit and usual range, over by, beyond by, TN − TX), one decimal,
  signed where the sign says something (`+328.6`, #264).
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
`--text-sm`, the workspace overview's Stations table (#234, sans headers too) and the
workspace Files' By station table (#239), and the Workspaces table and Get started's
"Or continue a workspace" (#242), and the gridded pages' tables (#289, #291, #293). The
jobs list keeps the plain table.

## Layout

- **Width:** content up to `--container-content` (72rem), reading text up to
  `--container-prose` (42rem); a data page (a station's sections: `data_page` in its
  context) has no max width and uses the whole window (#263; 92rem from #227 until then).
- **Spacing:** one step is 0.25rem (`--spacing`), a 4px grid. Common steps: 2 (0.5rem)
  inside controls, 4 to 5 (1–1.25rem) inside cards, 8 to 12 (2–3rem) between sections.
- **Breakpoints:** `sm` 40rem, `md` 52rem, `lg` 60rem, `xl` 64rem. Logical properties
  only, so right-to-left scripts work (checked by `test_static.py`).
- **Page frame:** header (#227: one row about 48px high across the window: the logo and
  "Climpact", which go to the landing page; Workspaces and Gridded; then Index reference,
  Help and the theme toggle at the end, and on the landing page Get started (from 40rem).
  Below 600px the destinations and Index reference are in the Menu, and so is the theme
  toggle, #203. Workspaces opens the Workspaces page, `/w/` (#242), and is current on
  workspace and station pages too; Gridded is current on every gridded page). The header
  stays in view at the top of every page as it scrolls (#284), with the context bar under
  it where there is one; not in a window under 30rem high, where nothing sticks → step
  indicator for the gridded flow (**Target:** none, #289) → title and one-line lead → content → footer. Stations come in
  on Add stations (#233, the AddStations board; starting a workspace, `/add/`, has Start's
  drop zone with the file format and the settings beside it, the content width): the h1
  (with the workspace in a breadcrumb when adding to one), then the drop zone, the review
  table and the line under it with Cancel and "Add N stations and check them", and beside
  them, from 90rem, the panel "Applies to every station" (below 90rem it is one line above
  the drop zone, so the table's eight columns fit at 1280px without scrolling sideways);
  up to 90rem wide. A station's own setup page (a new file that needs new details) keeps
  New station's narrow page (40rem, centred; #201): a lead, two numbered steps (Your
  file, Station details) divided by hairlines, then the one call to action. A station is a
  workspace instead: its context bar (#227: its name as the h1, the provenance line, the
  page's actions, then the section tabs, Quality, Indices and Files), then the Inputs
  panel and the section's content side by side (the Indices keep the Inputs bar at every
  width, #236). An index's page (#237) is a drill-down from the Indices instead: its
  context bar has the breadcrumb (station / Indices) with the previous and next index,
  the index as the h1 with its theme, its definition and the provenance line, and its
  files; no tabs and no Inputs panel, and it scrolls away with the page (`flow`), so
  the chart has the width (the site header stays). The h1 is the station name the user
  gives (the file name until there is one). The context bar stays in view under the site
  header as the page scrolls (not in a window under 30rem high), and so does what sticks
  under it, moved down by the header's height: the Indices' rail and pane, Quality's
  rail, the Inputs panel (#284). The page's scroll padding keeps a focused element or a
  `#fragment` out from under both (WCAG 2.4.11; `--site-header-height`, measured by
  `js/site-header.js`, plus `--context-bar-height`, measured by `js/context-bar.js`,
  make `--frame-height`). On phones the header stays, with only the tabs and the Inputs
  bar under it, and the name scrolls away (#203). The Inputs panel
  (16rem) sits at the inline start, in view under the context bar as the page scrolls, where
  the content has at least 52rem (a container query, so the help drawer counts);
  narrower, the Inputs bar under the tabs takes its place (#203), and without JavaScript
  the panel comes above the content. Quality (#235, #264) is the verdict strip, the
  coverage strip, then the checks as a rail (20rem: "Look wrong" and "Worth a look", each
  check with its variable, a by-month sparkline and its count) with the selected check's
  detail wide beside it: its kicker, title and sentence (what the check means and what
  to look at first), with "These values (CSV)" and "Show on the daily chart" by the
  title; two charts with axes, When (each value by date, the selected one ringed) and By
  calendar month (bars, with "Table" in place of the chart); then its values table (only
  that check's columns, 12 rows a page, largest first or by date) beside the selected
  value (a 7-day chart, PR bars with the limit dashed or TX and TN lines, and the 7-day
  table). Then the checks that found nothing in one line; the daily charts with the
  flags and the distributions as disclosures, and one line with the thresholds and the
  link to Files. Like the Indices, Quality has no Inputs panel beside it (#264): "Edit
  inputs" on the provenance line. Nothing in it scrolls sideways at 1280px or wider
  (checked with the 67 heavy rain days of `qc_stress_1961-2020.txt`). While the checks run, what is in the file ("Your data", #198) takes the
  worklist's place.
- **The landing page** (#242, the Landing board): bands across the window, each with
  its content up to 77.5rem: "Welcome back" for a returning visitor, the hero (the
  question, the lead, Get started and See an example, beside a preview of the Sydney
  sample's real output: TXx drawn as the detail pane draws a series and four rows of the
  Indices table), the facts (the parity suite's), How it works with three miniatures of
  the real screens, What you get on the surface, What you need, and a closing band on the
  selected tint. The bands are the exception to "one surface level": a page that
  introduces the app, not a data page.
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
  `stations.workspace.provenance`; the shown run's while its results are out of date,
  #223, its file's years too, #269), the page's actions at the end, then the tabs.
  Quality's line describes the data the checks read instead (#235, as its board draws
  it): the coordinates, the years, the days and variables in the file ("21,915 days ·
  PR TX TN") and the file's name; after a new file, those of the file the shown checks
  read until the new checks have finished (#269).
  An index's page (#237) uses the breadcrumb (station / Indices) and the previous and
  next index, named codes first. In a workspace of several stations every station page
  starts the breadcrumb with the workspace, which leads to its overview, then "Station 2
  of 6", with the previous and next station (each at its furthest section) at the
  row's end (#234, `workspace.station_nav`); a workspace of one station has "Add
  stations" at the end of the provenance line instead. **Target:** "Edit inputs" on the
  provenance line replaces the Inputs panel on Files too (#231; the Indices have it since
  #263, Quality since #264). The tabs are Quality, Indices (Results until #236) and
  Files; Quality's shows its verdict and count, "Usable · 21" (#222).
- **The workspace's own bar** (#234, the Workspace board; `stations/_space_bar.html`):
  "Workspace" in small muted text over its name (the h1 on the overview; a link on its
  other pages), the mono provenance line ("6 stations", the base period, "ET-SCI
  defaults" or how many settings are not the default, the climpact version, "kept until
  24 Nov 2026" where workspaces expire) with Workspace settings and Rename at its end,
  Add stations (small secondary) at the end of the title's row, then the tabs Overview,
  Compare an index (#238) and Files. Export ▾ (#239), primary at the end of the title's
  row on the overview, Compare an index and Files: Everything (zip), Trends and Indices
  of all stations (CSV), and All files. "Save file" is on Workspaces (#240). On Compare an
  index and Files the name is the h1 too. The overview is a data page (the whole
  window), as a station's.
- **Trends across stations** (#238, the Workspace board; `stations/_trends.html`) under
  the overview's Stations table, and alone on Compare an index (`/w/<id>/compare/`): the
  heading and one line ("Sen's slope per decade. Filled cells: the 95% interval excludes
  zero. …") with the legend at the row's end, then "Choose indices" (a disclosure: every
  index with a trend, by theme, codes first; remembered for the workspace in the session)
  and "Grid as CSV", then the trend grid beside the selected column's interval plot (the
  grid `flex: 999 1 40rem`, the plot 20–25rem, under the grid when there is no room).
  The trends wait, with a line saying so, while a station is calculated, and come in
  with the overview's last poll. A station whose recalculation then failed, or was not
  run or cancelled, keeps its earlier trends, tagged "· out of date" (#279), as its
  Indices, Files and its row of the Stations table say.
- **The gridded frame (the Grid boards; built by #289, #290, #291, #293 and #295, Target: #292, #294 and #296 for the rest).**
  A gridded run is a place of its own, like a workspace, not a flow of steps. **Naming:** the header says
  "Gridded" (the data's shape, the field's word: ET-SCI, Climpact for R's "gridded
  indices"); "netCDF" is said where files are chosen (the landing card "Gridded data
  (netCDF)", New gridded run, the upload) and never names the section, since stations may
  come as netCDF too.
  - **Gridded** (`/gridded/`, #289) lists the browser's runs (the computer's, locally) as
    a data table, most recently changed first: Run (a link; an ellipsis when long),
    Grid (rows × columns and the spacing), Period, Thresholds (the base period, ", file
    kept" when the run wrote a thresholds file; a scenario run names the run whose
    thresholds file it read, "From <run>"), Calculates ("55 indices", "Thresholds file
    only"), State ("Not started", or "Not started: precipitation units" in danger;
    "Calculating · 38%" with a small bar; "Finished 18 Nov, 21 min"; "Failed" in
    danger), Kept until ("–" while it calculates) where runs expire; a line under it on
    how long runs are kept. New gridded run (primary) at the title's end; with no runs,
    one line and the sample grid in the table's place; three boxes under it (stations or
    a grid, scenarios, the sample). Runs are not listed on Workspaces, whose note links
    here. Runs are kept as workspaces are (#301): hosted, `JOB_RETENTION_DAYS` after their
    last change ("Runs are kept in this browser for 7 days after their last change.
    Download what you want to keep."); locally, on the computer until forgotten, so Kept
    until is left out, as Workspaces' "Deleted on", and the line says "Runs stay on this
    computer until you forget them; files read in place are never touched."
  - **Before a run,** two pages with a breadcrumb ("Gridded / New run" and "Gridded /
    New run / set-up", #289), no stepper; the set-up page's h1 is the run's name, with
    Rename. New run (#292, `/gridded/new/`) is a narrow page (55rem, centred): the
    breadcrumb, the h1 and one lead, then locally "Files on this computer", the Folder
    listing (below) with "Paste paths or a pattern instead" one disclosure away (a path or
    a `*` and `?` pattern a line, up to 200 files since #291), and hosted "Upload netCDF
    files", the drop zone with the limit and how long files are kept stated in it before
    anything is uploaded, and one line on the ways round the limit. Under either, on a
    hairline, what is chosen in mono ("3 files chosen · tasmax, tasmin, pr · 561.0 MB", or
    "No files yet") and Read the files (primary, large) at the end; then "No files to
    hand? Try the sample grid" with its size. **Set-up**
    (#293, the GridSetup board; `gridded/setup.html`, `gridded/setup_page.py`): a context
    bar in the page's flow (the breadcrumb, the run's name as the h1 with Rename, "Climpact
    has read the headers of 3 files. Nothing has been calculated yet.", and "Choose other
    files" and "Forget this run" at its end), then one page of sections divided by
    hairlines, without cards or numbers: Files (the Gridded files table, below: a row for
    each variable's files, so a variable split by year is one row, "20 files, 1991–2010",
    that opens to its list; Header opens a file's `ncdump -h` in a dialog), Variables (a
    data table: Climpact needs, Variable in the files, Units in the file, Read as, Check;
    then one mono line, "Together: …"), What to calculate (three radio cards; Percentile
    thresholds under them), Base period (the years beside a timeline of the data's years,
    then the coverage line), Indices (four columns by the variable needed, codes first;
    the numbered indices' parameters in one row), Output files and Computing (closed, its
    values in its summary). Beside them the summary panel (Gridded summary panel, below;
    22.5rem, sticky; under the form below 64rem). Units are never converted silently: each
    variable shows its units and how they are read ("°C (K − 273.15)", "mm/day (× 86400)");
    a unit Climpact cannot read has a danger-tinted row and, under the table, what
    Climpact reads and how to convert it, with a CDO command and Copy for ERA5's
    precipitation in metres and hourly rates. Help is on request: a quiet link on What to
    calculate, the parameters, Output files and Computing.
  - **A run** (#289, `gridded/_run_bar.html` on `components/context_bar.html`) has its
    own bar, sticky as a station's: "Gridded / run", the run's name as the h1 (named
    from its files until renamed: "era5 SEA 0.25°, 1961–2020", the sample "Sample
    grid"), the mono provenance line (grid and cells with data, period and calendar,
    base period, indices and files or "calculating", version, kept until (where runs
    expire); then Rename
    and Forget this run, at every width), "Run again with other files" once no job runs
    and Download all (zip, size) once all have finished at the title's end; then the
    tabs **Map** (`/gridded/<run>/`), **Files** (`files/`) and **Set-up** (`setup/`).
    The old `results` address redirects to Map. While the run calculates or after it
    failed, Map holds the job cards with their progress.
    Set-up's summary panel describes the run ("This run": when, how long, what it wrote,
    and what has changed since), and "Start again with changes" keeps the results on Map
    and Files until the new ones are ready (#293). **Target:** while it calculates, or
    after it failed, the Map tab shows the run status line and the stages table (#294); a
    failure names the setting that fixes it, with a link.
  - **Map** (#295, the Gridded map pattern below) is a data page in the Indices' three
    columns: the index rail (14rem, by theme, codes first, the frequencies each index
    has), the map, the cell pane (`clamp(22rem, 28%, 32rem)`). Above the map: the code and
    name, the definition and file name; the view (Year; Base mean, Anomaly and Trend shown
    unavailable, **Target:** #296), Annual / Monthly, the year stepper (a month for a
    monthly file, the scale for SPI and SPEI); one line on what is shown; Download ▾ (Map
    as PNG, Map as CSV, the netCDF file). The map draws every cell (a PNG, one pixel per
    cell, scaled up without smoothing, the cells' aspect from the cosine of the mean
    latitude) under an SVG of the coastline and three to five places from a bundled
    Natural Earth outline: no map tiles, works offline. Eight fixed bins per index and
    view, the same for every year of the file: a sequential scale by the index's kind
    (temperature, warm counts, cold counts, wet, dry). **Target (#296):** a diverging
    scale centred on zero for anomalies and trends, reversed where an increase means
    cooler or drier, so warmer and wetter read the same on every map; on Trend a dot marks
    each cell whose 95% interval excludes zero. Hover reads a cell out; click, Enter,
    arrow keys and "Go to" select one. The cell pane reads like the Indices' detail pane
    (the series chart with base band, 11-year mean, Sen's slope and its interval, the year
    on the map marked; the statistics in the same order); when a station of one of the
    browser's workspaces is in the cell, it links to that station's index page.
    **Target (#296):** "Mean over the grid" (cos-latitude weighted).
  - **Files** (#289, `gridded/files.html`) uses the File group pattern, framed, by theme
    (Heat, Cold, Rain, Drought, Other; or by variable needed, or frequency, a GET form),
    the first open, each with "Download these (zip)" beside its summary: Code, Index,
    Freq., File, the netCDF variables in it, Size, the long ones ending in an ellipsis.
    Beside it (20rem, from 64rem): Everything (Download all; the links as a text file
    for `wget -i`, which work without the browser's session while the run is kept; the
    folder the files were copied to), the run's record (`run.json`: the settings,
    versions and the inputs' checksums; `climpact.log`; the thresholds file when the run
    kept one; `trends.nc`, each cell's trend and base-period mean, #290) and a note on
    reading the files.
- **Data pages use the width.** Desktop first: a station's pages fill the whole window
  (#263), with no max width; the 72rem content width stays for reading pages. Nothing on
  them scrolls sideways at 1280px or wider (Quality's since #264; on a phone a table's
  own frame may).
- **Panes:** a filter rail at the inline start (about 14rem), the table, and a detail pane
  at the inline end that stays in view as the list scrolls (`detail-pane`). Narrower,
  the rail goes above the table and the detail after the list, with "Back to the list".
  Quality (#264): the checks' rail (20rem, framed lists) and the check's detail (one
  framed object) side by side from a 60rem page, the rail sticky under the header and
  the context bar and scrolling inside itself when taller than the window; narrower, the
  rail above and
  the detail after it, its two tables one after the other. The Indices (#236, #263):
  the rail and the pane are full-height columns against the window's edges, not cards:
  the rail on the page's colour, the pane on the surface, each behind a hairline, their
  contents sticky under the header and the context bar. Side by side from a 76rem page:
  the rail 14rem (12.5rem below 86rem, so the table's names keep room at 1280px), the table, the pane
  `clamp(22rem, 28%, 32rem)`; from 48rem the rail beside the table and the pane under it;
  narrower, the rail above (its themes a wrapping row) and the detail after the table.
  No Inputs panel there, so the three have the width: "Edit inputs" on the provenance
  line opens the Inputs sheet, and the Inputs bar shows under 52rem, or wider only while
  an input has changed or a run is under way. The table opens sorted by the size of the
  trend with the first row's pane shown.
- **Data tables sit in one frame** (a `border` edge and `--radius-sm`), with hairline rows
  of 32px and a header row on the sunken tint: the exception to "a box marks only one
  object", because the table is one object (`components/table.html`, `table--data`).
  Quality's are (#235), and the Indices' (#236): at 1280 x 1180px (the board's size) 26
  of the Sydney sample's indices are in view, without sideways scroll. The Workspaces
  table is one since #242 (checked with seven workspaces: a 90-character name, one
  deleted in two days, one with a failed station, one with files not yet added; nothing
  scrolls sideways at 1280px or wider, and on a phone it scrolls in its frame). The Stations table is one
  since #234: nothing on the overview scrolls sideways at 1280px or wider (checked with
  7 stations, among them `qc_stress_1961-2020.txt`, a failed and a left-out station);
  the workspace Files' By station table since #239 (checked the same way with 8); the
  trend grid since #238 (eight stations, two without results, long names: 11 columns fit
  at 1280px with about 90px to spare, and with all 77 indices it scrolls inside its frame).

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
| Quality worklist | Pattern | Quality (#235, #264, the Quality board; `stations/_qc_review.html`): the verdict strip and the coverage strip, then the checks as a rail (`stations/_qc_rail_item.html`): "Look wrong" and "Worth a look", each a framed list with its heading, count and note inside the frame; each check a row ("Heavy rain days", "PR" in mono under it, twelve small bars by month with an empty month a thin mark, its count), the selected one on the selected tint with an ink edge (`is-selected`, `aria-current`); "How the checks work" as a quiet link under them. Each check links to `?show=<id>`, so it works without JS and can be linked; with JS the detail changes in place and is announced. The detail (`stations/_qc_detail.html`), one framed object: the kicker ("Worth a look · PR · 67 values"), the title, one sentence (what the check means, then what to look at first), "These values (CSV)" and "Show on the daily chart"; the When and By calendar month charts; then the values table and the selected value (`stations/_qc_values.html`, also the htmx fragment of `stations:qc_table`). The table has only the check's columns (`qc_review.value_columns`: heavy rain "PR mm, Month's limit mm, Over by mm"; TN ≥ TX "TN °C, TX °C, TN − TX °C"; temperature outliers "TX °C, Usual range °C, Beyond by °C"; jumps without the next day's date; flat runs with their first day; repeated dates with their lines in the file), 30px rows, 12 a page, "Sort: Largest first · Date", "Page 1 of 6 ← Previous Next →". A row's date selects its value (an address without JS, the fragment with it; the whole row can be clicked). The selected value: its date and check in mono, the sentence ("PR 350.5 mm, 328.6 mm over the limit for December", codes first), the 7-day chart, the 7-day table (one decimal; the day in bold on the warning tint, the check's other values on a lighter one), a repeated date's rows, its line in the file. The largest value is selected by default | check, value, by date, table view |
| Verdict strip | Component | A judgement in one line (`components/verdict_strip.html`, #235): on the status's soft tint with a hairline in its hue, the level in bold and one sentence as the heading ("**Usable.** 21 values look wrong; the indices can run with them as they are."), the counts on one mono line under it, the decision's small buttons at the end. On Quality: "Flagged values (CSV)", "Replace file", "Go to indices" (primary); on red "Go to indices anyway" and "Replace file" (primary); no buttons while the checks are out of date | ready, usable, fix |
| Coverage strip | Component | Missing days per year for each variable (`components/coverage_strip.html`, #235): in a frame, "Coverage" with a muted note (what the annual completeness rule makes of the years) and the key; a row per variable, its code, a cell a year in the three coverage steps (an SVG, `aria-hidden`) and its total; the years under them, evenly spaced. The table view follows as a disclosure. Narrower than 36rem the rows scroll | — |
| Detail pane | Component | The selected row's detail beside its table (`detail-pane`, #235, and the Indices', #236): a frame on the surface, in view under the context bar as the list scrolls and scrolling inside itself; after the list on narrow screens, with "Back to the list", which returns focus to the row | — |
| `field`, `field_errors` | Component | Label, short hint, input, unit, inline error; no help link of its own | narrow, with unit |
| `dropzone` | Component | File input with drag and drop; works without JS | — |
| Review table | Pattern | Add stations' files (#233, the AddStations board; `stations/_add_table.html`, `stations/add_stations.review`): a framed data table with its heading inside the frame ("7 files read · metadata from stations_nsw.txt · paste latitude and longitude columns from a spreadsheet" and "Metadata file format"); a row a station file, 34px: File (mono, an ellipsis when long, whole in its title), Station name, Latitude and Longitude (inputs as small as the row, mono for the coordinates), Period, Days, Index settings ("Defaults" or "Custom (wsdin 4)") and Read ("Read · 6.9% missing" in success, a warning such as "Read · 2 repeated dates; checks will list them" in amber, a problem such as "Latitude needed" or "Not read: line 1 has 4 values, expected 6 (year month day PR TX TN)" in red, the only column that wraps). A row with a problem has a faint danger tint and its invalid cells the danger edge; it stays out. Under the table, a disclosure with every problem and warning and its line, and one sentence naming what is left to fix ("2 problems to fix before these stations can be added: a missing latitude and an unreadable file."). Checked as it is typed, a pasted column fills down (`js/add-stations.js`); a plain form without JavaScript. On a phone the table scrolls in its frame | problems, warnings, metadata |
| New station steps | Pattern | The steps of a station's setup page (New station until Add stations, #233; `setup__step`, #201): a number in an ink circle (a CSS counter, so no text to translate; a success tick once done), the step's section header and its fields, each step under a hairline; then `setup__cta`, the one primary button and a muted note beside it on what it does and what keeps its default. No boxes: the file card is the only one | step done |
| File card | Component | The file read (`stations/_file_card.html`): its name, "✓ Read: first–last year, days" in success, and Replace (a file button inside the page's form) at the end; under it the days with data in each year, an SVG bar a year in success, amber (`--color-warning`) when the year misses more than 15 days (too many for annual index values), with a text alternative naming those years | gaps, no gaps |
| `file_button` | Component | A button that opens the file picker and sends the chosen file at once, for a second upload where a drop zone takes too much room; a file input and a submit button without JS. Unused since Quality's corrected file became the File sheet (#199) | primary, secondary; lg, sm |
| `form_errors` | Component | Error summary that links to each field, focused on load | — |
| `card` | Component | Grouped content; whole-card link | link, muted, with badge |
| `alert`, `messages`, `toasts` | Component | Page and transient feedback | info, success, warning, error; dismissible; live |
| `disclosure` | Component | Content that opens in place (`<details>`): a row between hairlines, not a box | — |
| `dialog` | Component | Native modal with focus kept inside | confirm, danger |
| Inputs panel | Component | Everything the user gave, beside a station's sections (`stations/_inputs.html`): a group label, then each input as a row of its name (muted), its value (semibold) and one link at the end, Edit or Replace, on a sunken tint without a border. The thresholds and index settings read "Defaults" or how many were changed ("2 changed"). An input changed since the checks or results shown has the warning tint and says "changed" after its name; the run of the new inputs shows its progress in a box beneath the list, polled until it finishes. While that run is a change to the workspace's settings (#254), a small secondary "Undo the change" under it, a plain form (`stations/_undo_form.html`). Sticky under the context bar when beside the content | changed; with a run; with undo |
| Inputs bar | Component | The Inputs panel in one line, under the workspace tabs where the content has less than 52rem (`stations/_inputs_bar.html`, the mockups' `.inputsbar`; #203): "Inputs:" then the base period and "defaults" or how many settings are not the default, then each input changed since what is shown (warning colour, and the bar takes the warning tint) and each run under way, and a small secondary Edit at the end, after a small secondary "Undo" while a change to the workspace's settings can be undone (#254). Edit opens the Inputs sheet: the panel's list in a side sheet, which on a phone fills the screen; each input's Edit there opens its own sheet over it, and Escape steps back to the list, then the bar. Only with JavaScript; without it the panel shows above the content. On a phone it reaches the screen's edges, under a hairline | changed; with a run; with undo |
| Popover | Component | A disclosure whose panel floats under its button at the inline end (`pop`, `pop__details`, `pop__panel` in `disclosure.css`, #239; the index page's citation since #237): a native `<details>`, so it works without JavaScript. Export ▾ (`pop__panel--menu`, the menu's links one a line; `js/context-bar.js` closes it on Escape and on a click elsewhere), "Citation" and Files' "Methods text" (`pop__panel--text`: the text, which a copy button replaces with JavaScript, `js/copy.js` and `js/index-page.js`). In the ⋯ menu on phones it opens in place. The context bar's surface reaches the window's edges from a layer behind it (`::before`), so nothing that opens below the bar is cut off | menu, text |
| Page menu (⋯) | Component | On a phone the page's actions (Results: the sector comparison, Download all) move from the context bar into a ⋯ button at the end of the name's line (`page-menu` in `components/context_bar.html`; #203). A disclosure, not an ARIA menu: a native `<details>` whose summary is the button ("Page actions" for screen readers), so it works without JavaScript; Enter or Space opens it, Tab goes through the actions (full-width buttons, one a line, in a raised panel), Escape closes it and returns focus to the button, and a click or focus elsewhere closes it (`js/context-bar.js`) | — |
| Side sheet | Component | One input's form at the inline end, the screen's full height (`stations/_input_sheets.html`, `js/sheet.js`): a title and close button, the form's fields, what applying will update in a warning tint (`impact`), then one primary button, Apply, and Cancel at its foot. **Modal**, unlike the drawer: the form is being edited and applying starts a run, so it is a native `<dialog>` opened with `showModal()`: a backdrop, the page behind inert, focus on the first field and kept inside, Escape, Cancel, close or a click on the backdrop closes it and discards what was typed, and focus returns to the Edit link. Without JS, Edit links to the same form on its own page; a form with errors returns there. A long form (the index settings) scrolls inside the sheet with Apply kept in view at the foot, rather than widening the sheet; its groups are divided by rules, and their help opens in place, since the drawer would be behind the modal | base period, index settings |
| `drawer` | Component | A section's help in a side panel, opened by the Help pill of the section's header (`{% section_help %}`). Not modal: no backdrop, no focus trap. Beside the content from 64rem, below it on narrower screens. Escape or close returns focus to the pill. Without JS the pill links to the same help on its own page. Help at the end of the app bar (a quiet link since #227) opens the page's guide | — |
| `table` (data table) | Component | The framed dense table (#227, `table-wrap--data`, `table--data`): one frame, hairline rows 32px high and one line each, a sticky header on the sunken tint, `num` and `code` cells in mono with tabular figures, the selected row (`aria-current`) in the selected tint with an ink edge, in a keyboard-scrollable region. The plain `.table` (hairline rows, no frame) stays for tables inside a card, a disclosure or a chart until each page moves (Layout) | empty state, selected row |
| Context bar | Component | Under the header on a station's pages (`components/context_bar.html`, #227): a breadcrumb with the previous and next item (when given; an index named codes first, #237), the title, a lead line (`lead_template`), the mono provenance line, the page's actions, the tabs and the Inputs bar under them; across the window and sticky under the site header (`js/context-bar.js` keeps the scroll padding to its height, #284). `title_template` draws a title of its own (an index's name and theme pill); `flow` keeps it in the page's flow, for a page without tabs (an index's); `static` shows it in place on `/patterns/` | breadcrumb, sub-page title (a line, not the h1), own title, flow |
| `index_name` | Primitive | An index named codes first (#218): the code in mono, without the code background, then the short name, "TXx Hottest day". In a page title the name is a step lighter. The catalogue puts them in two columns, Code then Index | title |
| `summary_list` | Component | Key–value pairs | — |
| `tabs` | Component | ARIA tablist; all panels show without JS | — |
| `workspace_tabs` | Component | A station's sections as tabs under its name, in the sticky context bar (`stations/_workspace.html`). Each is a page of its own, so they are links in a named `nav` with `aria-current="page"`, not a tablist; Tab moves between them. Each has a status: an icon of its own shape and a word (done `check-circle`, needs attention `warning`, out of date `clock`, running `refresh`, not started `circle`, not available yet `lock`; Indices' "No indices" `warning`, in the warning colour, when the run made no index table, #298). The word shows for the states that need the user and is read by screen readers for all. Quality's tab reads like its verdict (#222): "Checking…" (`refresh`) while the checks run, then the verdict strip's level and an icon, Ready `check-circle`, Usable `warning` or Fix first `error`, as a small pill in the status colour on its soft tint, with the count of values that look wrong after a middle dot ("Usable · 21", read as "Usable, 21 values look wrong"); a failed check stays "Needs attention". On a phone (under 40rem) the verdict is its icon on the tint, so the three tabs stay on one line at 320px; the word and count are still read. A section not available yet is not a link. Looks like `tabs` | — |
| `progress`, `stages`, `skeleton` | Component | Running jobs and loading content. The label is the stage in words, then the percentage ("Calculating the indices", 7%): `jobs/stages.py` maps each stage to its words and never shows its ids (module, index or file, #226) | determinate, indeterminate |
| `chart_frame` | Pattern | Chart with title, text summary, legend, zoom, PNG/SVG, table view, CSV (Quality's daily charts; the index page draws its own frame since #237, and the gridded cell pane its own since #295 and shares its controls, `chart_toolbar` and `chart_readout`, since #283) | — |
| `readout` | Component | The read-out under a chart drawn on the server (#283, `js/chart-readout.js`): the line that writes the values under the pointer or the keyboard's cursor ("1996 · TXx 41.2 °C"), how the keyboard works (named by the chart's `data-readout-keys`) and the status line that announces each keyboard move. The chart's `data-readout` holds where each value is; "open" or "select" says what Enter does | open (a value opens the index page at it), select (a value selects its row), none |
| Segmented control | Primitive | One choice of two to four side by side (`segmented`, #237): links in one strip of `border-strong` edges, the current one ink (`aria-current`), so each works without JavaScript. A choice not offered is a span with `aria-disabled` in muted text, struck through when the item has no such thing (`segmented__item--off`, a frequency without a file, #295). The index page's Values / Anomaly and Annual / Monthly; the gridded map's view, frequency and scale | not offered, off |
| Index page | Pattern | One index (#237, the Index board; `stations/result.html`, `stations/index_page.py`): the context bar (breadcrumb station / Indices with the previous and next index; the index as the h1 with its theme pill; its definition, unit and R's name, with "About this index" as a quiet help link; the provenance line; CSV, "PNG (R style)" and "Copy citation", a disclosure without JavaScript); then the chart in a frame beside the Trend statistics (Sen's slope, 95% interval, Significant, Years used, Base-period mean, Record; why any year was left out; the method); then the values as a framed data table, scrolling inside its frame (Year, the value with its unit, Anomaly, Rank, the date of the maximum or minimum where the core gives it, Note: Record or why the value was left out), most recent first. The chart is drawn on the server: the base period as a band, round values and years on the axes, the y axis titled with the code and units, Sen's slope's 95% interval as a shaded bow tie through the slope's middle, the values (bars for SPI and SPEI) with gaps, the 11-year running mean, Sen's slope dashed, each value left out an open point at the base-period mean; the segmented controls switch Values / Anomaly in place (`js/index-page.js`) and Annual / Monthly by link. Below 32rem the server's chart scrolls inside its region. With JavaScript (#283) `charts.js` draws the same marks from the page's data (`index_page.payload`, `#index-chart-data`) in the server chart's place, which stays for print: the read-out under it by pointer or keyboard (the year, or month, with the date of the extreme; the value with its unit; its anomaly; the running mean; or why the value was left out), the controls above it (zoom in and out, earlier and later, Show all, PNG and SVG of the view; "PNG (R style)" stays R's file), and Values / Anomaly switching it in place; it fits the width at every size. `?at=1944` (a year picked on the Indices) marks that year, reads it out and selects its row | annual, monthly, anomaly, bars (SPI), day of the year (TX95t: no rank or record), daily (EHF, ECF: the ten highest days) |
| Filter rail | Component | The Indices' filters at the inline start (`filter-rail` in `stations/_indices.html`, #236): "Find", a search that matches the code, the short name and R's names; "Theme", a list of plain rows (All and each theme with its dot and a mono count; the current one on the `selected` tint with an ink edge, as a selected table row, #263); "Significant only"; one muted line defining significant ("the 95% interval of Sen's slope excludes zero"); the help as a quiet link; at its foot, under a hairline, the settings line. A GET form without JavaScript, filtering as you type with it (`js/results.js`). Above the table on narrow pages, the themes in a wrapping row | — |
| Indices table | Component | Every index in one data table (`stations/_indices.html`, #200, #236): Code (the theme's dot and the code, a link to `?show=`), Index (the short name; an ellipsis when long, whole in its `title`), Slope per decade with its unit beside it in muted text ("+5.15 days", "+1.31 pp" for a percentage), 95% interval, Significant ("yes" with the dot, a dash read "no"), the series as a sparkline headed by its years (144px where the page is 86rem wide, 96px narrower) (#263). A line that answers above it and the live line ("Showing 80 of 80 indices. Sorted by the size of the trend, largest first."). It opens sorted by the size of the trend, the slope per decade without its sign, largest first (#263). Code, Index, Slope and Significant sort it: links without JavaScript, buttons with it, `aria-sort` on the sorted column. Every row is in the page, the filtered ones hidden. On a phone each row is two lines, its cells wrapping rather than overlapping: a third line at 320px when a long slope, interval and "yes" don't fit (#286) | filtered, sorted, selected row, no match |
| Index detail | Component | The selected index in the detail pane (`stations/_index_detail.html`, #236): code and theme in mono, the short name as a heading, the definition; the series drawn on the server with axes (three values, three years), the base period as a band and Sen's slope dashed (`index_detail.chart`), its caption and text alternative; then two columns of statistics: Slope, 95% interval, "Mean, 1936–2015", Significant in words ("Yes: the interval excludes zero" or "No"), Years used and Method ("Sen's slope (zyp)") (#263), one a line in a narrow pane; then "Open full page", CSV, PNG and "Monthly values". The chart reads out each value by pointer or keyboard (`readout`, #283; its values fetched from the series' chart data when it is first used), and a click or Enter on a year opens the index page at it (`?at=`) | with a trend, without, daily |
| `download_link` | Primitive | One file to download: a small secondary button with its format and size, the file named for screen readers | — |
| `spark` | Primitive | Decorative sparkline beside a trend given in words | line, bars |
| Run status line | Pattern | One line above a workspace's Stations table (#234, the Calculate board; `stations/_overview.html`, `stations.overview.status_line`), never a panel: on the surface with a 3px edge at the inline start. Neutral (ink edge) with a small bar while stations calculate: "**Calculating indices: 3 of 5 stations done.** About 25 s left. Finished stations open now." and Cancel (the batch) or "Undo the change" (a change to the workspace's settings, #254), plain forms. Quiet (success edge) when they have finished: "**5 stations calculated in 41 s.**", the stations not run and why (the files are in Export ▾ and on Files since #239). A station whose run made no index table finished but is not counted as calculated (#298): "**1 of 2 stations calculated in 16 s.** Empty Hill has no indices: every value is missing.", still quiet. Red (danger edge) only when one failed: "**4 of 5 stations calculated in 38 s. Port Macquarie failed:** its error", with Workspace settings. Its first sentence is announced (`data-announce`, at once when it has finished). It sums up every station's state, so a recalculation shows in it as a batch does | running, done, failed, with undo |
| Stations table | Pattern | A workspace's stations (#234, `stations/_overview.html`, `stations.overview.rows`), a data table in the order they were added: Station (a link to its furthest section, an ellipsis when long), "Lat, lon", Period, Missing (all values, mono), Quality (the Quality tab's verdict pill with its count, "Usable · 5", or "Checking…", or "–" without checks), Indices (Done, or "Out of date" when its replacement was cancelled and the results shown are from before a change (#279); "No indices" when the run made no index table (every index skipped, as for a file whose values are all missing; #298), muted as "Not run" is, with "Replace the file" (the File sheet) and "–" under Significant; "Calculating · 40%" with a small bar; Waiting; "Not run" with its fix, "Fix the file" or "Fix quality first"; "Failed: " and the error, an ellipsis when long, with "Change base period" when that is why; the row on a faint danger tint) and Significant ("22 of 80", the indices with a significant trend of those calculated), then "Copy…" (Copy to workspace…, #241) at the row's end, its column header for screen readers only. Polled with the run status line while a station is checked or calculated (`stations:workspace_progress`); the note above it says rows update as each station finishes. A station added to a workspace of several is calculated at once, as a batch's are (#277: no "Go to indices" first), so its row, its Indices tab, Files and the trend grid agree | calculating, finished, failed, not run |
| Workspaces table | Pattern | Every workspace of the browser (#242, the WorkspaceList board; `stations/_workspaces_table.html`, `stations.workspace_list`), a data table, most recently changed first: Name (a link, with a muted hint of its stations under it: one station's years, several stations' first two names "and 4 more"; each line ends in an ellipsis; rows 44px for the two lines), Stations, Status (one station's Quality pill with its count; several stations' counts by verdict, "2 ready", "2 usable", "1 fix first", "1 checking" on the sunken tint, and "1 failed" on the danger tint), Base period, Updated, "Deleted on" where workspaces expire ("20 Nov · in 2 days" in warning colour under three days away) and Delete (a quiet link to a confirmation page). Get started's "Or continue a workspace" is the same table cut to Name, Stations, Updated and Deleted on, three rows | expiring soon, failed, files waiting |
| `stale_banner` | Pattern | Results kept on the page after an input changed: what changed, in words, and what happens next. An info alert with the new run's progress while it is on the way; a warning alert with one action ("Recalculate", or a link to fix the input) otherwise. The results below sit in a `stale-content` block: a dashed warning edge and greyed sparklines, the text at full contrast. Meanwhile the header describes the results shown and "Download all (out of date)" is secondary (#223) | updating, out of date |
| Workspace files | Pattern | The workspace's Files (#239, the Files board; `stations/workspace_files.html`, `stations/workspace_files.py`): three framed boxes in a row, one a file (its name, its format and size in mono, what is in it, Download: "Download (out of date)" while a station's results are), "What is in the zip"; By station, a data table of each station's R files (Folder (zip), Report (PDF), All plots (PDF), Trends, Thresholds, Missing values, Quality flags: a size, "8 files", or why it is missing); then the provenance file (`climpact_run.json`, scrolling in its frame) with "Copy methods text", beside "Keeping the files": when they are deleted, then "Keep 7 more days" (#274: a POST form's button styled as a link, only where workspaces expire; it counts the workspace as changed now) and "Delete workspace now" in danger colour (the Workspaces list's confirmation page, whose Cancel comes back to Files). The files wait, with a line saying so, while a station is being calculated | ready, calculating, no results |
| Trend grid | Pattern | Stations by indices (#238, `stations/_trends.html`, `stations/trend_grid.py`): a data table in its own frame, scrolling sideways inside it when the user chooses many indices, the station's name sticky at the inline start (an ellipsis from 11rem; "(no results)" after it). By default TXx, TNn, TN90p, TX10p, SU, TR, WSDI, PRCPTOT, Rx1day, R95p and CDD; chosen ones follow the defaults' order. Each header is the code (a link that selects the column, `?index=`; `js/trends.js` shows its plot in place), the short name in its `title` and for screen readers, the slope's units under it (`pp` for a percentage). Each cell is Sen's slope per decade, always written (`numbers.slope`), a link to the station's index page, its interval and significance in words for screen readers: filled on the trend scale when the 95% interval excludes zero (the strong step from half the column's largest significant slope, the weak one below), a dashed `border-strong` edge when it does not, "–" for too few values, hatched for a station without results. A station whose results are out of date (its recalculation failed, was not run or was cancelled; #279) keeps its trends, tagged "· out of date" after its name (muted, as the Calculate board tags rows "· failed"; the dot hidden from screen readers, "These trends are from before the last change." in its `title`), its name cell edged as `stale-content` is (a dashed warning edge at the inline start), each cell's words ending ", out of date"; in the interval plot its name is tagged the same. A station whose run made no index table (every index skipped, as for a file whose values are all missing; the Stations table's "No indices", #298) is hatched as a station without results and tagged "· no indices" after its name, as the Calculate board tags a hatched row (muted, the dot hidden from screen readers; #315), each cell's words "<code>: no indices", and the interval plot lists it under "Not shown" ("Empty Hill: no indices"). The selected column's header is on the selected tint with an ink edge under it. "Grid as CSV" is the workspace's Trends file's rows for the grid's indices, whose `out_of_date` column says the same; a station with no indices has no rows there, as a station without results has none | selected column, not significant, too few values, no results, no indices, out of date, many columns |
| Interval plot | Pattern | The selected column beside the grid (#238): the code and "units per decade" in mono over the short name; a row a station, its name (a link to its index page) with its slope and interval, then a 360 x 16 line: the zero line, the interval as a thick muted line, the slope as a dot (the strong step of its direction when significant, `border-strong` when not); one axis under them, symmetric about zero, its ends round (`index_page.nice_ticks`). Stations left out say why under it ("Not shown: … no results"), then the key line and "CSV, all stations". Every column's plot is in the page, the others hidden. Its table view is the grid's column, its text summary the count of significant trends | significant, not significant, left out |
| `empty_state` | Pattern | Nothing to show yet, with the next action. The Indices of a run that wrote no index table (every index skipped, #268): "No index to show" above the list of what could not be calculated, with "Replace the file" (the File sheet), in place of the rail, table and pane; its Indices tab, its Stations-table row and the run status line say "No indices" (#298) | — |
| File group | Pattern | A long list of files behind a closed native `<details>` (`disclosure download-group`): the summary gives the group's name, the count and the total size, and opens to a table with a `download_link` per file; on phones each row becomes a short block. Each index section and the quality checks on Files; markup in `stations/downloads.html`. A gridded run's Files (#289) frames each group (`gridded-group`), its hue dot before the name, the first open, and puts "Download these (zip)" beside the summary rather than in it (a link in a summary is a control in a control) | open, closed |
| Gridded files table | Pattern | The set-up page's Files (#291, the GridSetup board's Files table; `gridded/_files_table.html`, `inspection.group_files`): a framed data table, a row for the files holding the same variables, joined along time. File: the name over its folder (locally) in mono, or for a variable split across files "20 files, 1991–2010" as a native `<details>` listing each file and its dates, over the folder (or the first and last names when hosted); Daily variables, Grid, Dates (`first → last`), Calendar in mono; Size; then Header (#293), a link to the row's first file's header as `ncdump -h` prints it, which `js/gridded.js` opens in a wide dialog (its own page without JavaScript). Long names end in an ellipsis, whole in their `title`. A file that cannot be used has its own row, the reason in danger | one file, split files, list open, a file that cannot be used |
| Folder listing | Pattern | New gridded run's chooser (#292, the GridNew board; `gridded/_listing.html`, `gridded.listing`): one frame holding a path bar (the folders above as links in mono, separated by ›, the current one in medium weight; a 30px folder field in mono at the end) and a data table of the folder: a checkbox, Name, Daily variables, Dates (years), Size. Subfolders first, as links ("raw/"); a ticked file's row in the `selected` tint (no ink edge: several can be ticked); a file that cannot be chosen greyed, its checkbox off, the reason in the variables column ("– (no time axis)", "– (thresholds file)"). The links are the form's buttons, so it works without JavaScript and keeps what is ticked across folders; htmx swaps only the listing | a ticked file, a file that cannot be chosen, an empty folder, a folder that is not there |
| Gridded summary panel | Pattern | The set-up's check (#293, the GridSetup board; `gridded/_summary.html`, `setup_page.panel_for`): a framed panel at the inline end, sticky, its title ("Ready to start"; "Before you start" with "1 problem to fix before starting:" and each problem linked to its field, in danger; "This run" after a run; "Calculating" or "Calculating again" while jobs run), then a list, each line a mark (✓ success, ✗ danger, i ink, ~ and · muted, drawn by CSS and named for screen readers) and a bold title before its sentence: Grid, Period, Variables, Base period, Writes, Disk, Cell-first copy, Time; after a run Calculated, Wrote, Settings and "Nothing changed yet." or "Changed: Base period."; then the one primary button, full width ("Start the calculation", "Start again with changes") and a muted line. Estimates say "about". htmx swaps it (and, out of band, the parts of the form that follow it) as the form changes; without JavaScript the posted form draws it | ready, a problem, after a run, changed, calculating again, a new start that failed |
| Gridded runs table | Pattern | Gridded's runs (#289, the GridList board; `gridded/_runs_table.html`, `gridded.runs.entries`): a data table, most recently changed first, as the gridded frame describes it; State in danger for a run that failed or cannot start, with a small bar (`meter`) while it calculates | not started, a problem, calculating, finished, failed |
| Gridded map | Pattern | A gridded run's Map (#295, the GridMap board; `gridded/_map.html`, `gridded/_cell_pane.html`, `gridded/map_page.py`, `js/gridded-map.js`): the index rail (Find, then the run's indices by theme with the theme's dot and name, each row the code in mono, the short name with an ellipsis and its frequencies, 30px; the selected one on the selected tint with an ink edge; a GET form without JavaScript, filtering as you type with it); the toolbar (the code and name as the h2, the definition and file; segmented controls for the view, the frequency and SPI's scale, a choice not offered `aria-disabled`; the stepper; Download ▾); the map (a PNG of every cell in an SVG with the coastline over a surface halo, places with a halo, axes in degrees and the selected cell outlined in ink over a surface halo; one focusable group with a read-out line, a tooltip and a polite live region; a latitude and longitude form without JavaScript); the legend (the bins with their breaks, the range of the cells with a value, No value); the cell pane (the cell in mono, Go to, the series chart, the statistics, the values by year, the CSV, the station in the cell). Links and forms swap the map in place and keep the address | year, month, scale, no value, a station in the cell |

Patterns built in a page's own templates, not yet in `/patterns/` (the Quality page,
`stations/templates/stations/_qc_*.html`, and the Indices):

| Pattern | Purpose | Built from |
| --- | --- | --- |
| Index chart | The index page's chart (#237), drawn on the server (`index_page.chart`, `stations/_index_chart.html`) in an 860 x 340 box, both views (values and anomalies) in the page: the chart without JavaScript and in print. With it, `charts.js` draws the same marks interactively in its place (#283, `stations/_index_chart_tools.html`). Its text alternative gives the values and the trend; the table under it is its table view and the CSV is in the context bar. | `chart_frame`'s toolbar and read-out, `charts.js` |
| Finding chart | The 7 days around a check's selected value on Quality (#235, #264), drawn on the server (`qc_review._chart`, `_bar_chart`): for rain a bar a day (the day in `--chart-prcp`, the others muted) with the limit it is checked against dashed; otherwise a line per variable in its role colour, gaps where values are missing, the value ringed in `--chart-flag` as on the full charts; the day as a band in the selected tint, three value ticks and three date ticks. Its text alternative names the variables, the dates and the limit; the 7-day table under it is its table view, and "Show on the daily chart" leads to the full chart and its CSV. Each day's PR, TX and TN is read out by pointer or keyboard (`readout`, #283). | `chart_frame` for the full chart, `readout` |
| Check charts | A check's two charts on Quality (#264), drawn on the server: When (`qc_review.when_chart`: each value against its date across the record as a muted dot, the selected one ringed in `--chart-flag`, three value ticks from zero for amounts, up to seven years) and By calendar month (`months_chart`: twelve muted bars, three count ticks, the months under them). Text alternatives give the check, the years and the counts by month; When's table view is the values table, By calendar month's a table that "Table" (`aria-pressed`) shows in the chart's place, under the chart without JS. Both read out their values by pointer or keyboard (`readout`, #283): When each value's date and value (the nearest dot), a click or Enter selecting it in the values table, on its page; By calendar month each month's count. | `chart_frame` for the full chart, `readout` |
| Settings line and panel | The settings in one muted line (at the foot of the Indices' filter rail since #236): the defaults, or what was changed, and a link that opens them in place. The form is one closed `disclosure` near the foot of the page, its groups divided by rules, not cards; one button at the end. `stations/_settings_form.html` | `disclosure`, `field`, `button` |
| Recalculation | A run that replaces results already shown, of the same inputs: its progress in a card with an ink edge above the results, which stay until it finishes. A failure says so in the same card, with "Try again". When the inputs changed (#179) the `stale_banner` takes its place, with the same progress inside. | `card`, `progress`, `stages` |

**Target: replaced by #230.** These stay until the ticket named lands, then go (the
theme tiles, `answer-band` and the Catalogue went with the Indices table, #236): the
Inputs panel and Inputs bar (by "Edit inputs" on the
context bar and workspace settings, #231); `file_button` (unused); the
Settings line and panel (by workspace settings, #231). The batch results page and the
batch's `steps` went with #234 (the overview's run status line and Stations table), and
`steps` itself with #289 (a gridded run has a breadcrumb before it starts and its tabs
after). The Side sheet stays, for workspace settings.

The new patterns of #230 have all landed and are on `/patterns/`; the Workspaces table
was the last (#242).

Every chart has a text summary, a table view and a CSV download, and can be used by
keyboard. This is not optional. **Every chart that is read has axes** with units and
years; sparklines are only for scanning, beside a number given in text.

**Every chart that is read is interactive** (#283): its values are read out under it by
pointer and by keyboard, the crosshair in `--chart-axis`, the value ringed in the text
colour and the focus ring in `--color-focus`, in both themes. Which charts hydrate:

- **Drawn by `charts.js` (uPlot)**: Quality's daily charts, since #283 the index page's
  chart, and since #295 the gridded cell pane's series (each from the page's own data,
  the index page's payload, the server's chart its fallback; the pane's without the
  zoom toolbar, as the GridMap board draws it). The read-out, zoom and move, Show all, and PNG and SVG of the view. The
  keyboard: the left and right arrow keys read out each value (announced), Home and End
  the first and last in view, Shift with an arrow key moves the view, + and − zoom, 0
  shows the whole series.
- **Drawn on the server, with a read-out** (`readout`, `js/chart-readout.js`): the
  Indices' detail chart, Quality's When, By calendar month and 7-day charts. The arrow
  keys, Home and End read out each value; Enter acts where the chart has an action (open
  the index page at a year; select a When value's row). Without JavaScript they are the
  server's images, unchanged.
- **Not interactive**: sparklines, the rail's month bars, the coverage strip (its table
  view is one click away) and the trend grid's interval plot (its values are the grid's
  cells).

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
  context bar (#227), and the workspace's pages theirs (#234). Every zip the app offers
  holds `climpact_run.json` (#239): the software, when, the base period, the settings,
  the trend method and each station's file, SHA-256 and coordinates; the workspace's
  Files shows it, with "Copy methods text".
- **Separate what the user enters from what they get.** Inputs live in the Inputs panel,
  each edited in a side sheet that says what applying will update, with one Apply
  button; output pages hold no forms (#198, #199), only the decision, search and filters,
  and small actions such as Delete or Try again. Links elsewhere that change an input
  ("Replace file" on Quality's verdict, "Change the settings" on Results) open the same
  sheet. The base period, thresholds and index settings are the workspace's (#254): their
  sheets say so when the workspace has several stations, and that the change can be undone
  until its replacement is ready. Before a workspace has stations they change on Add
  stations, in its panel "Applies to every station" (the base period and the plots,
  #233). Since #234 they are also Workspace settings on the workspace's own bar: a page
  listing the three as the Inputs panel does, each Edit opening its form on a page of its
  own, which applies it to every station and returns to the overview. **Target (#231):**
  the same as side sheets over the overview; a station's name and coordinates edited from
  "Edit inputs" on its provenance line.
- **Let the user take a change back.** A change to the workspace's settings recalculates
  every station; until that has finished, "Undo the change" beside its progress (the
  Inputs panel's runs, or the Inputs bar) puts the settings and the earlier results back
  (#254). One place per page, and a form that works without JavaScript. On the
  workspace's overview the run status line shows the recalculation's progress and offers
  "Undo the change" (#234). What can't be taken back asks first: deleting a workspace,
  from Workspaces or from its Files' "Delete workspace now", opens a page that names its
  stations and says they can't be recovered, with Cancel back to where it was chosen
  (#242, #274).
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
- **Don't offer downloads everywhere.** Files live in one Files section (a station's,
  `stations:downloads`; a workspace's, `stations:workspace_files`, #239); elsewhere at
  most one "Download all" link, plus each chart's own
  PNG/SVG/CSV. The Indices have the zip, primary in the context bar beside "Compare with
  sector data", the Files tab, and in the detail pane the selected index's CSV and PNG
  (#236, as the Results board draws it); Quality offers its flagged values as one CSV in the
  verdict strip (#235) and has one link to Files under the worklist; an index page offers
  its series' CSV, its R-style PNG and a citation (#237). The workspace's Files (#239, the
  Files board) has the workspace files (Everything, Trends and Indices of all stations,
  each with its size), each station's R files in one table (a size, or why the file is
  missing: "not run", "failed", "checking"), and the provenance file; on the overview,
  Export ▾ is its one way to them, so the run status line no longer offers the batch's
  zip.
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
  no steps (#179, #198). A first visit is Add stations (#233): one file or many,
  reviewed in one table, then "Add N stations and check them"; one station opens straight
  on its Quality, checked and calculated with the defaults, which are changed later in
  Inputs; two or more open the workspace's overview, which shows them checked and
  calculated (#234). Before it, the landing page (#242) leads to Get started (Add
  stations' empty page), or opens the sample's Indices at once ("See an example").
- **Don't throw work away when an input changes.** A new file, new station details, new
  thresholds or new settings keep the checks and results already made. They show as out
  of date (`stale_banner`, and the section's tab) until their replacement has finished,
  so the user can compare. Mark only what depends on the change: the base period changes
  Results and Files, not Quality. Nothing in the header claims the new inputs for the old
  results (#223): while they are out of date, the provenance line of the Indices, an
  index page and Files describes the run on the page (its file's years, base period,
  coordinates and settings; the Inputs panel and bar have the new values, "· changed"),
  Quality's the file its checks read (#269), as do Quality's verdict, counts, year table and values (#308), the station's entry in `climpact_run.json` the file and coordinates its results were made from, with what changed since (#307), and "Download all" says "(out of date)" and is secondary, in the context bar, its ⋯ menu and on
  Files, until the new results are ready.
- **Don't repeat a standing notice on every page** (retention, privacy). Show it once,
  where it matters, as a quiet line at the foot of the page: small muted text
  (`text-sm text-text-muted`) with a lock icon. Add stations says it once (#233).
- **Don't use colour alone.** Badges, flags and chart series carry a word or a shape too,
  and a theme's hue is always beside its name.
- **Don't take the decision out of view.** Quality is a rail of checks and a check's
  detail side by side under the verdict strip and its buttons (#202, #235, #264):
  reviewing a check or a value changes the detail in place instead of opening rows down
  the page, and the rail stays in view as the detail scrolls, so the page stays short.

## Responsive

**Desktop first** (#230): screens are designed at 1280–1600px, where the work is done.
Phones get the same content, stacked and usable, not a matched design; the accessibility
rules below still hold at every width.

Narrow screens get the same content in one column, in the same order. Below 600px the
header links and the theme toggle become a menu; on narrow screens two-column field
groups stack, and wide tables
scroll inside their focusable region rather than the page. Charts keep their table view.

On a phone (below 40rem, #203, proposal 7 of the mockups) a station's context bar is
the name (18px) and the ⋯ page menu on one line, the years under it (the base period
is in the Inputs bar, the file name in the File sheet), then the three tabs on one line
and the Inputs bar. Only the site header, the tabs and the bar stay in view as the
page scrolls (#284); the scroll padding is their height, so focus never goes under them. Sheets fill the screen.
The Indices' rows are two lines each (the significance wraps to a third at 320px when a
long slope and interval leave no room, #286) and their detail comes after the table, Quality's
check detail comes after its rail, its values table before the selected value, an index page's statistics come under its chart, which
scrolls inside its region below 32rem,
and the download tables are short blocks. The accessibility tests run every page at
320px and fail on horizontal page scroll; the sticky tests check the station and
workspace pages at 320, 375, 1280 and 1440px for sticky elements covering each other
(#284), focus and `#fragment` targets under the header and the context bar, the Inputs bar's sheets and the
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

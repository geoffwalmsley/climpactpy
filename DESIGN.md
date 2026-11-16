# Climpact web design language

The design language of the web app (`packages/climpact-web`). It records what the
interface is built from and the rules a change has to keep, so a design review has
something to check against. How the tokens, theme switch, charts and accessibility tests
work is in [`TECHNICAL.md`, "Design system"](TECHNICAL.md#design-system); this file does
not repeat it.

The rules come from the UX redesign (#171). A rule not yet met everywhere is marked
**Target**, with the ticket that brings the code in line. Phase 1 (#172–#179) left none.
Phase 2 comes from the second design review (16 Nov 2026), whose approved mockups are
[`docs/design/redesign-proposals.html`](docs/design/redesign-proposals.html) and, in the
dark theme, [`redesign-proposals-dark.html`](docs/design/redesign-proposals-dark.html);
its rules are marked **Target** with #196–#203. New work follows them.

### Phase 2 decisions

Taken with the approval of the mockups (#171):

- **The Inputs panel is the model.** Everything the user gives (the file, the station,
  the base period, the quality thresholds, the index settings) is listed in one Inputs
  panel, each with an Edit that opens a side sheet with only that form (#198, #199). The
  tabs are outputs: Quality, Results and Files.
- **Primary buttons are ink.** Near-black, near-white in the dark theme; blue is no longer
  the action colour (see [Colour](#colour)).
- **The station title comes from the station name** the user gives, not the file name;
  the file name moves to the line under it (#197). **Target:** #201 asks for the name on
  the first page.

## Who it is for

Climatologists at national meteorological services, and students and researchers. Many
read English as a second language, some work on slow or metered connections, and some
run the app offline on their own computer. They come with three questions:

1. Is this my station, described correctly? (name, latitude, base period)
2. Is the data fit to use, or should I fix the file?
3. What has changed in this station's climate, and where are the files?

Screens are organised around these questions, not around the stages of the calculation.

## Visual theme

**Calm, plain, precise: a scientific instrument.** Neutral surfaces, ink for actions and
strong type hierarchy, so the data carries the colour. It replaces the R Shiny app
(shinydashboard boxes, a sidebar menu, tabs as steps). System fonts only and no web
fonts, for bandwidth, offline use and every script the operating system supports.

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
| `--color-ink` | `#111827` | `#e6eaef` | Primary buttons, the current tab and step, links (underlined), running state |
| `--color-ink-hover` | `#374151` | `#c3cad3` | Hover on ink |
| `--color-ink-contrast` | `#ffffff` | `#0e1218` | Text on ink |
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

- **Ink** for actions: primary buttons, the current tab and step, links (underlined ink
  text, not blue), the running state (progress bars, spinners, the current stage).
  Interactive icons (a disclosure's chevron, a dropzone's icon) are ink too.
- **Brand blue** only for the logo, focus rings and selection.
- **Status colours** (success, warning, danger) only for the verdict and run state. Info
  is neutral: an info alert or badge is ink on the sunken surface.
- **Theme hues** mark data. Heat, Cold, Rain and Drought each have one hue, and the
  themes under "Also measured" share a neutral. The hue colours the theme tile's top
  edge, its pill and dot, the filter chip's dot, the catalogue row's dot, the
  sparklines and the index page's chart line (a `hue-<theme>` class on the block, from
  `stations.themes.hue_of`). The theme's name is always beside the hue.
- Hover is a neutral change (the sunken surface, or a thicker underline on links), never
  a colour of its own.

**Charts** have their own tokens (`--chart-*`): eight categorical slots in a fixed order,
never cycled; variable roles (`tmax` red, `tmin` blue, `prcp` green, checked as a set
for colour-vision deficiency), which the daily and quality charts keep: the theme hues
are for indices, the variable roles for the station's variables; trend, band, grid and axis; a five-step sequential and a
seven-step diverging scale for maps. QC flags are hollow rings in ink, told apart by
shape rather than colour. `chart-palette.json` carries the same values to the static
plots and the PDF report.

**Severity colours mean severity.** Danger is for something that stops the user or is
almost certainly wrong. Warning is for something worth a look. Use neither for "the
check found something" on its own (see Rules).

## Typography

`--font-sans` is the system UI stack; `--font-mono` is used for index codes, file names
and dates in tables. The scale is set by hand (about 1.125 to 1.25 between steps),
font size only; line height is `--leading-normal` 1.6 for text and `--leading-tight`
1.25 for headings.

| Token | Size | Role |
| --- | --- | --- |
| `--text-hero` | clamp(2rem … 3rem) | Home page heading only |
| `--text-2xl` | 2rem | Page title (h1) |
| `--text-xl` | 1.5rem | Section heading (h2) outside a station; a station's name in its workspace header |
| `--text-lg` | 1.25rem | Card title, stat value; a section heading (h2) in a section header and on a station's pages |
| `--text-md` | 1.125rem | Lead paragraph under a title |
| `--text-base` | 1rem | Body, controls |
| `--text-sm` | 0.875rem | Table cells, hints, help links |
| `--text-xs` | 0.8125rem | Badges, captions, footer, group labels, the Help pill |

Weights: 400, 500, 600, and 650 for bold. Headings never skip a level.

Small uppercase labels name groups (`group-label`, stat labels: `--text-xs`, 600,
letter-spacing 0.06em, muted); they group without adding boxes. Where a page has an
answer, its number is large (`--text-2xl`, 650, in the answer band), with the rest smaller
and muted.

## Layout

- **Width:** content up to `--container-content` (72rem), reading text up to
  `--container-prose` (42rem).
- **Spacing:** one step is 0.25rem (`--spacing`), a 4px grid. Common steps: 2 (0.5rem)
  inside controls, 4 to 5 (1–1.25rem) inside cards, 8 to 12 (2–3rem) between sections.
- **Breakpoints:** `sm` 40rem, `md` 52rem, `lg` 60rem, `xl` 64rem. Logical properties
  only, so right-to-left scripts work (checked by `test_static.py`).
- **Page frame:** header (logo, main destinations, theme toggle) → step indicator for the
  batch and gridded flows → title and one-line lead → content → footer. A station is a
  workspace instead: its name as the h1, a line with its years and base period, then the
  section tabs (Quality, Results, Files), then the Inputs panel and the section's content
  side by side. The h1 is the station name the user gives, with the file name on the
  line under it. The workspace header (name, that line, the page's actions, the tabs)
  stays in view as the page scrolls, from 40rem wide; the page's scroll padding keeps a
  focused element out from under it (WCAG 2.4.11). The Inputs panel (16rem) sits at the
  inline start, in view under the header as the page scrolls, where the content has at
  least 52rem (a container query, so the help drawer counts); narrower, it comes above
  the content. What is in the file ("Your data") is the last section of Quality (#198).
- **Sections:** one surface level. A page's sections sit on the page, 48px apart
  (`stack--xl`), each under a section header; a box marks only one object (a theme tile,
  a chart, a progress card). The page's one answer is a tinted band (`answer-band`).
- **Controls:** `--control-height` 2.75rem (2.25rem small), so touch targets reach 44px.

## Depth and shape

| Level | Token | Used for |
| --- | --- | --- |
| 0 | none | Page background, a page's sections, content inside a card, the answer band (a tint, no border or shadow) |
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
| `section-header` | Component | A section's heading, an optional muted note (`section-header__note`), then the Help pill (`{% section_help %}`) at the end of the row. The pill is 30px high with a ringed question mark and a word: "Help", or a question where it helps (`label="How to read this"`) | with note, with a specific label |
| `answer-band` | Pattern | The page's one answer in a tint, no border or shadow; a large number with its words under it (`answer-band__number`) and a sentence. The Quality verdict keeps its status tint | — |
| `field`, `field_errors` | Component | Label, short hint, input, unit, inline error; no help link of its own | narrow, with unit |
| `dropzone` | Component | File input with drag and drop; works without JS | — |
| `file_button` | Component | A button that opens the file picker and sends the chosen file at once, for a second upload where a drop zone takes too much room; a file input and a submit button without JS. Unused since Quality's corrected file became the File sheet (#199) | primary, secondary; lg, sm |
| `form_errors` | Component | Error summary that links to each field, focused on load | — |
| `card` | Component | Grouped content; whole-card link | link, muted, with badge |
| `alert`, `messages`, `toasts` | Component | Page and transient feedback | info, success, warning, error; dismissible; live |
| `disclosure` | Component | Content that opens in place (`<details>`): a row between hairlines, not a box | — |
| `dialog` | Component | Native modal with focus kept inside | confirm, danger |
| Inputs panel | Component | Everything the user gave, beside a station's sections (`stations/_inputs.html`): a group label, then each input as a row of its name (muted), its value (semibold) and one link at the end, Edit or Replace, on a sunken tint without a border. The thresholds and index settings read "Defaults" or how many were changed ("2 changed"). An input changed since the checks or results shown has the warning tint and says "changed" after its name; the run of the new inputs shows its progress in a box beneath the list, polled until it finishes. Sticky under the workspace header when beside the content | changed; with a run |
| Side sheet | Component | One input's form at the inline end, the screen's full height (`stations/_input_sheets.html`, `js/sheet.js`): a title and close button, the form's fields, what applying will update in a warning tint (`impact`), then one primary button, Apply, and Cancel at its foot. **Modal**, unlike the drawer: the form is being edited and applying starts a run, so it is a native `<dialog>` opened with `showModal()`: a backdrop, the page behind inert, focus on the first field and kept inside, Escape, Cancel, close or a click on the backdrop closes it and discards what was typed, and focus returns to the Edit link. Without JS, Edit links to the same form on its own page; a form with errors returns there. A long form (the index settings) scrolls inside the sheet with Apply kept in view at the foot, rather than widening the sheet; its groups are divided by rules, and their help opens in place, since the drawer would be behind the modal | base period, index settings |
| `drawer` | Component | A section's help in a side panel, opened by the Help pill of the section's header (`{% section_help %}`). Not modal: no backdrop, no focus trap. Beside the content from 64rem, below it on narrower screens. Escape or close returns focus to the pill. Without JS the pill links to the same help on its own page. The Help pill in the app bar opens the page's guide | — |
| `table`, `summary_list` | Component | Data in a keyboard-scrollable region, hairline rows and no frame; key–value pairs | empty state |
| `tabs` | Component | ARIA tablist; all panels show without JS | — |
| `workspace_tabs` | Component | A station's sections as tabs under its name, in the sticky workspace header (`stations/_workspace.html`). Each is a page of its own, so they are links in a named `nav` with `aria-current="page"`, not a tablist; Tab moves between them. Each has a status: an icon of its own shape and a word (done `check-circle`, needs attention `warning`, out of date `clock`, running `refresh`, not started `circle`, not available yet `lock`). The word shows for the states that need the user and is read by screen readers for all. A section not available yet is not a link. Looks like `tabs` | — |
| `progress`, `stages`, `skeleton` | Component | Running jobs and loading content | determinate, indeterminate |
| `chart_frame` | Pattern | Chart with title, text summary, legend, zoom, PNG/SVG, table view, CSV | — |
| `theme_headline` | Pattern | A theme tile, the finding first: one sentence from the trends, up to three trends, each on one line (the plain name, the value with short units, "pp / decade", and a sparkline), a link to the rest. Its hue on the top edge, the dot, the pill and the sparklines. Four in a 2 x 2 grid under "By theme" | changed, quiet (no change: the sunken surface, one sentence, no trends) |
| Catalogue | Pattern | Every index in one table (`stations/results.html`, `js/results.js`): above it, theme chips (`chip`, with the hue's dot and a muted count; "Also measured" for the rest), "Significant only" as a chip and a search box at the end of the row; below them a live line that says how many rows show and how they are sorted. Columns: the index (dot and plain name, a link, the row's header), code, trend per decade, significance, sparkline. Each header but the sparkline's sorts the table: a link without JavaScript, a button with it (`sort`, an arrow for the order), `aria-sort` on the sorted column. The table scrolls in its focusable region under a sticky header, so the page stays short. Without JavaScript the filters are a form and every row is in the page | filtered, sorted, no match |
| `download_link` | Primitive | One file to download: a small secondary button with its format and size, the file named for screen readers | — |
| `spark` | Primitive | Decorative sparkline beside a trend given in words | line, bars |
| `steps` | Pattern | Where the user is in the batch or gridded flow; done steps link back. Not used by the station, whose sections are `workspace_tabs` (#179) | — |
| `stale_banner` | Pattern | Results kept on the page after an input changed: what changed, in words, and what happens next. An info alert with the new run's progress while it is on the way; a warning alert with one action ("Recalculate", or a link to fix the input) otherwise. The results below sit in a `stale-content` block: a dashed warning edge and greyed sparklines, the text at full contrast | updating, out of date |
| `empty_state` | Pattern | Nothing to show yet, with the next action | — |
| File group | Pattern | A long list of files behind a closed native `<details>` (`disclosure download-group`): the summary gives the group's name, the count and the total size, and opens to a table with a `download_link` per file; on phones each row becomes a short block. Each index section and the quality checks on Files; markup in `stations/downloads.html` | — |

Patterns built in a page's own templates, not yet in `/patterns/` (the Quality page,
`stations/templates/stations/_qc_*.html`, and Results):

| Pattern | Purpose | Built from |
| --- | --- | --- |
| Verdict | The answer and the one decision on it. An h2 title, one or two sentences, a line of counts against what was checked, and the decision's buttons. One primary button; on red the buttons swap, and a "… anyway" secondary always stays. "Replace file" opens the File sheet (#199). | `alert`, `button`, side sheet |
| Worklist group | A list of native `<details>` in one surface with dividers. Each summary has a title, a muted one-line note and a count chip (`qc-count`: neutral, the words carry the severity). It opens to its rows. Keyboard use is native. | `<details>`, `table` |
| Finding sparkline | A small SVG of the days around one value, drawn on the server, with the value ringed in `--chart-flag` as on the full charts. It is `aria-hidden`: the row's sentence is its text summary, "Days around it" its table view, and "Show on chart" leads to the full chart and its CSV. | `chart_frame` for the full chart |
| Settings line and panel | The settings in one muted line under the page title: the defaults, or what was changed, and a link that opens them in place. The form is one closed `disclosure` near the foot of the page, its groups divided by rules, not cards; one button at the end. `stations/_settings_form.html` | `disclosure`, `field`, `button` |
| Recalculation | A run that replaces results already shown, of the same inputs: its progress in a card with an ink edge above the results, which stay until it finishes. A failure says so in the same card, with "Try again". When the inputs changed (#179) the `stale_banner` takes its place, with the same progress inside. | `card`, `progress`, `stages` |

Every chart has a text summary, a table view and a CSV download, and can be used by
keyboard. This is not optional.

## Rules

### Do

- **One primary action per view.** One `button--primary` per screen or decision area, and
  it says what happens next with a verb ("Use this data", "Calculate"). A form's one
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
- **Give units with every number,** including stats and trends (percentage points for
  trends of percentage indices).
- **Plain names first, codes second.** "Hot days" with `TX90p` beside it, never the
  code alone.
- **Separate what the user enters from what they get.** Inputs live in the Inputs panel,
  each edited in a side sheet that says what applying will update, with one Apply
  button; output pages hold no forms (#198, #199), only the decision, search and filters,
  and small actions such as Delete or Try again. Links elsewhere that change an input
  ("Replace file" on Quality's verdict, "Change the settings" on Results) open the same
  sheet.
- **Give each colour one job.** Ink for actions, the brand blue for the logo, focus and
  selection, status colours for the verdict and run state, theme hues for data (see
  [Colour](#colour)).
- **Make help visible.** A section header is its title, an optional muted note, then a
  labelled Help button at the end of the row (a pill with a word, specific where it helps:
  "How to read this"). At most one per section, none on sections that explain
  themselves; a Help button in the app bar opens the page's guide.
- **Group findings by what people ask about.** Results lead with the answer in a tinted
  band (the count, and one paragraph whose first sentence is bold), then a tile per theme
  (Heat, Cold, Rain, Drought), then the 80 indices as one table, filtered by theme chip
  ("Also measured" for the rest), significance and search, and sortable by any column,
  with no family accordions. "No significant change" is a finding, shown in a quiet
  tile, not left out. Findings are template sentences built from the data, never
  written by hand for a station. The theme mapping lives in `stations/themes.py`.
- **Never change the user's data, and say so.** The app reports; the user decides.

### Don't

- **Don't put cards inside cards.** One surface level on the page: sections are
  separated by space and a heading, not boxes. A box marks only something that is one
  object (a theme tile, a chart, a finding); the page's one answer sits in a tinted band;
  tables have hairline rows and no frame, and disclosures are rows between hairlines.
  Inside a card, separate groups with spacing and headings, not another border.
- **Don't offer downloads everywhere.** Files live in one Files section
  (`stations:downloads`); elsewhere at most one "Download all" link, plus each chart's own
  PNG/SVG/CSV. Results have the zip, primary in the workspace header beside "Compare with
  sector data", and the Files tab; Quality has one link to Files
  under Details; an index page has only its chart's exports.
- **Don't put a help link under every field.** One Help button per section opens that section's help
  in the drawer (in a modal sheet, a disclosure in place); a field keeps a hint only when
  its value isn't self-explanatory. Section
  help lives in `help/sections.py`: notes plus the fields' help topics.
- **Don't show a step's results before the step.** QC flags belong to Quality, not to the
  Load chart (it asks for `?flags=0`).
- **Don't add a page or step without a decision on it.** A screen that only confirms
  defaults should be an inline action instead. The index settings are "Adjust and
  recalculate" on Results, and the defaults are calculated while the user checks the
  quality (#178). The station is a workspace of three sections beside its inputs, with
  no steps (#179, #198). The first visit still confirms the details on a page of its own
  (the old Data form and summary), until #201.
  **Target:** #201: a first visit is one New station page (the file, the station name,
  latitude and longitude, the base period, then "Check and calculate"); thresholds and
  index settings start at their defaults and are changed later in Inputs.
- **Don't throw work away when an input changes.** A new file, new station details, new
  thresholds or new settings keep the checks and results already made. They show as out
  of date (`stale_banner`, and the section's tab) until their replacement has finished,
  so the user can compare. Mark only what depends on the change: the base period changes
  Results and Files, not Quality.
- **Don't repeat a standing notice on every page** (retention, privacy). Show it in full
  once, where it matters. After that it is a quiet line at the foot of the page: small
  muted text (`text-sm text-text-muted`) with a lock icon.
- **Don't use colour alone.** Badges, flags and chart series carry a word or a shape too,
  and a theme's hue is always beside its name.
- **Don't take the decision out of view.** **Target:** #202: Quality is a list and a
  detail side by side, with the verdict and its buttons kept in view.

## Responsive

Narrow screens get the same content in one column. Below 600px the header links become a
menu; on narrow screens the step indicator shows only the current step's label, the
workspace tabs wrap onto a second line,
two-column field groups stack, and wide tables scroll inside their focusable region
rather than the page. Charts keep their table view. The accessibility tests run every page
in a 320px viewport and fail on horizontal page scroll. **Target:** #203: on phones the
Inputs panel collapses into a one-line bar with an Edit button, and the theme tiles
stack.

## Agent prompt guide

- Use tokens only: no hex values, no Tailwind default colours or sizes (they aren't
  loaded). New colours need light and dark values and pass the contrast test. Ink for
  actions and links, `--color-brand` only for the logo, focus and selection, status
  colours only for the verdict and run state, `hue-*` for a theme's data.
- Build from `core/templates/components/` and add new parts to `/patterns/`. After
  changing classes, run `scripts/build-css.sh` and commit `css/climpact.css`.
- One primary action per view, answer before detail, severity in proportion. Check a
  new screen against the three user questions above.
- Every chart keeps its text summary, table view, CSV and keyboard controls; every page
  passes the axe tests in light and dark (`uv run pytest -m browser`; they are
  deselected by default and CI runs them).
- Logical CSS properties only; strings through `{% translate %}`; no inline scripts or
  styles (Content Security Policy).

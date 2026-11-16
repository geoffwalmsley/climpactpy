# Climpact web design language

The design language of the web app (`packages/climpact-web`). It records what the
interface is built from and the rules a change has to keep, so a design review has
something to check against. How the tokens, theme switch, charts and accessibility tests
work is in [`TECHNICAL.md`, "Design system"](TECHNICAL.md#design-system); this file does
not repeat it.

The rules marked **Target** come from the UX redesign (#171) and are not met everywhere
yet. Each names the ticket that brings the code in line. New work follows them now.

## Who it is for

Climatologists at national meteorological services, and students and researchers. Many
read English as a second language, some work on slow or metered connections, and some
run the app offline on their own computer. They come with three questions:

1. Is this my station, described correctly? (name, latitude, base period)
2. Is the data fit to use, or should I fix the file?
3. What has changed in this station's climate, and where are the files?

Screens are organised around these questions, not around the stages of the calculation.

## Visual theme

**Calm, plain, precise: a scientific instrument.** Neutral surfaces, one blue accent and
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
| `--color-accent` | `#0a5aa8` | `#6db3f2` | Primary buttons, links, current step |
| `--color-accent-soft` | `#e5eff9` | `#132a40` | Info alerts, selected states |
| `--color-focus` | `#0b57d0` | `#8ab4f8` | Focus ring |
| `--color-success` / `-soft` | `#17773a` / `#e7f4ea` | `#5cc97e` / `#10291a` | Passed, done |
| `--color-warning` / `-soft` | `#8a5300` / `#fdf3dc` | `#e9b04a` / `#2e2410` | Worth a look |
| `--color-danger` / `-soft` | `#b3261e` / `#fbeae8` | `#ff8c82` / `#351513` | Errors, destructive actions |

**Charts** have their own tokens (`--chart-*`): eight categorical slots in a fixed order,
never cycled; variable roles (`tmax` red, `tmin` blue, `prcp` green, checked as a set
for colour-vision deficiency); trend, band, grid and axis; a five-step sequential and a
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
| `--text-xl` | 1.5rem | Section heading (h2) |
| `--text-lg` | 1.25rem | Card title, stat value |
| `--text-md` | 1.125rem | Lead paragraph under a title |
| `--text-base` | 1rem | Body, controls |
| `--text-sm` | 0.875rem | Table cells, hints, help links |
| `--text-xs` | 0.8125rem | Badges, captions, footer |

Weights: 400, 500, 600, and 650 for bold. Headings never skip a level.

## Layout

- **Width:** content up to `--container-content` (72rem), reading text up to
  `--container-prose` (42rem).
- **Spacing:** one step is 0.25rem (`--spacing`), a 4px grid. Common steps: 2 (0.5rem)
  inside controls, 4 to 5 (1–1.25rem) inside cards, 8 to 12 (2–3rem) between sections.
- **Breakpoints:** `sm` 40rem, `md` 52rem, `lg` 60rem, `xl` 64rem. Logical properties
  only, so right-to-left scripts work (checked by `test_static.py`).
- **Page frame:** header (logo, main destinations, theme toggle) → step indicator for a
  flow → title and one-line lead → content → footer.
- **Controls:** `--control-height` 2.75rem (2.25rem small), so touch targets reach 44px.

## Depth and shape

| Level | Token | Used for |
| --- | --- | --- |
| 0 | none | Page background, content inside a card |
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
| `button` | Primitive | Action, or a link styled as one | primary, secondary, ghost, danger; lg, sm; icon, icon only |
| `badge` | Primitive | Status in words, never colour alone | info, success, warning, danger |
| `stat` | Primitive | One number with label and note | — |
| `field`, `field_errors` | Component | Label, hint, input, unit, inline error, help topic | narrow, with unit |
| `dropzone` | Component | File input with drag and drop; works without JS | — |
| `form_errors` | Component | Error summary that links to each field, focused on load | — |
| `card` | Component | Grouped content; whole-card link | link, muted, with badge |
| `alert`, `messages`, `toasts` | Component | Page and transient feedback | info, success, warning, error; dismissible; live |
| `disclosure` | Component | Help that opens in place (`<details>`) | — |
| `dialog` | Component | Native modal with focus kept inside | confirm, danger |
| `table`, `summary_list` | Component | Data in a keyboard-scrollable region; key–value pairs | empty state |
| `tabs` | Component | ARIA tablist; all panels show without JS | — |
| `progress`, `stages`, `skeleton` | Component | Running jobs and loading content | determinate, indeterminate |
| `chart_frame` | Pattern | Chart with title, text summary, legend, zoom, PNG/SVG, table view, CSV | — |
| `steps` | Pattern | Where the user is in a flow; done steps link back | optional step |
| `empty_state` | Pattern | Nothing to show yet, with the next action | — |

Every chart has a text summary, a table view and a CSV download, and can be used by
keyboard. This is not optional.

## Rules

### Do

- **One primary action per view.** One `button--primary` per screen or decision area, and
  it says what happens next with a verb ("Use this data", "Calculate").
- **Answer first, detail on request.** Lead with the finding or verdict, then the
  evidence; tables, distributions and file lists go below or behind a disclosure.
- **Keep severity in proportion to the data.** State counts against what was checked
  ("5 of 87,600 values"). Red means "fix this before going on", not "the check found
  something". **Target:** QC verdict, #174.
- **Write short, plain sentences.** One idea per sentence; no chains of colons and
  semicolons; a verb on every button. Assume the reader is working in a second language.
  **Target:** copy pass, #177.
- **Give units with every number,** including stats and trends (percentage points for
  trends of percentage indices). **Target:** #173.
- **Plain names first, codes second.** "Hot days" with `TX90p` beside it, never the
  code alone.
- **Never change the user's data, and say so.** The app reports; the user decides.

### Don't

- **Don't put cards inside cards.** One surface level on the page; separate groups inside
  a card with spacing and headings, not another border and shadow. **Target:** #173,
  #174.
- **Don't offer downloads everywhere.** Files live in one Files section; elsewhere at most
  one "Download all" link, plus each chart's own PNG/SVG/CSV. **Target:** #176.
- **Don't put a help link under every field.** One ⓘ per section opens that section's help
  in a side panel; a field keeps a hint only when its value isn't self-explanatory.
  **Target:** #177.
- **Don't show a step's results before the step.** QC flags belong to Quality, not to the
  Load chart. **Target:** #173.
- **Don't add a page or step without a decision on it.** A screen that only confirms
  defaults should be an inline action instead. **Target:** #178.
- **Don't repeat a standing notice on every page** (retention, privacy). Say it once
  where it matters and keep a quiet line in the footer. **Target:** #173.
- **Don't use colour alone.** Badges, flags and chart series carry a word or a shape too.

## Responsive

Narrow screens get the same content in one column. Below 600px the header links become a
menu; on narrow screens the step indicator shows only the current step's label,
two-column field groups stack, and wide tables scroll inside their focusable region
rather than the page. Charts keep their table view. The accessibility tests run every page
in a 320px viewport and fail on horizontal page scroll.

## Agent prompt guide

- Use tokens only: no hex values, no Tailwind default colours or sizes (they aren't
  loaded). New colours need light and dark values and pass the contrast test.
- Build from `core/templates/components/` and add new parts to `/patterns/`. After
  changing classes, run `scripts/build-css.sh` and commit `css/climpact.css`.
- One primary action per view, answer before detail, severity in proportion. Check a
  new screen against the three user questions above.
- Every chart keeps its text summary, table view, CSV and keyboard controls; every page
  passes the axe tests in light and dark (`uv run pytest -m browser`; they are
  deselected by default and CI runs them).
- Logical CSS properties only; strings through `{% translate %}`; no inline scripts or
  styles (Content Security Policy).

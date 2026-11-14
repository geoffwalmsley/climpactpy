# Accessibility audit of Climpact web (WCAG 2.1 AA)

Audit of the finished web app for #83 (epic #11), 14 November 2026. The statement for
users is the help guide `/help/accessibility/` (`help/guides/en/accessibility.md`); how
the checks work is in `TECHNICAL.md`, "Accessibility".

## What was checked, and how

Every page type, with real results: `tests/test_accessibility.py` starts `climpact-web`
(with its worker) on a free port and drives the installed Google Chrome, headless with a
throwaway profile, over the DevTools protocol. It goes through the Sydney sample station
(steps 1 to 5 and the downloads), the sample batch and the 3 x 4 sample grid in the
browser, so the worker runs real jobs. That gives these 36 pages and states:

| Area | Pages |
| --- | --- |
| Shell | landing, pattern library, 404, 413 (an upload over the limit), 500 |
| Station | upload, upload with errors, sample loaded, details with errors, quality results, a quality check's table page, indices, indices with errors, results dashboard, an index page (txx), an index page with anomalies (spi), downloads, sector form, sector results |
| Batch | start, check, results |
| Gridded | start, set-up, results (map, explorer, chart) |
| Jobs | calculations list, a calculation |
| Help | index, a guide, the indices guide, topics, search, the accessibility statement |
| While running | quality checks, station run, sector comparison, batch, gridded run (axe, and what is announced) |

On every page the test records:

| Check | WCAG 2.1 | How |
| --- | --- | --- |
| axe-core 4.14, all A and AA rules and best practices | many | light theme and 320 px wide; contrast rules again in the dark theme |
| No horizontal scrolling | 1.4.10 Reflow, 1.4.4 Resize text | 320 CSS px (= 400% zoom of 1280 px) and 200% zoom of 1280 px (640 px at scale 2), after the page has drawn (as when a user zooms) |
| Tab order, no trap, visible focus | 2.1.1, 2.1.2, 2.4.3, 2.4.7 | Tab from the top until focus comes back round; every stop visible, with an outline (or a box shadow outside forced colours) on it or a near ancestor; no positive `tabindex` |
| Skip link | 2.4.1 | first Tab stop; Enter moves focus to `main` |
| Forced colours | 1.4.11, 2.4.7 | the Tab traversal again under `forced-colors: active` (box shadows are not drawn there, so only outlines count) |
| Reduced motion | 2.3.3 | under `prefers-reduced-motion: reduce`, no animation or transition over 0.1 s, no smooth scrolling |
| Structure | 1.3.1, 2.4.2, 3.1.1, 4.1.2 | `lang`, a title, one `main`, one `h1`, names on regions, groups, toolbars, navigation and tab lists |
| Progress announced | 4.1.3 | while each job runs, what the page's announcer says; the batch's end announced |
| Focus kept across updates | 2.4.3 | focus on the batch's Cancel button survives the progress polls |

Widgets, worked by keyboard in their own tests: tabs (arrow keys, Home, End, one Tab stop),
the dialog (opens with focus inside, Tab stays inside, Escape closes and returns focus),
the drop zone (a Tab stop with a visible outline; Space opens the file chooser), an
interactive chart (Tab stop; +, arrows and 0; each change announced; table view opens),
the tour (starts from the keyboard, takes focus, Escape closes and puts focus somewhere
useful), the help search (results announced, focus stays in the field) and the gridded
explorer (focus stays on the select as the map is swapped).

Colour contrast of every token pairing in both themes is checked separately by
`tests/test_design_tokens.py` (#71).

Run locally with `uv run pytest packages/climpact-web/tests/test_accessibility.py`;
set `CLIMPACT_A11Y_REPORT=<folder>` for a JSON report and screenshots (light, dark,
forced colours and 320 px of every page). CI runs it in the `web-accessibility` job with
the runner's Chrome and keeps the report as an artifact.

## What was found and fixed

| Finding | WCAG | Fix |
| --- | --- | --- |
| Progress of a running job (station run, sector, batch, gridded, job page, the checks) was not announced: each poll replaced the whole fragment, live region included, and screen readers do not read a live region that is new | 4.1.3 | one persistent announcer (`#announcer`, `role="status"`) in the page shell; fragments mark their news with `data-announce` and `ui.js` passes it on when it changes, at most every 10 s unless marked `now` (a finished batch or job). The help search count, the batch estimate and the gridded set-up checks, also swapped in, use it too |
| Keyboard focus on a control inside a polled fragment (Cancel) was lost to the page at every poll | 2.4.3 | `ui.js` notes the focused control before an htmx swap and focuses the same control (same id, or same form and kind) after it |
| Interactive charts kept the page wide when the window narrowed or the page was zoomed after drawing (the canvas set the frame's minimum width) | 1.4.4, 1.4.10 | the chart frame's grid column is `minmax(0, 1fr)`, so it shrinks and the chart redraws to fit |
| Gridded set-up wider than 320 px: the form's grid column took the width of its widest content, and an output file name in the checks could not wrap | 1.4.10 | `.form` grid column `minmax(0, 1fr)`; file names in the checks break anywhere |
| A calculation's page wider than 320 px: a long station name in the `h1` | 1.4.10 | headings break long words (`overflow-wrap: anywhere`) |
| The tour gave focus back to its (hidden) invitation button when closed, so focus was lost | 2.4.3 | focus goes to the main content when the opener is gone or hidden |
| 500 page: no `main` landmark, no way on, and in a dark system theme its link had 2.4:1 contrast | 1.3.1, 1.4.3 | a `main`, a link to the start page, system colours that follow the theme |
| Help guide tables: scrolling regions without a name | 4.1.2 | named by the heading above the table |
| Downloads page and index page: a table region with the same name as its section | best practice | each table has its own caption |
| Index page: the chart's title was an `h3` straight after the `h1` | 1.3.1 | the chart frame takes a heading level; the index chart's is `h2` |
| Pattern library: three step indicators with one name, and a second `h1` in the type specimen | best practice, 1.3.1 | the examples are named; the specimen's "Heading 1" is a paragraph drawn as an `h1` |

After the fixes every check above passes on every page: no axe violations of any impact.

## Known limitations (not fixed here)

- The PDF report and the plots PDF (PR #109) are not tagged PDF (PDF/UA). Follow-up:
  #110.
- The PNG plots have no text alternative inside the files; their data are in the CSVs.
- The gridded map's cells are mouse targets only; the latitude and longitude selects are
  the keyboard equivalent, and the map has a table.
- Screen readers have not been tested by hand yet: see the checklist below.

## Screen reader checklist (by hand)

Automated checks cannot tell how a page sounds. Do these with **VoiceOver** (macOS,
Safari; Cmd+F5) and **NVDA** (Windows, Firefox or Chrome), using the sample data. Tick
each line for each screen reader and note anything odd in the issue (#83) or a new ticket
under epic #11.

| # | Do | Expect | VoiceOver | NVDA |
| --- | --- | --- | --- | --- |
| 1 | Open the landing page; list the landmarks (VO: rotor; NVDA: D) and headings (VO: rotor; NVDA: H) | banner, Main navigation, main, contentinfo; one h1 "Climpact..." then sensible h2s | [ ] | [ ] |
| 2 | Tab once, press Enter | "Skip to main content", then reading starts in the main content | [ ] | [ ] |
| 3 | Take the tour with the keyboard | the tour box is announced as a dialog with its title and text; Next/Back/Done work; Escape closes it | [ ] | [ ] |
| 4 | Theme buttons in the header | each announced with its name and pressed state | [ ] | [ ] |
| 5 | Single station: upload page, "Use the sample data" | the step indicator says "Step 1 of 5: Load data, current step" | [ ] | [ ] |
| 6 | Step 1: submit the details with a latitude of 123 | the error summary is announced and focused; each link moves to its field; the field reads its error | [ ] | [ ] |
| 7 | Step 1: the daily chart; Tab to the plot | announced as a chart with its title and summary; +, arrows and 0 announce the visible period | [ ] | [ ] |
| 8 | Step 1: open the chart's table view | a table with column headers; reading a cell gives its date and variable | [ ] | [ ] |
| 9 | Step 2: run the checks | "Running the quality checks" announced; the results arrive and are read | [ ] | [ ] |
| 10 | Step 2: a check's table, next page | the table and its page number are read; focus stays sensible | [ ] | [ ] |
| 11 | Step 3: start the calculation; wait | the stages are announced every few seconds without having to move; the dashboard opens at the end | [ ] | [ ] |
| 12 | Step 3: Tab to Cancel while it runs, wait 10 s | focus stays on Cancel; it is not re-announced at every update | [ ] | [ ] |
| 13 | Step 4: type in "Find an index" | the count "Showing n of 80 indices" is announced | [ ] | [ ] |
| 14 | Step 4: a sparkline card | the card reads as one link with the index name and trend; the sparkline is not read as noise | [ ] | [ ] |
| 15 | Downloads: list the links | each download names its file and size | [ ] | [ ] |
| 16 | Step 5: the sample sector data | progress announced; the bar chart and scatter plots have tables that read well | [ ] | [ ] |
| 17 | Batch: sample, run | the stations' progress and "n of 3 stations calculated" announced | [ ] | [ ] |
| 18 | Gridded: sample, set-up; change the variable selects | the checks under the form are announced | [ ] | [ ] |
| 19 | Gridded results: change Year, then Cell latitude | focus stays on the select; the map title and the cell's values change and can be read; the map table reads | [ ] | [ ] |
| 20 | Help: type in the search | "n results for ..." announced; results are a list of links | [ ] | [ ] |
| 21 | Help topics (the "?" disclosures) on any form | announced as collapsed/expanded buttons; the text is read after opening | [ ] | [ ] |
| 22 | Pattern library: tabs and the dialog | tabs: "tab, 1 of 3, selected"; dialog: announced with its title, Escape returns to the button | [ ] | [ ] |
| 23 | Any page at 200% zoom with the screen reader on | nothing is lost or overlaps; reading order matches the visual order | [ ] | [ ] |
| 24 | Windows high contrast (NVDA machine): Tab through step 3 | the focus outline is always visible; chart lines and map cells are distinguishable | n/a | [ ] |

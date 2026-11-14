title: Accessibility statement
summary: The standard Climpact web aims to meet, how it was tested, what is known not to work yet and how to report a problem.

## Our aim {#aim}

Climpact web should be usable by everyone, including people who use a screen reader,
a keyboard instead of a mouse, magnification, high-contrast colours or speech input,
and people on slow connections. It aims to meet the
[Web Content Accessibility Guidelines (WCAG) 2.1](https://www.w3.org/TR/WCAG21/) at
level **AA**, the standard most public bodies are held to.

You should be able to:

- use every page with the keyboard alone, with the focus always visible;
- zoom to 200% or use a window 320 pixels wide without scrolling sideways;
- use the high-contrast (forced colours) modes of Windows and the light and dark themes;
- turn off animation (the "reduce motion" setting of your system);
- read every chart as a table and download its data as CSV;
- hear the progress of a long calculation announced by a screen reader.

## Conformance status {#status}

Climpact web **partially conforms** to WCAG 2.1 AA: the checks below pass on every page,
but testing with screen readers by hand is not finished, and the files listed under
[Known limitations](#limitations) do not conform.

## How it was tested {#testing}

On 14 November 2026 every type of page of Climpact web was checked
with real results: the sample station through all five steps and its downloads, the
sample batch, the sample grid, the help pages, the calculations list and the error
pages.

- **Automated checks** with [axe-core](https://github.com/dequelabs/axe-core) 4.14 in
  Google Chrome: every WCAG 2.1 A and AA rule and axe's best practices, in the light theme,
  the dark theme and a 320 pixel wide window. No violations were found. These checks run
  on every change to the code.
- **Keyboard**: each page was gone through with the Tab key from top to bottom, checking
  that the "Skip to main content" link comes first and works, that every control can be
  reached in a sensible order, shows where the focus is, and that focus never gets stuck.
  The tabs, dialogs, file drop zones, interactive charts, the tour, the help search and
  the gridded map's controls were each worked with the keyboard.
- **Zoom and small screens**: each page at 200% zoom and 320 pixels wide.
- **High contrast**: each page with forced colours on, checking that the focus outline
  stays visible.
- **Reduced motion**: each page with the setting on, checking that nothing animates.
- **Structure**: each page has a language, a title, one main heading, landmarks, and
  names on its regions, form fields and buttons.
- **Progress**: while each kind of calculation ran, that its progress is announced to
  screen readers and that the focus stays on the Cancel button as the progress updates.

Colour contrast of every pairing of text and background in both themes is also checked
by a test of the design tokens.

A checklist for testing with VoiceOver (macOS) and NVDA (Windows) is kept with the source
code (`packages/climpact-web/docs/accessibility-audit.md`), with the full audit; those
tests are done by hand.

## Known limitations {#limitations}

- **The PDF report and the PDF of plots** (in the downloads) are not tagged PDFs
  (PDF/UA), so a screen reader cannot follow their structure or read the plots. The same
  information is on the results pages and in the CSV files of the downloads.
- **The plot images** (PNG files in the downloads and the zip) have no text description
  inside the files. Each plot's values are in the matching CSV file, and every chart on
  the results pages has a table view.
- **The map of the grid** (gridded results) is drawn as a picture: its cells can be
  clicked with a mouse but are not keyboard controls. Choose a cell with the
  **Cell latitude** and **Cell longitude** lists instead, and read the map's values in its
  table.
- **The interactive charts** draw on a canvas. Their summary, keyboard controls and table
  view give the same information; very long daily series are easier to read from the CSV
  file.
- **Screen readers**: testing by hand with VoiceOver and NVDA is not finished.
- **Languages**: the interface is in English only for now.

## Reporting a problem {#report}

If something on Climpact web is hard or impossible for you to use, please tell us, and
say which page, what you were trying to do, and the browser and any assistive technology
you use. We will try to fix it, or give you the information in another way.

- Open an issue on the project's
  [issue tracker](https://github.com/geoffwalmsley/climpactpy/issues).
- If you use a hosted installation of Climpact, you can also contact the organisation
  that runs it.

This statement was prepared on 14 November 2026. It will be reviewed when the app changes
significantly.

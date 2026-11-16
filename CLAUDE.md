# climpactpy

Python port of Climpact (R). See `README.md` for setup and `TECHNICAL.md` for the
architecture, parity testing and the differences between the Python and R implementations.

## Working rules

- The repository is a uv workspace. `uv sync` makes the project virtualenv (`.venv`) from
  `uv.lock`; run all Python through it with `uv run`: `uv run python`, `uv run pytest`,
  `uv run ruff`, `uv run climpact-web`. Never install packages globally, and use uv only
  for the project environment.
- The repository holds two packages, both workspace members: the core in
  `packages/climpact` (distribution `climpact`; `src/climpact`, its tests and the R
  parity suite) and the web front end in `packages/climpact-web` (`climpact_web`). The
  core must never import `climpact_web`. `uv sync` installs both, editable, with the dev
  tools of the root `pyproject.toml`'s `dev` group.
- Add or change a dependency in the member's `pyproject.toml` (dev tools in its
  `[dependency-groups]` and in the root's), then run `uv lock` and commit `uv.lock`; CI
  fails when `uv.lock` is stale (`uv lock --check`).
- `uv run pytest` from the root runs both packages' tests; `uv run pytest
  packages/climpact` runs the core alone (CI runs it without the web package installed:
  `uv sync --package climpact`).
- The tests run in parallel with pytest-xdist (`-n auto --dist loadgroup` in `addopts`,
  about 80 s locally instead of 8 minutes). Add `-n 0` to run them in one process, for
  debugging (`--pdb` does so by itself). Tests that share a cached session- or
  module-scoped build must stay in one `xdist_group` (added at collection in the
  `conftest.py` files; TECHNICAL.md, "Running the tests in parallel"). Keep `pytest<9.2`
  until a pytest-xdist release fixes `--dist loadgroup` for pytest 9.2 (pytest-xdist#1386).
- The browser accessibility checks (`packages/climpact-web/tests/test_accessibility.py`,
  marker `browser`, about 2.5 minutes, needs Chrome) are deselected by default
  (`-m "not browser"` in `addopts`); CI's `web-accessibility` job runs them. Run them
  locally with `uv run pytest -m browser` before a pull request that touches templates,
  CSS or JavaScript. Naming the file without `-m browser` collects nothing.
- The web stylesheet is built with the pinned standalone Tailwind CLI: after changing a
  template's classes or `packages/climpact-web/src/climpact_web/core/tailwind/`, run
  `scripts/build-css.sh` (get the CLI once with `scripts/fetch-tailwind.sh`; never install
  Tailwind any other way) and commit `css/climpact.css`; CI fails when it is stale.
- Changes go through pull requests; do not commit to `main`. **Only the user merges pull
  requests.** Never run `gh pr merge`, even when CI is green: take the PR to green CI and
  In review, then say it is ready. The user merges with a **merge commit**, never squash or
  rebase, so the branch's commits are kept on `main` as they were written. Every commit on the branch
  therefore lands on `main`: keep each one signed, with a meaningful message, and tidy up
  "fix typo"-style commits before the PR is merged.
- Before opening or updating a pull request, run `ruff check`, `ruff format --check` and
  `pytest`, and report the R parity summary.
- **A pull request that changes how the web app looks shows it.** Add one or two
  screenshots of the new design to the PR body, under "Screenshots". Pick the screens
  that best show the change, not every page; include a before/after pair when that makes
  the change clearer. Take them from the running app with `tests/browser.py`'s `Chrome`
  (`media(prefers_color_scheme=...)`, `viewport`, `screenshot`), at 1280 px wide unless
  the change is about phones. Publish them with `scripts/pr-screenshots.sh <pr-number>
  <image>...`, which puts them on the orphan `pr-screenshots` branch (never merged, so the
  images stay out of `main`) and prints the Markdown to paste into the body. Don't commit
  screenshots to the pull request's branch.
- **Run the full suite once, and get the parity summary from the file, not by running it
  again.** The summary is about 60 lines, too long for a `tail` of the output, so the test
  run also writes it, with the test totals, to `.parity-summary.txt` at the repository root
  (git-ignored). Run `uv run pytest -q 2>&1 | tee "$TMPDIR/pytest.log" | tail -n 15`, then
  `cat .parity-summary.txt`; if the tail doesn't show every failure, read them from the log
  (`grep -E "^(FAILED|ERROR)" "$TMPDIR/pytest.log"`) instead of re-running. Check that the
  file's header (timestamp and command) is from this run: a run that doesn't collect the
  parity tests leaves an older file in place. For a "before" summary, copy the file aside
  (for example `cp .parity-summary.txt "$TMPDIR/parity-before.txt"`) before changing the
  code.

## Tickets

All work is tracked as GitHub issues on the **[climpactpy Kanban](https://github.com/users/geoffwalmsley/projects/2)**. **Always use the `ticket` skill** to add a ticket, pick what to work on, and move cards through the workflow. The columns are Backlog → Ready → In progress → In review → Done.

- Don't start work that has no issue. File one first, unless the user asks for something quick and one-off.
- Name branches `<issue>-<slug>`. PRs say `Closes #N`, so the issue closes and the card moves to Done on merge.
- Every ticket has a **Parity coverage** section naming the R reference files it should make pass, and the PR reports the parity summary before and after.

## Keep TECHNICAL.md up to date

`TECHNICAL.md` must describe the code as it is on the branch. Update it **in the same pull
request** as the change whenever you:

- port an index or output, or change how one is calculated (update the Status table and
  parity counts, the "Use of xclim" table, and the relevant sections);
- find or introduce any difference between the Python and R results or behaviour,
  including R behaviour deliberately not copied (add an entry under "Differences between
  Python and R, and how they are handled");
- add, move or rename modules, change the data model, `IndexParams`, output table layouts,
  the missing-data rules or the tolerance tiers;
- change the R reference setup, reference runs, supported Python versions or the
  development workflow.

Use the `update-technical-docs` skill to do this. If a change needs no documentation
update, say so explicitly in the pull request description.

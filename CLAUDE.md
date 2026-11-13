# climpactpy

Python port of Climpact (R). See `README.md` for setup and `TECHNICAL.md` for the
architecture, parity testing and the differences between the Python and R implementations.

## Working rules

- Run all Python through the project virtualenv: `.venv/bin/python`, `.venv/bin/pytest`,
  `.venv/bin/ruff`. Never install packages globally.
- The repository holds two packages: the core in `packages/climpact` (`src/climpact`, its
  tests and the R parity suite) and the web front end in `packages/climpact-web`
  (`climpact_web`). The core must never import `climpact_web`. One venv has both,
  installed editable: `python3 -m venv .venv && .venv/bin/python -m pip install -e
  "packages/climpact[dev]" -e "packages/climpact-web[dev]"`.
- `.venv/bin/pytest` from the root runs both packages' tests; `.venv/bin/pytest
  packages/climpact` runs the core alone (as CI does, without the web package installed).
- Changes go through pull requests; do not commit to `main`.
- Before opening or updating a pull request, run `ruff check`, `ruff format --check` and
  `pytest`, and report the R parity summary printed at the end of the test run.

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

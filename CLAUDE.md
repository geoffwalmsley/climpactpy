# climpactpy

Python port of Climpact (R). See `README.md` for setup and `TECHNICAL.md` for the
architecture, parity testing and the differences between the Python and R implementations.

## Working rules

- Run all Python through the project virtualenv: `.venv/bin/python`, `.venv/bin/pytest`,
  `.venv/bin/ruff`. Never install packages globally.
- Changes go through pull requests; do not commit to `main`.
- Before opening or updating a pull request, run `ruff check`, `ruff format --check` and
  `pytest`, and report the R parity summary printed at the end of the test run.

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

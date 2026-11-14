---
name: update-technical-docs
description: Update TECHNICAL.md so it matches the code on the current branch. Use after porting an index or output, changing a calculation, finding a Python/R difference, changing modules, data model, parameters, tolerance tiers or the R reference setup, and before opening or updating a pull request in climpactpy.
---

# Update TECHNICAL.md

`TECHNICAL.md` is the technical record of the Python port, and in particular the record of
every difference between the Python and R implementations. Keep it accurate to the code on
the current branch. Every statement must be checked against the code or a test run, never
written from memory.

## 1. Find what changed

```sh
git fetch -q
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- packages reference ruff.toml pytest.ini .github
```

List the changes that affect documented behaviour. Ignore pure refactors that change no
names, behaviour or results.

## 2. Get the current parity numbers

```sh
uv run pytest -q 2>&1 | tail -6
```

Record the `R parity` summary lines (`lat0: N/117 ...`, `sydney: N/117 ...`) and the test
totals. Do not copy numbers from an earlier run.

## 3. Update each affected section

| Change | Sections to update |
| --- | --- |
| Index or output ported | Status (counts and both columns of the table), "Use of xclim" table, Parity testing example output, Performance if run time changed noticeably |
| Calculation changed | The index's entry under "Differences between Python and R", "Use of xclim" if xclim is now used or no longer used |
| New Python/R difference found or resolved | "Differences between Python and R" (see entry format below) |
| R behaviour deliberately not copied | "R behaviour not to be copied", plus the output it affects |
| Module added, moved or renamed | Repository layout, Data flow |
| Data model, `IndexParams`, `CustomIndex`, table layouts | Station data model, Index parameters, Output products |
| Missing-data rules | Missing data |
| Tolerance tiers or catalogue rules | Tolerance tiers |
| R reference setup or reference runs | Reference outputs (and `reference/README.md`) |
| Python versions, dependencies, CI, workflow | Development |
| Something listed as "not yet ported" or "not yet handled" is now done | Remove or rewrite that statement wherever it appears |

### Entry format for differences

Each difference states, in this order:

1. **The R behaviour**, with the R function or file it comes from
   (e.g. climdex.pcic `spell.length.max`, Climpact `climpact.etsci-functions.r`).
2. **What Python does** and where (module and function).
3. **The effect on results**: identical, within which tier, or how outputs differ. Include
   numbers when you have them (e.g. "3 of 1,920 monthly dates").

Put it under the matching subheading (Numerical precision, Index definitions, Station
input, Output files). Add a subheading only if none fits.

## 4. Check the document

- Every module, function, class, parameter and file named in `TECHNICAL.md` exists:
  ```sh
  grep -oE '`[A-Za-z_][A-Za-z0-9_./]*(\(\))?`' TECHNICAL.md | sort -u
  ```
  and look up each name that refers to code with `grep -rn` in `packages/` and `reference/`.
- Status table, parity counts and "not yet ported" lists agree with each other and with
  the test run from step 2.
- No statement describes behaviour that the code no longer has.
- Keep the existing style: short sentences, tables for comparisons, no marketing language.

## 5. Report

In the pull request description, add a short "Documentation" note listing the sections of
`TECHNICAL.md` that changed, or state that no documentation update was needed and why.

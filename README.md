# climpactpy

A Python port of [Climpact](https://github.com/ARCCSS-extremes/climpact), the R software for calculating indices of daily climate extremes.

## Repository layout

The repository holds two Python packages:

- `packages/climpact`: the core package (distribution `climpactpy`, imported as
  `climpact`), with its tests and the R parity suite. It has no web dependencies:
  `pip install ./packages/climpact` installs only the core.
- `packages/climpact-web`: the web front end (`climpact_web`, Django + htmx), which
  depends on the core. Only the skeleton so far: the screens are being built (epic #11).

`reference/` (the R reference outputs) is shared at the root.

## Development

Requires Python 3.11+. Work inside one virtual environment with both packages installed
in editable mode:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e "packages/climpact[dev]" -e "packages/climpact-web[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest                      # both packages' tests, including R parity
.venv/bin/pytest packages/climpact    # the core only
```

To calculate the indices for a station and write them as Climpact CSV files:

```sh
.venv/bin/climpact run station.txt --out outputs --lat -33.86 --lon 151.21
```

To process many stations listed in a Climpact R batch metadata file (one process per CPU;
a station that fails is reported in `outputs/<station>.errors.txt`):

```sh
.venv/bin/climpact batch metadata.txt station_files/ --out outputs
```

To start the web app on this computer (it opens in the browser and works offline):

```sh
.venv/bin/climpact-web               # --no-browser, --port, --host, --data-dir
```

QC, homogeneity and index calculation are separate modules, and other packages can add
their own as plugins. `climpact modules` lists the modules installed; `--qc`,
`--homogeneity` and `--indices` select them (see "Modules and plugins" in TECHNICAL.md).

The R reference outputs used for parity testing are in `reference/` (see `reference/README.md`).

See [TECHNICAL.md](TECHNICAL.md) for the architecture, parity testing and the differences between the Python and R implementations.

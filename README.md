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

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). The repository is a uv
workspace: `uv sync` makes one virtual environment (`.venv`) with both packages installed
in editable mode and the development tools, at the versions in `uv.lock`:

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest                      # both packages' tests, including R parity
uv run pytest packages/climpact    # the core only
```

Without uv, `pip install -e packages/climpact -e packages/climpact-web` and
`pip install --group packages/climpact/pyproject.toml:dev --group
packages/climpact-web/pyproject.toml:dev` (pip 25.1+) also work, but are not locked.

To calculate the indices for a station and write them as Climpact CSV files:

```sh
uv run climpact run station.txt --out outputs --lat -33.86 --lon 151.21
```

To process many stations listed in a Climpact R batch metadata file (one process per CPU;
a station that fails is reported in `outputs/<station>.errors.txt`):

```sh
uv run climpact batch metadata.txt station_files/ --out outputs
```

To start the web app on this computer (it opens in the browser and works offline):

```sh
uv run climpact-web               # --no-browser, --port, --host, --data-dir
```

QC, homogeneity and index calculation are separate modules, and other packages can add
their own as plugins. `climpact modules` lists the modules installed; `--qc`,
`--homogeneity` and `--indices` select them (see "Modules and plugins" in TECHNICAL.md).

The R reference outputs used for parity testing are in `reference/` (see `reference/README.md`).

See [TECHNICAL.md](TECHNICAL.md) for the architecture, parity testing and the differences between the Python and R implementations.

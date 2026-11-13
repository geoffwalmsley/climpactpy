# climpactpy

A Python port of [Climpact](https://github.com/ARCCSS-extremes/climpact), the R software for calculating indices of daily climate extremes.

## Development

Requires Python 3.11+. Work inside a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
```

To calculate the indices for a station and write them as Climpact CSV files:

```sh
.venv/bin/climpact run station.txt --out outputs --lat -33.86 --lon 151.21
```

The R reference outputs used for parity testing are in `reference/` (see `reference/README.md`).

See [TECHNICAL.md](TECHNICAL.md) for the architecture, parity testing and the differences between the Python and R implementations.

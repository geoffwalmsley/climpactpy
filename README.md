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

The R reference outputs used for parity testing are in `reference/` (see `reference/README.md`).

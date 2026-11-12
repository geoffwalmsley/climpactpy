"""Registry of builders for Climpact-format output tables.

Each Climpact output file (for example ``indices/fd_ANN``) is produced by a builder
that takes a station run and returns a :class:`pandas.DataFrame` with the same
columns as the R output. Some output names depend on the run's parameters (for
example ``r30mm`` or ``rx3day``), so builders are *products*: functions returning a
mapping of output key to table. The parity tests compare every produced table
against the R reference outputs; files no product produces are reported as not yet
ported.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

Product = Callable[[Any], Mapping[str, pd.DataFrame]]

PRODUCTS: list[Product] = []


def product(func: Product) -> Product:
    """Register a function returning ``{output key: table}`` for a run."""
    PRODUCTS.append(func)
    return func


def register(*keys: str) -> Callable[[Callable[[Any], pd.DataFrame]], Callable]:
    """Register a builder producing the same table for each of the fixed ``keys``."""

    def decorator(func: Callable[[Any], pd.DataFrame]) -> Callable[[Any], pd.DataFrame]:
        def single(run: Any) -> dict[str, pd.DataFrame]:
            table = func(run)
            return {key: table for key in keys}

        single.__name__ = func.__name__
        PRODUCTS.append(single)
        return func

    return decorator


def load_builtin_builders() -> list[Product]:
    """Import the built-in products so they register themselves."""
    import climpact.products  # noqa: F401

    return PRODUCTS


def build_all(run: Any) -> dict[str, pd.DataFrame]:
    """Build every registered output table for a run."""
    load_builtin_builders()
    tables: dict[str, pd.DataFrame] = {}
    for make in PRODUCTS:
        for key, table in make(run).items():
            if key in tables:
                raise ValueError(f"output {key!r} produced twice")
            tables[key] = table
    return tables


def build(key: str, run: Any) -> pd.DataFrame:
    """Build the output table for ``key``."""
    tables = build_all(run)
    try:
        return tables[key]
    except KeyError:
        raise NotImplementedError(f"no builder produces {key!r}") from None

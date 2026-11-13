"""Registry of builders for Climpact-format index tables, and the built-in index module.

Each Climpact output file (for example ``indices/fd_ANN``) is produced by a builder
that takes a station run and returns a :class:`pandas.DataFrame` with the same
columns as the R output. Some output names depend on the run's parameters (for
example ``r30mm`` or ``rx3day``), so builders are *products*: functions returning a
mapping of output key to table. The parity tests compare every produced table
against the R reference outputs; files no product produces are reported as not yet
ported.

The registered products make up the built-in index module, :data:`CLIMPACT_INDICES`
(see :mod:`climpact.modules`). The QC files are built by the built-in QC module,
:data:`climpact.products.qc.CLIMPACT_QC`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

Product = Callable[[Any], Mapping[str, pd.DataFrame]]
# A product built from the other products' tables (the trend file).
DerivedProduct = Callable[[Any, Mapping[str, pd.DataFrame]], Mapping[str, pd.DataFrame]]

PRODUCTS: list[Product] = []
DERIVED: list[DerivedProduct] = []


def product(func: Product) -> Product:
    """Register a function returning ``{output key: table}`` for a run."""
    PRODUCTS.append(func)
    return func


def derived(func: DerivedProduct) -> DerivedProduct:
    """Register a function of ``(run, tables)`` run after every other product, where
    ``tables`` holds all the tables those products built."""
    DERIVED.append(func)
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


class ClimpactIndices:
    """The built-in index module: every registered product, then the derived ones."""

    name = "climpact"

    def build(self, run: Any, tables: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        load_builtin_builders()
        out: dict[str, pd.DataFrame] = {}
        for make in PRODUCTS:
            _add(out, make(run))
        for make in DERIVED:
            _add(out, make(run, {**tables, **out}))
        return out


def _add(tables: dict[str, pd.DataFrame], new: Mapping[str, pd.DataFrame]) -> None:
    for key, table in new.items():
        if key in tables:
            raise ValueError(f"output {key!r} produced twice")
        tables[key] = table


CLIMPACT_INDICES = ClimpactIndices()


def build_all(run: Any, modules: Any = None) -> dict[str, pd.DataFrame]:
    """Build every output table for a run: QC, homogeneity and index modules.

    ``modules`` is a :class:`climpact.modules.ModuleSelection` (default: the built-in
    modules, which write R's files).
    """
    from climpact.modules import run_pipeline

    return run_pipeline(run, modules).tables


def build(key: str, run: Any) -> pd.DataFrame:
    """Build the output table for ``key``."""
    tables = build_all(run)
    try:
        return tables[key]
    except KeyError:
        raise NotImplementedError(f"no builder produces {key!r}") from None

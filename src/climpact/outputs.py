"""Registry of builders for Climpact-format output tables.

Each Climpact output file (for example ``indices/fd_ANN``) is produced by a builder
function that takes a station run and returns a :class:`pandas.DataFrame` with the
same columns as the R output. The parity tests compare every registered builder
against the R reference outputs; files without a builder are reported as not yet
ported.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

Builder = Callable[[Any], pd.DataFrame]

BUILDERS: dict[str, Builder] = {}


def register(*keys: str) -> Callable[[Builder], Builder]:
    """Register a builder for one or more output keys such as ``"indices/fd_ANN"``."""

    def decorator(func: Builder) -> Builder:
        for key in keys:
            if key in BUILDERS:
                raise ValueError(f"builder for {key!r} already registered")
            BUILDERS[key] = func
        return func

    return decorator


def load_builtin_builders() -> dict[str, Builder]:
    """Import the built-in builders so they register themselves; returns the registry."""
    import climpact.products  # noqa: F401

    return BUILDERS


def build(key: str, run: Any) -> pd.DataFrame:
    """Build the output table for ``key``."""
    load_builtin_builders()
    try:
        builder = BUILDERS[key]
    except KeyError:
        raise NotImplementedError(f"no builder registered for {key!r}") from None
    return builder(run)

"""Shared pytest hooks for the core tests: running them in parallel with pytest-xdist.

The tests run in worker processes (``-n auto --dist loadgroup`` in the pytest settings,
TECHNICAL.md, "Running the tests in parallel"). Tests that share an expensive module- or
session-scoped fixture are put in one ``xdist_group``, so the fixture is built in one worker
instead of in every worker; the parity tests are grouped by reference run in
``parity/conftest.py``. ``-n 0`` runs everything in one process, for debugging.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from .parity.summary import write_parity_summary

# One thread each for the maths libraries and dask in each worker: the workers already use
# every core, and a thread pool per worker would oversubscribe them. Tests that choose
# their own number of threads or processes are not affected, and a value already set in
# the environment is kept.
SINGLE_THREAD = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "DASK_NUM_WORKERS",
)

# Test modules whose tests share module-scoped fixtures, run in one worker each.
MODULE_GROUPS = {"test_drought.py", "test_ehf.py"}
HERE = Path(__file__).parent


def pytest_configure(config):
    # Set in the main process before it starts the workers, which inherit its environment
    # (and so have it before they import numpy).
    if config.getoption("dist", "no") != "no" and config.getoption("tx", None):
        for name in SINGLE_THREAD:
            os.environ.setdefault(name, "1")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if item.path.name in MODULE_GROUPS and item.path.parent == HERE:
            item.add_marker(pytest.mark.xdist_group(f"core-{item.path.stem}"))


def pytest_terminal_summary(terminalreporter, config):
    """The R parity summary (``parity/summary.py``), in the main process only: under
    pytest-xdist a worker sees only its own tests, and must not overwrite the file."""
    if not hasattr(config, "workerinput"):
        write_parity_summary(terminalreporter)

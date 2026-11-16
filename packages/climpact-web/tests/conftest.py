"""Shared pytest hooks for the climpact-web tests.

The tests run in parallel with pytest-xdist (``-n auto --dist loadgroup`` in the pytest
settings; ``-n 0`` runs them in one process): see packages/climpact/tests/conftest.py,
whose thread limits are repeated here for running these tests alone.
"""

import os
from pathlib import Path

import pytest

# One thread each for the maths libraries and dask in each worker (as in the core's
# conftest.py): the workers already use every core.
SINGLE_THREAD = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "DASK_NUM_WORKERS",
)

# Test modules whose tests share module-scoped fixtures (collected static files; the
# browser and the running app), run in one worker each.
MODULE_GROUPS = {"test_page_budget.py", "test_accessibility.py"}
HERE = Path(__file__).parent

# The user property test_page_budget.py records each page's sizes in (its SIZES_PROPERTY).
SIZES_PROPERTY = "page_sizes"


def pytest_configure(config):
    # Set in the main process before it starts the workers, which inherit its environment.
    if config.getoption("dist", "no") != "no" and config.getoption("tx", None):
        for name in SINGLE_THREAD:
            os.environ.setdefault(name, "1")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if item.path.name in MODULE_GROUPS and item.path.parent == HERE:
            item.add_marker(pytest.mark.xdist_group(f"web-{item.path.stem}"))


def pytest_terminal_summary(terminalreporter):
    """The page sizes measured by test_page_budget.py (#82), largest first.

    They come from the test reports, which reach the main process under pytest-xdist too.
    """
    measured, budgets = {}, None
    for outcome in ("passed", "failed"):
        for report in terminalreporter.stats.get(outcome, []):
            for name, value in getattr(report, "user_properties", ()):
                if name == SIZES_PROPERTY:
                    measured[value["page"]] = value
                    budgets = value["budgets"]
    if not measured:
        return
    kb = 1024
    write = terminalreporter.write_line
    terminalreporter.write_sep("-", "page sizes (#82): HTML and everything it links")
    write(f"{'page':34} {'HTML':>8} {'HTML gz':>8} {'total':>8} {'gzip':>8} {'brotli':>8}  KB")
    for name, s in sorted(measured.items(), key=lambda item: -item[1]["gz"]):
        write(
            f"{name:34} {s['html_raw'] / kb:8.1f} {s['html_gz'] / kb:8.1f} {s['raw'] / kb:8.1f}"
            f" {s['gz'] / kb:8.1f} {s['br'] / kb:8.1f}"
        )
    write(
        f"budgets: landing {budgets['landing'] // kb} KB gzip, other pages "
        f"{budgets['page'] // kb} KB gzip, HTML {budgets['html_raw'] // kb} KB raw"
    )

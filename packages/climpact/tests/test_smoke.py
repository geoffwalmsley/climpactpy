"""Smoke tests for the project skeleton."""

from pathlib import Path

import climpact

REFERENCE_DIR = Path(__file__).parents[3] / "reference" / "output"
STATION = "sydney_observatory_hill_1936-2015"


def test_package_has_version():
    assert climpact.__version__


def test_xclim_imports():
    import xclim

    assert xclim.__version__.startswith("1.0")


def test_r_reference_outputs_present():
    """The committed R reference CSVs that the parity tests will compare against."""
    for run in ("lat0", "sydney"):
        indices = REFERENCE_DIR / run / STATION / "indices"
        assert len(list(indices.glob("*.csv"))) == 114, run

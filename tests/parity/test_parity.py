"""Parity tests: every R reference output against the Python port.

Files that no registered product builds are reported as xfail ("not yet ported").
Once a product builds a file its comparison must pass; ``strict`` xfail is not used
so that the summary shows progress without failing CI for unported files.
"""

from __future__ import annotations

import pytest

from climpact.compare import compare_tables
from climpact.io.climpact_csv import read_climpact_csv

from .catalogue import reference_files

FILES = reference_files()


@pytest.mark.parity
@pytest.mark.parametrize("ref", FILES, ids=[f.id for f in FILES])
def test_parity(ref, station_outputs):
    outputs = station_outputs(ref.run)
    if ref.key not in outputs:
        pytest.xfail("not yet ported")

    expected = read_climpact_csv(ref.path).data
    result = compare_tables(expected, outputs[ref.key], ref.tier, ref.column_tiers)
    assert result.ok, f"{ref.id} does not match the R reference:\n{result.summary()}"

"""Parity tests: every R reference output against the Python port.

Files with no registered builder are reported as xfail ("not yet ported"). Once a
builder is registered its comparison must pass; ``strict`` xfail is not used so that
the summary shows progress without failing CI for unported files.
"""

from __future__ import annotations

import pytest

from climpact import outputs
from climpact.compare import compare_tables
from climpact.io.climpact_csv import read_climpact_csv

from .catalogue import reference_files

FILES = reference_files()


@pytest.mark.parity
@pytest.mark.parametrize("ref", FILES, ids=[f.id for f in FILES])
def test_parity(ref, request):
    if ref.key not in outputs.BUILDERS:
        pytest.xfail("not yet ported")

    station_run = request.getfixturevalue("station_run")(ref.run)
    expected = read_climpact_csv(ref.path).data
    actual = outputs.build(ref.key, station_run)

    result = compare_tables(expected, actual, ref.tier, ref.column_tiers)
    assert result.ok, f"{ref.id} does not match the R reference:\n{result.summary()}"

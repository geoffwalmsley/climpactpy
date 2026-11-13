"""Written CSV files are text-identical to the R reference files.

For every reference file the Python port builds, the file written by
:func:`climpact.io.output_files.write_outputs` must match R's line for line, apart from
the ``Date_of_calculation`` line.
"""

from __future__ import annotations

import pytest

from climpact.io.output_files import write_outputs

from .catalogue import RUNS, reference_files

FILES = reference_files()
DATE_LINE = '"Date_of_calculation: "'


@pytest.fixture(scope="session")
def written_files(station_run, station_outputs, tmp_path_factory):
    """Factory returning ``{key: path}`` of the files written for a reference run."""
    cache = {}

    def get(run: str):
        if run not in cache:
            station = station_run(run)
            out = tmp_path_factory.mktemp(f"csv_{run}")
            cache[run] = write_outputs(station_outputs(run), station.metadata, station.params, out)
        return cache[run]

    return get


def lines_without_date(path) -> list[str]:
    return [line for line in path.read_text().splitlines() if not line.startswith(DATE_LINE)]


@pytest.mark.parity
@pytest.mark.parametrize("ref", FILES, ids=[f.id for f in FILES])
def test_csv_text(ref, station_outputs, written_files, request):
    if ref.known_bug:
        request.applymarker(pytest.mark.xfail(reason=ref.known_bug, strict=True))
    if ref.key not in station_outputs(ref.run):
        pytest.xfail("not yet ported")
    written = written_files(ref.run)
    assert ref.key in written, f"{ref.id}: built but not written"

    expected = lines_without_date(ref.path)
    actual = lines_without_date(written[ref.key])
    mismatches = [
        (number, e, a)
        for number, (e, a) in enumerate(zip(expected, actual, strict=False), start=1)
        if e != a
    ]
    assert len(expected) == len(actual) and not mismatches, (
        f"{ref.id}: {len(mismatches)} lines differ ({len(expected)} lines in R, "
        f"{len(actual)} written); first: {mismatches[:3]}"
    )


@pytest.mark.parity
@pytest.mark.parametrize("run", RUNS)
def test_only_reference_files_written(run, written_files):
    """Every written file has an R reference (no extra or misnamed files)."""
    keys = {f.key for f in FILES if f.run == run}
    assert set(written_files(run)) <= keys

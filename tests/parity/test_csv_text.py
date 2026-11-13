"""Written CSV files are text-identical to the R reference files.

For every reference file the Python port builds, the file written by
:func:`climpact.io.output_files.write_outputs` must match R's line for line, apart from
the ``Date_of_calculation`` line.

The SPI and SPEI files are the one exception, and only on platforms other than glibc on
x86_64, where the R reference was made: their values go through the C library's
``exp``, ``log``, ``pow`` and trigonometric functions, which differ from glibc in the
last bit for some inputs on other platforms (see ``tests/libm.py``). There a line of
these files may differ from R's only in numeric fields that agree within ``LIBM_RTOL``
relative (plus ``LIBM_ATOL``); missing values (``-99.9``) and every other field must
still be identical.
The same applies to the SPI and SPEI rows of the trend file (``spi3,FEB,...``,
``spei12,DEC,...``), whose slopes and bounds are computed from those values; every other
row of the trend file must be identical on every platform.
On glibc x86_64 (CI) they must be text-identical like every other file.
"""

from __future__ import annotations

import re

import pytest

from climpact.io.output_files import write_outputs

from ..libm import GLIBC_X86_64, LIBM_ATOL, LIBM_RTOL
from .catalogue import RUNS, reference_files

FILES = reference_files()
DATE_LINE = '"Date_of_calculation: "'
# Files whose last digit depends on the platform's C maths library (see the module docstring).
LIBM_SENSITIVE = re.compile(r"^indices/\d+month_(spi|spei)_MON$")
# Files where only some lines depend on it: key -> pattern on the line.
LIBM_SENSITIVE_LINES = {"trend/trend": re.compile(r"^(spi|spei)\d+,")}
# Field separator of files not written with ", ".
SEPARATORS = {"trend/trend": ","}


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


def same_within_libm_tolerance(expected: str, actual: str, sep: str = ", ") -> bool:
    """Lines equal apart from numeric fields within the libm tolerance (never ``-99.9``
    or ``NA``)."""
    e_fields, a_fields = expected.split(sep), actual.split(sep)
    if len(e_fields) != len(a_fields):
        return False
    for e, a in zip(e_fields, a_fields, strict=True):
        if e == a:
            continue
        try:
            x, y = float(e), float(a)
        except ValueError:
            return False
        if "-99.9" in (e, a) or abs(x - y) > LIBM_RTOL * abs(x) + LIBM_ATOL:
            return False
    return True


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
    sep = SEPARATORS.get(ref.key, ", ")

    def relaxed(line: str) -> bool:
        if GLIBC_X86_64:
            return False
        if LIBM_SENSITIVE.match(ref.key):
            return True
        pattern = LIBM_SENSITIVE_LINES.get(ref.key)
        return bool(pattern and pattern.match(line))

    mismatches = [
        (number, e, a)
        for number, (e, a) in enumerate(zip(expected, actual, strict=False), start=1)
        if e != a and not (relaxed(e) and same_within_libm_tolerance(e, a, sep))
    ]
    assert len(expected) == len(actual) and not mismatches, (
        f"{ref.id}: {len(mismatches)} lines differ ({len(expected)} lines in R, "
        f"{len(actual)} written); first: {mismatches[:3]}"
    )


@pytest.mark.parity
@pytest.mark.parametrize("run", RUNS)
def test_only_reference_files_written(run, written_files):
    """Every written file has an R reference (no extra or misnamed files).

    Only the ``qc/`` files of a QC-only (synthetic) run are compared."""
    keys = {f.key for f in FILES if f.run == run}
    written = set(written_files(run))
    if RUNS[run].qc_only:
        written = {key for key in written if key.startswith("qc/")}
    assert written <= keys

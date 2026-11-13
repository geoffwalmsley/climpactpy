"""Batch output equals single-station output for reference stations.

Runs a small batch through the process pool, with two reference stations and one malformed
file, and checks that every file written for each station is identical to the file
``write_outputs`` writes for the single run of that station (which ``test_csv_text``
checks against R), and that the malformed file fails without stopping the batch.
"""

from __future__ import annotations

import datetime as dt

import pytest

from climpact.batch import read_batch_metadata, run_batch
from climpact.config import IndexParams
from climpact.io.output_files import write_outputs

from .catalogue import RUNS

BATCH_RUNS = ("sydney", "nairobi")
DATE = dt.date(2026, 1, 1)
HEADER = "station_file latitude longitude wsdin csdin Tb_HDD Tb_CDD Tb_GDD rxnday rnnmm txtn SPEI"


@pytest.mark.parity
def test_batch_equals_single_runs(tmp_path, station_run, station_outputs):
    data = tmp_path / "data"
    data.mkdir()
    p = IndexParams()
    params = (
        f"{p.wsdi_days} {p.csdi_days} {p.hdd_base} {p.cdd_base} {p.gdd_base} "
        f"{p.rx_days} {p.rnnmm} {p.txtn_days} {p.spei_months}"
    )
    rows = [HEADER]
    for name in BATCH_RUNS:
        run = RUNS[name]
        (data / run.input_path.name).symlink_to(run.input_path)
        rows.append(f"{run.input_path.name} {run.latitude} {run.longitude} {params}")
    (data / "malformed.txt").write_text("1990 1 1 0.0 25.0\n1990 1 2 0.0 25.1 15.2\n")
    rows.append(f"malformed.txt -10 100 {params}")
    metadata = tmp_path / "metadata.txt"
    metadata.write_text("\n".join(rows) + "\n")

    out = tmp_path / "batch"
    results = run_batch(
        read_batch_metadata(metadata), data, out, custom=p.custom, workers=2, date=DATE
    )

    *stations, malformed = results
    assert not malformed.ok
    assert "data row 1 has 5 fields" in (out / "malformed.errors.txt").read_text()
    assert not (out / "malformed").exists()

    for name, result in zip(BATCH_RUNS, stations, strict=True):
        assert result.ok, result.error
        station = station_run(name)
        assert station.params == p
        single = write_outputs(
            station_outputs(name), station.metadata, station.params, tmp_path / "single", DATE
        )
        batch_files = sorted((out / station.metadata.name).rglob("*.csv"))
        assert [f.relative_to(out) for f in batch_files] == sorted(
            f.relative_to(tmp_path / "single") for f in single.values()
        )
        assert result.written == len(single)
        for path in single.values():
            batch_path = out / path.relative_to(tmp_path / "single")
            assert batch_path.read_text() == path.read_text(), f"{name}: {batch_path.name} differs"

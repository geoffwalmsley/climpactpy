from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from climpact.batch import (
    COLUMNS,
    BatchMetadataError,
    BatchStation,
    read_batch_metadata,
    run_batch,
    strip_file_extension,
    validate_params,
)
from climpact.cli import main
from climpact.config import CustomIndex, IndexParams
from climpact.io.climpact_csv import read_climpact_csv

SAMPLE_METADATA = Path(__file__).parent / "data" / "climpact.sample.batch.metadata.txt"
HEADER = "\t".join(COLUMNS) + "\n"


def write_station(path: Path, seed: int = 0) -> Path:
    """Two years of synthetic data."""
    dates = pd.date_range("2000-01-01", "2001-12-31")
    rng = np.random.default_rng(seed)
    n = len(dates)
    tx = rng.normal(22, 4, n)
    tn = tx - rng.uniform(5, 10, n)
    rows = [
        f"{d.year} {d.month} {d.day} {p:.1f} {x:.1f} {m:.1f}"
        for d, p, x, m in zip(dates, rng.gamma(0.5, 4, n), tx, tn, strict=True)
    ]
    path.write_text("\n".join(rows) + "\n")
    return path


def test_reads_r_sample_metadata_unchanged():
    stations = read_batch_metadata(SAMPLE_METADATA)
    assert [s.station_file for s in stations] == [
        "sydney_observatory_hill_1936-2015.txt",
        "sydney_observatory_hill_batch_file_2.txt",
    ]
    first = stations[0]
    assert first.name == "sydney_observatory_hill_1936-2015"
    assert (first.latitude, first.longitude) == (-10, 100)
    assert first.params == IndexParams(
        wsdi_days=3,
        csdi_days=3,
        rx_days=3,
        txtn_days=2,
        hdd_base=18,
        cdd_base=18,
        gdd_base=10,
        rnnmm=30,
        spei_months=24,
        custom=None,
    )


def test_metadata_whitespace_and_comments(tmp_path):
    path = tmp_path / "meta.txt"
    path.write_text(
        "station_file latitude longitude wsdin csdin Tb_HDD Tb_CDD Tb_GDD rxnday rnnmm txtn SPEI\n"
        "\n"
        "# a comment\n"
        "a.b.txt  -33.86 151.21 2 4 17.5 19 11 5 25.4 3.0 12  # trailing comment\n"
    )
    [station] = read_batch_metadata(path)
    assert station.name == "a.b"
    assert station.params.rnnmm == 25.4
    assert station.params.txtn_days == 3
    assert isinstance(station.params.txtn_days, int)
    assert station.params.hdd_base == 17.5


@pytest.mark.parametrize(
    "row, message",
    [
        ("a.txt -10 100 3 3 18 18 10 3 30 2", "11 fields"),
        ("a.txt north 100 3 3 18 18 10 3 30 2 24", "latitude must be a number"),
        ("a.txt -10 100 3.5 3 18 18 10 3 30 2 24", "wsdin must be a whole number"),
    ],
)
def test_bad_metadata_rows(tmp_path, row, message):
    path = tmp_path / "meta.txt"
    path.write_text(HEADER + row + "\n")
    with pytest.raises(BatchMetadataError, match=message):
        read_batch_metadata(path)


def test_two_files_with_the_same_station_name(tmp_path):
    path = tmp_path / "meta.txt"
    row = "\t-10\t100\t3\t3\t18\t18\t10\t3\t30\t2\t24\n"
    path.write_text(HEADER + "a.txt" + row + "a.csv" + row)
    with pytest.raises(BatchMetadataError, match="lines 2 and 3"):
        read_batch_metadata(path)


def test_strip_file_extension():
    assert strip_file_extension("sydney_1936-2015.txt") == "sydney_1936-2015"
    assert strip_file_extension("a.b.txt") == "a.b"
    assert strip_file_extension("noext") == "noext"


def test_validate_params():
    validate_params(IndexParams())
    with pytest.raises(ValueError, match="WSDId"):
        validate_params(IndexParams(wsdi_days=11))
    with pytest.raises(ValueError, match="SPEI"):
        validate_params(IndexParams(spei_months=0))


def _station(file: str, **params) -> BatchStation:
    return BatchStation(file, -10.0, 100.0, IndexParams(custom=None, **params), line=2)


def test_failures_do_not_stop_the_batch(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    write_station(data / "good.txt")
    (data / "broken.txt").write_text("2000 1 1 0.0 20.0\n")
    out = tmp_path / "out"
    out.mkdir()
    (out / "good.errors.txt").write_text("stale error from an earlier run\n")

    seen = []
    results = run_batch(
        [
            _station("broken.txt"),
            _station("good.txt", rnnmm=25),
            _station("absent.txt"),
            _station("badparams.txt", wsdi_days=0),
        ],
        data,
        out,
        workers=1,
        on_result=lambda r: seen.append(r.name),
    )
    assert [r.name for r in results] == ["broken", "good", "absent", "badparams"]
    assert seen == ["broken", "good", "absent", "badparams"]

    broken, good, absent, badparams = results
    assert good.ok and good.written > 0
    assert (out / "good" / "indices" / "good_r25mm_ANN.csv").is_file()
    assert not (out / "good" / "indices" / "good_TNgt0_ANN.csv").exists()  # no custom index
    assert not (out / "good.errors.txt").exists()

    assert "has 5 fields, expected 6" in broken.error
    assert broken.error_file == out / "broken.errors.txt"
    assert "has 5 fields" in broken.error_file.read_text()
    assert not (out / "broken").exists()
    assert "station file not found" in absent.error_file.read_text()
    assert "WSDId" in badparams.error_file.read_text()


def test_custom_index_for_every_station(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    write_station(data / "s.txt")
    [result] = run_batch(
        [_station("s.txt")], data, tmp_path / "out", custom=CustomIndex("TX", ">=", 30), workers=1
    )
    assert result.ok
    table = read_climpact_csv(tmp_path / "out" / "s" / "indices" / "s_TXge30_ANN.csv")
    assert table.metadata["Description"] == "TX >= 30"


def test_batch_command(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    write_station(data / "one.txt", seed=1)
    (data / "two.txt").write_text("not a station file\n")
    meta = tmp_path / "meta.txt"
    row = "\t33\t-112\t2\t2\t18\t18\t10\t3\t30\t2\t24\n"
    meta.write_text(HEADER + "one.txt" + row + "two.txt" + row)
    out = tmp_path / "out"

    status = main(["batch", str(meta), str(data), "--out", str(out), "--workers", "1"])
    assert status == 1
    txx = read_climpact_csv(out / "one" / "indices" / "one_txx_ANN.csv")
    assert txx.metadata["Latitude"] == "33"
    assert txx.metadata["Base_period"] == "1971-2000"
    assert (out / "two.errors.txt").is_file()

    output = capsys.readouterr().out
    assert "Processing 2 stations" in output
    assert "one: wrote" in output
    assert "two: FAILED" in output
    assert "1 of 2 stations processed, 1 failed" in output


@pytest.mark.parametrize(
    "args",
    [
        ["--workers", "0"],
        ["--custom", "XX", ">", "0"],
    ],
)
def test_batch_bad_arguments(tmp_path, args):
    meta = tmp_path / "meta.txt"
    meta.write_text(HEADER)
    with pytest.raises(SystemExit):
        main(["batch", str(meta), str(tmp_path), "--out", str(tmp_path / "out"), *args])


def test_batch_bad_metadata_is_a_usage_error(tmp_path):
    meta = tmp_path / "meta.txt"
    meta.write_text(HEADER + "a.txt 1 2\n")
    with pytest.raises(SystemExit):
        main(["batch", str(meta), str(tmp_path), "--out", str(tmp_path / "out")])


def test_run_station_qc_only_with_thresholds(tmp_path):
    """No index modules: only the QC files, written with the given thresholds (#77)."""
    from climpact.batch import run_station
    from climpact.config import QCParams, StationMetadata
    from climpact.modules import ModuleSelection

    station = write_station(tmp_path / "s.txt")
    meta = StationMetadata("s", -30.0, 150.0, 2000, 2001)
    stages = []
    written, skipped = run_station(station, meta, IndexParams(), tmp_path / "out",
                                   modules=ModuleSelection(indices=()), zip=True,
                                   progress=lambda *a: stages.append(a[0]),
                                   qc=QCParams(jump=5.0, temp_max=30.0))  # fmt: skip
    assert {k.split("/")[0] for k in written} == {"qc", "zip"} and not skipped
    assert stages == ["read", "qc:climpact", "homogeneity:none", "write", "zip"]
    jumps = written["qc/tx_jumps"].read_text()
    assert "change in TX is > 5 degrees" in jumps
    assert "abs(temperature) > 30 degrees" in written["qc/toolarge"].read_text()
    default, _ = run_station(station, meta, IndexParams(), tmp_path / "default",
                             modules=ModuleSelection(indices=()))  # fmt: skip
    assert "> 20 degrees" in default["qc/tx_jumps"].read_text()

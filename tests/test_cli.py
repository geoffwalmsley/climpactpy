import numpy as np
import pandas as pd
import pytest

from climpact.cli import main
from climpact.io.climpact_csv import read_climpact_csv


@pytest.fixture
def station_file(tmp_path):
    """Two years of synthetic data with TN missing throughout."""
    dates = pd.date_range("2000-01-01", "2001-12-31")
    rng = np.random.default_rng(0)
    rows = [
        f"{d.year} {d.month} {d.day} {p:.1f} {t:.1f} -99.9"
        for d, p, t in zip(
            dates, rng.gamma(0.5, 4, len(dates)), rng.normal(22, 4, len(dates)), strict=True
        )
    ]
    path = tmp_path / "mystation.txt"
    path.write_text("\n".join(rows) + "\n")
    return path


def test_run_writes_climpact_files(station_file, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["run", str(station_file), "--out", str(out), "--lat", "-10", "--rnnmm", "25"]) == 0

    folder = out / "mystation"
    txx = read_climpact_csv(folder / "indices" / "mystation_txx_ANN.csv")
    assert txx.metadata["Station"] == "mystation"
    assert txx.metadata["Latitude"] == "-10"
    assert (folder / "indices" / "mystation_r25mm_MON.csv").is_file()
    assert (folder / "qc" / "mystation_nastatistics.csv").is_file()
    # TN is missing everywhere, so R writes no TN index files.
    assert not (folder / "indices" / "mystation_fd_ANN.csv").exists()
    assert not (folder / "indices" / "mystation_TNgt0_ANN.csv").exists()

    output = capsys.readouterr().out
    assert f"files to {folder}" in output
    assert "indices/fd_ANN" in output


def test_custom_index_options(station_file, tmp_path):
    out = tmp_path / "out"
    main(["run", str(station_file), "--out", str(out), "--name", "s", "--custom", "TX", ">=", "30"])
    table = read_climpact_csv(out / "s" / "indices" / "s_TXge30_ANN.csv")
    assert table.metadata["Description"] == "TX >= 30"


@pytest.mark.parametrize(
    "args",
    [
        ["--custom", "XX", ">", "0"],
        ["--custom", "TX", "!=", "0"],
        ["--custom", "TX", ">", "abc"],
        ["--custom", "TX", ">", "0", "--no-custom"],
    ],
)
def test_bad_arguments(station_file, tmp_path, args):
    with pytest.raises(SystemExit):
        main(["run", str(station_file), "--out", str(tmp_path), *args])


def test_missing_station_file(tmp_path):
    with pytest.raises(SystemExit):
        main(["run", str(tmp_path / "nope.txt"), "--out", str(tmp_path)])

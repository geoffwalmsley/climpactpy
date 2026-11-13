"""The module interfaces, plugin discovery and the QC -> homogeneity -> indices pipeline."""

import shutil
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from climpact import modules
from climpact.batch import BatchStation, run_batch
from climpact.cli import main
from climpact.config import IndexParams, StationMetadata
from climpact.io.climpact_csv import read_climpact_csv
from climpact.io.output_files import FileFormat, with_file_format
from climpact.modules import (
    HomogeneityModule,
    HomogeneityResult,
    IndexModule,
    ModuleSelection,
    QCModule,
    UnknownModuleError,
    resolve,
    run_pipeline,
)
from climpact.outputs import build_all
from climpact.station import load_station

PLUGIN = Path(__file__).parent / "plugins" / "climpact_example_plugin"
WITH_PLUGINS = ModuleSelection(
    qc=("climpact", "example_qc"),
    homogeneity="example_shift",
    indices=("climpact", "example_indices"),
)


def install(project: Path, site: Path) -> None:
    """Install a pure-Python project into ``site`` as pip would: its package plus a
    ``.dist-info`` folder holding its metadata and entry points (no build step)."""
    meta = tomllib.loads((project / "pyproject.toml").read_text())["project"]
    package = meta["name"].replace("-", "_")
    shutil.copytree(project / package, site / package)
    info = site / f"{package}-{meta['version']}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {meta['name']}\nVersion: {meta['version']}\n"
    )
    lines = []
    for group, points in meta["entry-points"].items():
        lines.append(f"[{group}]")
        lines += [f"{name} = {value}" for name, value in points.items()]
    (info / "entry_points.txt").write_text("\n".join(lines) + "\n")


@pytest.fixture
def example_plugin(tmp_path, monkeypatch):
    """The example plugin package, installed into a folder on ``sys.path``."""
    site = tmp_path / "site-packages"
    site.mkdir()
    install(PLUGIN, site)
    monkeypatch.syspath_prepend(str(site))
    yield site


@pytest.fixture
def station_file(tmp_path):
    """Four years of synthetic data, 2000-2003."""
    dates = pd.date_range("2000-01-01", "2003-12-31")
    rng = np.random.default_rng(1)
    n = len(dates)
    tx = rng.normal(28, 5, n)
    tn = tx - rng.uniform(5, 10, n)
    rows = [
        f"{d.year} {d.month} {d.day} {p:.1f} {x:.1f} {m:.1f}"
        for d, p, x, m in zip(dates, rng.gamma(0.5, 4, n), tx, tn, strict=True)
    ]
    path = tmp_path / "plugstation.txt"
    path.write_text("\n".join(rows) + "\n")
    return path


@pytest.fixture
def run(station_file):
    return load_station(station_file, StationMetadata("plugstation", latitude=-20))


def test_builtin_modules_without_plugins():
    assert modules.available("qc") == {"climpact": "built-in"}
    assert modules.available("homogeneity") == {"none": "built-in"}
    assert modules.available("indices") == {"climpact": "built-in"}
    with pytest.raises(UnknownModuleError, match="example_qc.*available: climpact"):
        resolve(WITH_PLUGINS)


def test_builtin_modules_implement_the_interfaces():
    loaded = resolve()
    assert all(isinstance(m, QCModule) for m in loaded.qc)
    assert isinstance(loaded.homogeneity, HomogeneityModule)
    assert all(isinstance(m, IndexModule) for m in loaded.indices)


def test_default_pipeline_is_build_all(run):
    result = run_pipeline(run)
    assert not result.adjusted
    assert result.indices_run is run
    tables = result.tables
    assert set(tables) == set(build_all(run))
    assert {"qc/outliers", "qc/nastatistics", "indices/txx_ANN", "trend/trend"} <= set(tables)


def test_plugin_is_discovered(example_plugin):
    assert modules.available("qc")["example_qc"] == "climpact_example_plugin:HotDaysQC"
    assert "example_shift" in modules.available("homogeneity")
    assert "example_indices" in modules.available("indices")
    loaded = resolve(WITH_PLUGINS)
    # Classes are instantiated; objects are used as they are.
    assert loaded.qc[1].name == "example_qc"
    assert loaded.homogeneity.name == "example_shift"
    assert isinstance(loaded.indices[1], IndexModule)


def test_plugins_run_in_the_pipeline(example_plugin, run):
    original_tx = run.data["tasmax"].copy()
    builtin = run_pipeline(run).tables
    result = run_pipeline(run, WITH_PLUGINS)
    tables = result.tables

    # Every built-in output is still there, plus one table from each plugin.
    plugin_keys = {
        "qc/example_hot_days",
        "homogeneity/example_breaks",
        "indices/example_txmean_ANN",
    }
    assert set(tables) == set(builtin) | plugin_keys
    assert tables["homogeneity/example_breaks"]["Date"].tolist() == ["2002-01-01"]

    # QC saw the original data, the indices the adjusted data.
    assert result.adjusted
    assert result.input_run is run
    np.testing.assert_array_equal(run.data["tasmax"], original_tx)
    for key in builtin:
        if key.startswith("qc/"):
            pd.testing.assert_frame_equal(tables[key], builtin[key])
    shifted = tables["indices/txx_ANN"]["val"].to_numpy() - builtin["indices/txx_ANN"]["val"]
    np.testing.assert_allclose(shifted, [1, 1, 0, 0])
    plugin_mean = tables["indices/example_txmean_ANN"]["example_txmean"].to_numpy()
    tx_mean = original_tx.groupby("time.year").mean().to_numpy()
    np.testing.assert_allclose(plugin_mean, np.round(tx_mean + [1, 1, 0, 0], 3))


def test_cli_lists_and_runs_plugins(example_plugin, station_file, tmp_path, capsys):
    assert main(["modules"]) == 0
    listing = capsys.readouterr().out
    assert "example_qc (climpact_example_plugin:HotDaysQC)" in listing
    assert "none (built-in)" in listing

    out = tmp_path / "out"
    args = ["run", str(station_file), "--out", str(out), "--lat", "-20"]
    args += ["--qc", "climpact,example_qc", "--homogeneity", "example_shift"]
    args += ["--indices", "climpact,example_indices"]
    assert main(args) == 0
    folder = out / "plugstation"
    breaks = read_climpact_csv(folder / "homogeneity" / "plugstation_example_breaks.csv")
    assert breaks.metadata["Description"] == "Breaks found and the adjustment applied before them"
    assert breaks.data["Date"].tolist() == ["2002-01-01"]
    txmean = read_climpact_csv(folder / "indices" / "plugstation_example_txmean_ANN.csv")
    assert txmean.data.columns.tolist() == ["time", "example_txmean"]
    assert (folder / "qc" / "plugstation_example_hot_days.csv").is_file()
    assert (folder / "qc" / "plugstation_outliers.csv").is_file()


def test_cli_rejects_unknown_module(station_file, tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["run", str(station_file), "--out", str(tmp_path), "--homogeneity", "nope"])
    assert "no homogeneity module named 'nope'" in capsys.readouterr().err


def test_batch_workers_load_plugins(example_plugin, station_file, tmp_path):
    """Spawned worker processes find the plugin too."""
    stations = [
        BatchStation(station_file.name, -20, 0, IndexParams(custom=None), 2),
        BatchStation("missing.txt", -20, 0, IndexParams(custom=None), 3),
    ]
    out = tmp_path / "out"
    results = run_batch(stations, station_file.parent, out, workers=2, modules=WITH_PLUGINS)
    assert results[0].ok, results[0].error
    assert not results[1].ok
    assert (out / "plugstation" / "homogeneity" / "plugstation_example_breaks.csv").is_file()


class _Module:
    """A module returning fixed tables, for the error tests."""

    def __init__(self, name, tables=None, data=None):
        self.name = name
        self.tables = tables or {}
        self.data = data

    def build(self, run, tables):
        return self.tables

    def homogenise(self, run, tables):
        return HomogeneityResult(self.tables, self.data)


def _formatted(table):
    return with_file_format(table, FileFormat("test"))


def _modules(qc=(), homogeneity=None, indices=()):
    return modules.Modules(
        qc=tuple(qc), homogeneity=homogeneity or modules.PASS_THROUGH, indices=tuple(indices)
    )


def test_plugin_tables_need_a_file_format(run):
    bad = _Module("bad", {"qc/bad": pd.DataFrame({"a": [1]})})
    with pytest.raises(ValueError, match="'qc/bad' has no FileFormat"):
        run_pipeline(run, _modules(qc=[bad]))


def test_output_keys_are_checked(run):
    twice = _Module("twice", {"qc/nastatistics": _formatted(pd.DataFrame({"a": [1]}))})
    with pytest.raises(ValueError, match="'qc/nastatistics' produced twice"):
        run_pipeline(run, _modules(qc=[modules.load("qc", "climpact"), twice]))
    flat = _Module("flat", {"breaks": _formatted(pd.DataFrame({"a": [1]}))})
    with pytest.raises(ValueError, match="not folder/name"):
        run_pipeline(run, _modules(homogeneity=flat))


def test_adjusted_data_keeps_the_time_axis(run):
    shorter = _Module("shorter", data=run.data.isel(time=slice(1, None)))
    with pytest.raises(ValueError, match="changed the time axis"):
        run_pipeline(run, _modules(homogeneity=shorter))
    dropped = _Module("dropped", data=run.data.drop_vars("pr"))
    with pytest.raises(ValueError, match="dropped pr"):
        run_pipeline(run, _modules(homogeneity=dropped))


def test_adjusted_run_keeps_station_attributes(run):
    warmer = run.data.copy()
    warmer["tasmax"] = warmer["tasmax"] + 2
    warmer.attrs = {}  # the station attributes are restored from the input
    result = run_pipeline(run, _modules(homogeneity=_Module("warmer", data=warmer)))
    adjusted = result.indices_run
    assert adjusted is not run
    assert adjusted.data.attrs == run.data.attrs
    assert adjusted.metadata == run.metadata

"""Progress callbacks of run_pipeline, run_station, run_batch and the gridded thresholds."""

from pathlib import Path

import pandas as pd
import pytest

from climpact import modules
from climpact.batch import BatchStation, run_batch, run_station
from climpact.cli import main
from climpact.config import IndexParams, StationMetadata
from climpact.gridded import open_grid, write_grid_thresholds
from climpact.io.output_files import FileFormat, with_file_format
from climpact.modules import pipeline_stages, run_pipeline
from climpact.outputs import DERIVED, PRODUCTS, load_builtin_builders
from climpact.station import load_station
from tests.test_batch import write_station
from tests.test_gridded import write_grid

PARAMS = IndexParams(custom=None)


def _builtin_stages() -> list[str]:
    load_builtin_builders()
    products = [f"indices:climpact:{make.__name__}" for make in (*PRODUCTS, *DERIVED)]
    return ["qc:climpact", "homogeneity:none", *products]


def _check_steps(events: list[tuple[str, int, int]], stages: list[str]) -> None:
    """Every stage once, in order, numbered 1..total, with the right total."""
    assert [e[0] for e in events] == stages
    assert [e[1] for e in events] == list(range(1, len(stages) + 1))
    assert {e[2] for e in events} == {len(stages)}


def _files(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


@pytest.fixture
def station_file(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return write_station(data / "stn.txt")


def test_pipeline_stages_of_the_builtin_modules():
    stages = pipeline_stages()
    assert stages == _builtin_stages()
    assert "indices:climpact:temperature_percentiles" in stages
    assert stages[-1] == "indices:climpact:trend_file"


def test_run_station_reports_every_stage_and_writes_the_same_files(station_file, tmp_path):
    metadata = StationMetadata("stn", latitude=-10)
    events = []
    with_progress, skipped = run_station(
        station_file,
        metadata,
        PARAMS,
        tmp_path / "a",
        progress=lambda *e: events.append(e),
    )
    _check_steps(events, ["read", *_builtin_stages(), "write"])

    without, skipped_without = run_station(station_file, metadata, PARAMS, tmp_path / "b")
    assert skipped == skipped_without
    assert _files(tmp_path / "a") == _files(tmp_path / "b")


class _Plain:
    """A module without progress steps: reported as one stage."""

    def __init__(self, name, key):
        self.name = name
        self.key = key

    def build(self, run, tables):
        return {self.key: with_file_format(pd.DataFrame({"a": [1]}), FileFormat("test"))}


class _Stepped(_Plain):
    """A module reporting its own steps."""

    def progress_steps(self):
        return ["first", "second"]

    def build(self, run, tables, progress=None):
        for step in self.progress_steps():
            if progress:
                progress(step)
        return super().build(run, tables)


def test_pipeline_reports_plugin_modules(station_file):
    run = load_station(station_file, StationMetadata("stn"), PARAMS)
    selected = modules.Modules(
        qc=(_Plain("plain", "qc/plain"),),
        homogeneity=modules.PASS_THROUGH,
        indices=(_Stepped("stepped", "indices/stepped"),),
    )
    stages = ["qc:plain", "homogeneity:none", "indices:stepped:first", "indices:stepped:second"]
    assert pipeline_stages(selected) == stages
    events = []
    result = run_pipeline(run, selected, lambda *e: events.append(e))
    _check_steps(events, stages)
    assert set(result.tables) == {"qc/plain", "indices/stepped"}
    # Without a callback the module is called without one.
    assert set(run_pipeline(run, selected).tables) == {"qc/plain", "indices/stepped"}


@pytest.mark.parametrize("workers", [1, 2])
def test_batch_reports_each_station_from_the_workers(station_file, tmp_path, workers):
    write_station(station_file.parent / "other.txt", seed=3)
    stations = [
        BatchStation("stn.txt", -10, 100, PARAMS, 2),
        BatchStation("other.txt", -10, 100, PARAMS, 3),
        BatchStation("absent.txt", -10, 100, PARAMS, 4),
    ]
    log = []
    results = run_batch(
        stations,
        station_file.parent,
        tmp_path / "out",
        workers=workers,
        on_result=lambda r: log.append(("result", r.name)),
        progress=lambda *e: log.append(e),
    )
    assert [r.ok for r in results] == [True, True, False]
    stages = ["read", *_builtin_stages(), "write"]
    for name in ("stn", "other"):
        events = [e[1:] for e in log if e[0] == name]
        _check_steps(events, stages)
        # A station's stages all come before its result.
        last_stage = max(i for i, e in enumerate(log) if e[0] == name)
        assert log.index(("result", name)) > last_stage
    assert not [e for e in log if e[0] == "absent"]  # fails before reading
    assert ("result", "absent") in log


def test_gridded_thresholds_report_each_block(tmp_path):
    path = write_grid(tmp_path / "g.nc", ny=3, nx=5)
    inp = open_grid([path], max_values=2 * 3 * 3653, rechunk=False)
    events = []
    write_grid_thresholds(inp, tmp_path / "t.nc", 1972, 1979, progress=lambda *e: events.append(e))
    blocks = len(list(inp.blocks()))
    assert blocks > 1
    _check_steps(events, ["thresholds"] * blocks)


def test_cli_progress_goes_to_stderr(station_file, tmp_path, capsys):
    assert main(["run", str(station_file), "--out", str(tmp_path / "a"), "--progress"]) == 0
    captured = capsys.readouterr()
    total = len(_builtin_stages()) + 2
    assert captured.err.splitlines()[0] == f"[1/{total}] read"
    assert captured.err.splitlines()[-1] == f"[{total}/{total}] write"
    assert "[" not in captured.out

    assert main(["run", str(station_file), "--out", str(tmp_path / "b")]) == 0
    assert capsys.readouterr().err == ""
    assert _files(tmp_path / "a") == _files(tmp_path / "b")

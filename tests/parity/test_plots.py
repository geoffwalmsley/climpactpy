"""The plot files have R's names, for every reference run R drew plots for.

R's plots are gitignored, but ``reference/run_r_reference.sh`` writes their names (without
the station prefix) to ``reference/output/<run>/plot-files.txt``. The plots themselves are
compared with R's by eye, not pixel by pixel (see TECHNICAL.md).
"""

from __future__ import annotations

import pytest

from climpact.plots import index_plots, write_plots

from .catalogue import REFERENCE_DIR, RUNS

PLOT_RUNS = sorted(r for r in RUNS if (REFERENCE_DIR / r / "plot-files.txt").is_file())


def _r_files(run: str) -> list[str]:
    return sorted((REFERENCE_DIR / run / "plot-files.txt").read_text().split())


def test_reference_runs_with_plots():
    assert {"sydney", "lat0"} <= set(PLOT_RUNS)


@pytest.mark.parity
@pytest.mark.parametrize("run", PLOT_RUNS)
def test_plot_names_match_r(run, station_run, station_outputs):
    tables = station_outputs(run)
    names = [p.name for _, group in index_plots(tables, station_run(run).params) for p in group]
    assert len(names) == len(set(names))
    assert sorted([f"{n}.png" for n in names] + ["all_plots.pdf"]) == _r_files(run)


@pytest.mark.parity
def test_written_plot_files_match_r(tmp_path, station_run, station_outputs):
    pytest.importorskip("matplotlib")
    run = station_run("sydney")
    written = write_plots(station_outputs("sydney"), run.metadata, run.params, tmp_path)
    folder = tmp_path / run.metadata.name / "plots"
    prefix = f"{run.metadata.name}_"
    files = sorted(p.name.removeprefix(prefix) for p in folder.iterdir())
    assert files == _r_files("sydney")
    assert set(written.values()) == set(folder.iterdir())

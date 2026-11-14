"""Progress reporting for long runs.

A progress callback is any callable ``progress(stage, step, total)``. It is called once
as each step of a run *finishes*: ``stage`` names the step just done, ``step`` counts the
steps done so far (1 to ``total``) and ``total`` is the number of steps of the run, known
before the first call. The last call of a run that succeeds has ``step == total``. A run
that fails stops calling it.

- :func:`climpact.modules.run_pipeline` reports each QC module (``qc:<name>``), the
  homogeneity module (``homogeneity:<name>``) and each index module
  (``indices:<name>``). A module with a ``progress_steps()`` method reports its own
  steps instead: the built-in index module reports each index product
  (``indices:climpact:<product>``), so a station run has about 20 steps.
- :func:`climpact.batch.run_station` adds ``read`` (loading the station file) before
  them and ``write`` (writing the CSV files) after them.
- :func:`climpact.batch.run_batch` takes a :data:`BatchProgress`,
  ``progress(station, stage, step, total)``: the steps of each station, as
  ``run_station`` reports them, with the station's name. With several worker processes
  the workers send them to the parent through a queue and the callback is called in the
  parent process, in the thread that called ``run_batch``.
- :func:`climpact.gridded.write_grid_thresholds` reports ``thresholds`` once per block
  of the grid, and :func:`climpact.gridded.write_grid_indices` ``indices``; both report
  ``rechunk`` once per time slab first when the input is rechunked
  (:meth:`climpact.gridded.GriddedInput.block_reader`).

The default everywhere is no callback, which costs nothing and changes no output.
Callbacks are only ever called in the process that passed them, so they need not be
picklable.
"""

from __future__ import annotations

from collections.abc import Callable

Progress = Callable[[str, int, int], None]
"""``progress(stage, step, total)``, called as each step of a run finishes."""

BatchProgress = Callable[[str, str, int, int], None]
"""``progress(station, stage, step, total)``, the steps of each station of a batch."""


class Steps:
    """Counts the steps of a run of known ``total`` and reports each to ``progress``.

    ``offset`` is the number of steps already done, so a run can be split into parts
    that each report into the same count.
    """

    __slots__ = ("progress", "step", "total")

    def __init__(self, progress: Progress | None, total: int, offset: int = 0) -> None:
        self.progress = progress
        self.total = total
        self.step = offset

    def done(self, stage: str) -> None:
        self.step += 1
        if self.progress is not None:
            self.progress(stage, self.step, self.total)


__all__ = ["BatchProgress", "Progress", "Steps"]

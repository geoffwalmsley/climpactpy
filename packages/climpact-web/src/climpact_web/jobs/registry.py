"""Job kinds and their runners.

A runner is a function ``runner(ctx: JobContext) -> dict``: it reads ``ctx.params`` and
the files in ``ctx.input_dir``, calls the core, writes into ``ctx.output_dir``, reports
progress with ``ctx.progress(stage, step, total)`` (the core's callback, see
:mod:`climpact.progress`) and returns a JSON-serialisable summary, stored as
``Job.result``. It raises :class:`JobError` (or a ``ValueError`` from the core) for a
problem the user can fix; the message is shown to them as it is. Any other exception is
reported as an unexpected failure, its traceback kept in the operator log only.

Register a runner with ``@register("kind")``. The built-in ones are in
:mod:`climpact_web.jobs.runners`; the screens that create jobs (#76-#90) add their own
kinds the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class JobError(Exception):
    """A failure the user can understand and fix; its message is shown to them."""


class JobCancelled(BaseException):  # noqa: N818  (control flow, not an error)
    """Raised from the progress callback when the user cancels the job.

    A ``BaseException``, like ``KeyboardInterrupt``, so the core's per-station
    ``except Exception`` in a batch does not catch it and carry on."""


class JobInterrupted(BaseException):  # noqa: N818
    """Raised from the progress callback when the worker is asked to stop; the job is
    queued again."""


@dataclass
class JobContext:
    """What a runner gets: the job's parameters, folders and progress callback."""

    job_id: str
    params: dict[str, Any]
    input_dir: Path
    output_dir: Path
    progress: Callable[[str, int, int], None] = field(default=lambda stage, step, total: None)
    log: Callable[[str], None] = field(default=lambda message: None)

    def input_file(self, name: str) -> Path:
        """A file uploaded with the job, by name; :class:`JobError` if it is missing."""
        path = (self.input_dir / name).resolve()
        if self.input_dir.resolve() not in path.parents or not path.is_file():
            raise JobError(f"The input file {name!r} is missing.")
        return path


Runner = Callable[[JobContext], dict]

RUNNERS: dict[str, Runner] = {}


def register(kind: str) -> Callable[[Runner], Runner]:
    def decorator(func: Runner) -> Runner:
        RUNNERS[kind] = func
        return func

    return decorator


def get_runner(kind: str) -> Runner:
    try:
        return RUNNERS[kind]
    except KeyError:
        raise JobError(f"Unknown kind of job: {kind!r}.") from None

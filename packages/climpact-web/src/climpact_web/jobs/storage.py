"""Where a job's files live.

Each job has its own folder, ``<RUNS_DIR>/<job id>/``, with ``input/`` (uploads) and
``output/`` (what the core writes). The core reads and writes ordinary files, so the
worker always works on a local folder.

Only the local filesystem is implemented, and it is all hosted mode needs: the deployment
(#12) is a single host where the web and worker containers mount the same Docker volume at
``CLIMPACT_WEB_MEDIA_ROOT``, so both see every job folder. A deployment without a shared
filesystem could subclass this to copy ``input/`` down from object storage before a run
and ``output/`` up after it, and to serve downloads from there; set
``CLIMPACT_WEB_JOB_STORAGE`` to the subclass's dotted path.
"""

from __future__ import annotations

import re
import shutil
from functools import cache
from pathlib import Path

from django.conf import settings
from django.utils.module_loading import import_string


class LocalJobStorage:
    """Job folders on the local filesystem, under ``RUNS_DIR``."""

    def create(self, job) -> None:
        """Make the job's empty ``input/`` folder."""
        job.input_dir.mkdir(parents=True, exist_ok=True)

    def save_input(self, job, name: str, uploaded, folder: str = "") -> Path:
        """Save an uploaded file (a Django ``UploadedFile``) as ``input/<name>``, or as
        ``input/<folder>/<name>`` when the caller names a folder (one plain word, chosen
        by the code, e.g. a batch's ``stations``)."""
        name = Path(name).name  # never a path from the browser
        if not name or name in {".", ".."}:
            raise ValueError("invalid file name")
        if folder and not re.fullmatch(r"[\w-]+", folder):
            raise ValueError("invalid folder name")
        self.create(job)
        target = job.input_dir / folder if folder else job.input_dir
        target.mkdir(parents=True, exist_ok=True)
        path = target / name
        with path.open("wb") as out:
            for chunk in uploaded.chunks():
                out.write(chunk)
        return path

    def prepare_output(self, job) -> Path:
        """An empty ``output/`` folder for a run (a retry starts afresh)."""
        shutil.rmtree(job.output_dir, ignore_errors=True)
        job.output_dir.mkdir(parents=True, exist_ok=True)
        return job.output_dir

    def output_file(self, job, relative: str) -> Path | None:
        """An output file by its path relative to ``output/``, or None if there is no such
        file (or the path leaves the folder)."""
        root = job.output_dir.resolve()
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            return None
        return path

    def delete(self, job) -> None:
        shutil.rmtree(job.folder, ignore_errors=True)


@cache
def _storage_class(path: str):
    return import_string(path)


def get_storage() -> LocalJobStorage:
    return _storage_class(settings.JOB_STORAGE)()

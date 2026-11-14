"""Batch processing of stations (#80): the data model.

A :class:`BatchRun` is one batch going through the batch page: the uploaded metadata file
and station files (in its own folder), the result of checking them
(:mod:`climpact_web.batch.check`), the options chosen before it starts and the
background job that runs it. Like a station analysis it belongs to the browser session
that created it (the job owner token), and is deleted ``JOB_RETENTION_DAYS`` after it was
last changed (:mod:`.retention`). The job copies the files it needs into its own
``input/`` folder when it is queued, so batches and jobs expire independently.
"""

from __future__ import annotations

import datetime as dt
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

METADATA_FILE = "metadata.txt"  # the metadata file's name on disk never comes from the browser
# Station files keep their own names (the metadata file refers to them), without folders
# and never hidden (check.plain_name).
FILES_DIR = "files"


def batches_dir() -> Path:
    """``<MEDIA_ROOT>/batches``: not under ``RUNS_DIR``, whose stray folders the jobs app
    deletes."""
    return Path(settings.MEDIA_ROOT) / "batches"


class Source(models.TextChoices):
    UPLOAD = "upload", _("Uploaded files")
    SAMPLE = "sample", _("Sample batch")


class BatchRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    source = models.CharField(max_length=10, choices=Source.choices, default=Source.UPLOAD)
    metadata_name = models.CharField(max_length=255, blank=True)  # as uploaded, display only
    report = models.JSONField(default=dict, blank=True)  # check.BatchCheck.to_json()

    # Options (the R batch screen's parameters, and the plots).
    base_start = models.IntegerField(default=1971)
    base_end = models.IntegerField(default=2000)
    workers = models.PositiveIntegerField(default=1)
    plots = models.BooleanField(default=True)

    job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.metadata_name or str(self.id)

    # Files --------------------------------------------------------------------------

    @property
    def folder(self) -> Path:
        return batches_dir() / str(self.id)

    @property
    def metadata_path(self) -> Path:
        return self.folder / METADATA_FILE

    @property
    def files_dir(self) -> Path:
        return self.folder / FILES_DIR

    def station_files(self) -> dict[str, bytes]:
        if not self.files_dir.is_dir():
            return {}
        return {p.name: p.read_bytes() for p in sorted(self.files_dir.iterdir()) if p.is_file()}

    def save_files(self, files: dict[str, bytes]) -> None:
        """Add station files (replacing any of the same name)."""
        self.files_dir.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (self.files_dir / name).write_bytes(data)

    def save_metadata(self, data: bytes) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.metadata_path.write_bytes(data)

    def delete_files(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)

    # State --------------------------------------------------------------------------

    @property
    def stations(self) -> list[dict]:
        return self.report.get("stations", [])

    def count(self, status: str) -> int:
        return sum(1 for s in self.stations if s["status"] == status)

    @property
    def ready_count(self) -> int:
        return self.count("ready")

    @property
    def folder_name(self) -> str:
        """The batch folder and zip name: the metadata file's name without its extension,
        as R's batch screen names them."""
        from climpact.batch import strip_file_extension
        from climpact_web.jobs.forms import safe_station_name

        return safe_station_name(strip_file_extension(self.metadata_name or "batch"))

    def touch(self) -> None:
        self.updated_at = timezone.now()

    @property
    def expires_at(self) -> dt.datetime:
        return self.updated_at + dt.timedelta(days=settings.JOB_RETENTION_DAYS)

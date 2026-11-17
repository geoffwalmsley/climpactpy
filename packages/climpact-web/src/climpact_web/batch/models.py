"""Batch processing of stations (#80): the data model.

A :class:`BatchRun` is one batch going through the batch page: the uploaded metadata file
and station files (in its own folder), the result of checking them
(:mod:`climpact_web.batch.check`), the run options chosen before it starts (``workers``
and ``plots``) and the background job that runs it. It fills a workspace
(:class:`climpact_web.stations.models.Workspace`, #231), made with it, and is deleted with
that workspace (:mod:`climpact_web.stations.retention`). The base period and the custom
index are the workspace's (#255). Once the job has finished, its stations become stations
of the workspace (:mod:`climpact_web.batch.fill`). The job copies the files it needs into
its own ``input/`` folder when it is queued; it is kept as long as the batch.
"""

from __future__ import annotations

import datetime as dt
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.urls import reverse
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
    workspace = models.ForeignKey(
        "stations.Workspace", on_delete=models.CASCADE, related_name="batches"
    )
    owner = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    source = models.CharField(max_length=10, choices=Source.choices, default=Source.UPLOAD)
    metadata_name = models.CharField(max_length=255, blank=True)  # as uploaded, display only
    report = models.JSONField(default=dict, blank=True)  # check.BatchCheck.to_json()

    # Run options (the R batch screen's parameters, and the plots). The base period is
    # the workspace's since #255.
    workers = models.PositiveIntegerField(default=1)
    plots = models.BooleanField(default=True)

    job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # The finished job whose stations are in the workspace (#255, batch.fill): set once
    # they have been added, so that they are added only once for each run.
    filled_job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.metadata_name or str(self.id)

    def url(self, name: str = "check") -> str:
        """The address of the batch's page ``batch:<name>``: ``/w/<workspace>/batch/…``
        (#256). A batch makes its own workspace, so the workspace names it."""
        return reverse(f"batch:{name}", args=[self.workspace_id])

    def save(self, *args, **kwargs) -> None:
        """Save, making the batch's workspace when it is new and recording the change on it.
        A batch's workspace starts with no custom index, as Climpact for R's batch
        calculates none (:func:`climpact_web.batch.fill.batch_index_settings`)."""
        from climpact_web.batch.fill import batch_index_settings
        from climpact_web.stations.models import Workspace

        if self.workspace_id is None:
            self.workspace = Workspace.objects.create(
                owner=self.owner,
                created_at=self.created_at,
                updated_at=self.updated_at,
                index_settings=batch_index_settings(),
            )
        super().save(*args, **kwargs)
        self.workspace.bring_forward(self.updated_at)

    def delete(self, *args, **kwargs):
        """Delete the batch, and its workspace if nothing else is left in it."""
        workspace = self.workspace
        result = super().delete(*args, **kwargs)
        workspace.delete_if_empty()
        return result

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
    def expires_at(self) -> dt.datetime | None:
        """When the batch's workspace, with the batch, is deleted (None: never, or not
        saved yet)."""
        return self.workspace.expires_at if self.workspace_id else None

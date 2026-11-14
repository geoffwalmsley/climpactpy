"""Gridded runs (#85): the data model.

A :class:`GriddedRun` is one set of netCDF files going through the gridded steps: the
files (paths on this computer in local mode, read in place; or uploaded copies in the
run's own folder), what inspecting them found, the variable names, the parameters, and
the background jobs that calculate the thresholds and the indices. Like a batch it
belongs to the browser session that created it, and is deleted ``JOB_RETENTION_DAYS``
after it was last changed (:mod:`.retention`); files read in place are never deleted.
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

UPLOADS_DIR = "input"  # uploaded input files, under their own (reduced) names
THRESHOLDS_DIR = "thresholds"  # an uploaded thresholds file


def gridded_dir() -> Path:
    """``<MEDIA_ROOT>/gridded``: not under ``RUNS_DIR``, whose stray folders the jobs app
    deletes."""
    return Path(settings.MEDIA_ROOT) / "gridded"


class Source(models.TextChoices):
    PATH = "path", _("Files on this computer")
    UPLOAD = "upload", _("Uploaded files")
    SAMPLE = "sample", _("Sample grid")


class GriddedRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    source = models.CharField(max_length=10, choices=Source.choices, default=Source.PATH)
    # inspect.FileInfo.to_json() of each input file, in the order chosen.
    files = models.JSONField(default=list, blank=True)
    # The netCDF variable of each of tasmax, tasmin and pr.
    names = models.JSONField(default=dict, blank=True)
    # The parameters (forms.SetupForm's cleaned data, JSON-safe); empty until set.
    options = models.JSONField(default=dict, blank=True)

    thresholds_job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    indices_job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        names = [f["name"] for f in self.files]
        return ", ".join(names) if names else str(self.id)

    # Files --------------------------------------------------------------------------

    @property
    def folder(self) -> Path:
        return gridded_dir() / str(self.id)

    @property
    def uploads_dir(self) -> Path:
        return self.folder / UPLOADS_DIR

    @property
    def thresholds_dir(self) -> Path:
        return self.folder / THRESHOLDS_DIR

    @property
    def paths(self) -> list[str]:
        return [f["path"] for f in self.files]

    def file_infos(self):
        from climpact_web.gridded.inspection import FileInfo

        return [FileInfo.from_json(f) for f in self.files]

    def delete_files(self) -> None:
        """Delete the run's own folder (uploads); files read in place are left alone."""
        shutil.rmtree(self.folder, ignore_errors=True)

    # State --------------------------------------------------------------------------

    @property
    def jobs(self) -> list:
        return [j for j in (self.thresholds_job, self.indices_job) if j is not None]

    @property
    def job_active(self) -> bool:
        return any(not j.is_finished for j in self.jobs)

    def touch(self) -> None:
        self.updated_at = timezone.now()

    @property
    def expires_at(self) -> dt.datetime:
        return self.updated_at + dt.timedelta(days=settings.JOB_RETENTION_DAYS)

"""Gridded runs (#85): the data model.

A :class:`GriddedRun` is one set of netCDF files and what was made from them, a place of
its own like a workspace (#289): its name, the files (paths on this computer in local
mode, read in place; or uploaded copies in the run's own folder), what inspecting them
found, the variable names, the parameters, and the background jobs that calculate the
thresholds and the indices. Like a batch it belongs to the browser session that created
it, and is deleted ``JOB_RETENTION_DAYS`` after it was last changed (:mod:`.retention`);
files read in place are never deleted.
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

    # The name the user gave it (Rename, #289); blank: named from its files (runs.default_name).
    name = models.CharField(max_length=200, blank=True)
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
    # Starting a finished run again (#293): the new jobs and the settings they were
    # started with wait here, so the results shown stay until the new ones are ready
    # (:meth:`settle` then puts them in place of the old).
    next_thresholds_job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    next_indices_job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # {"names": ..., "options": ...} of the next jobs; empty when none wait.
    next_settings = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.display_name

    @property
    def display_name(self) -> str:
        """The run's title (#289): the name given, else one made from its files."""
        if self.name:
            return self.name
        from climpact_web.gridded.runs import default_name

        return default_name(self)

    def get_absolute_url(self) -> str:
        from django.urls import reverse

        return reverse("gridded:run", args=[self.pk])

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
    def next_jobs(self) -> list:
        """The jobs of a new start that replace the results shown when they finish."""
        return [j for j in (self.next_thresholds_job, self.next_indices_job) if j is not None]

    @property
    def job_active(self) -> bool:
        return any(not j.is_finished for j in self.jobs + self.next_jobs)

    @property
    def restarting(self) -> bool:
        """A new start is calculating while the old results are shown."""
        return any(not j.is_finished for j in self.next_jobs)

    def settle(self) -> bool:
        """Once every job of a new start has succeeded, put it and its settings in place
        of the old jobs, whose files are deleted. A new start that failed or was cancelled
        stays where it is, so the results shown are kept and the set-up can say what
        happened. Returns whether the run changed."""
        from climpact_web.jobs.models import Status
        from climpact_web.jobs.storage import get_storage

        pending = self.next_jobs
        if not pending or any(j.status != Status.SUCCEEDED for j in pending):
            return False
        old = [j for j in self.jobs if j.pk not in {p.pk for p in pending}]
        settings_ = self.next_settings or {}
        kept = {k: self.options[k] for k in ("checksums",) if k in self.options}
        self.options = {**settings_.get("options", {}), **kept}
        self.names = settings_.get("names", self.names)
        self.thresholds_job, self.indices_job = self.next_thresholds_job, self.next_indices_job
        self.next_thresholds_job = self.next_indices_job = None
        self.next_settings = {}
        self.save()
        storage = get_storage()
        for job in old:
            storage.delete(job)
            job.delete()
        return True

    def touch(self) -> None:
        self.updated_at = timezone.now()

    @property
    def expires_at(self) -> dt.datetime:
        return self.updated_at + dt.timedelta(days=settings.JOB_RETENTION_DAYS)

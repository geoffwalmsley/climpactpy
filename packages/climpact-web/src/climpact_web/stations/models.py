"""The single-station workspace's data model (#76, #179).

A :class:`StationAnalysis` is one station's workspace: Data (#76), Quality (#77), Results
(#78, #79) and Files (#176), with the index settings (#178) and the optional sector
comparison (#90) as actions on Results. It holds the uploaded file (in its own folder)
and its hash, the station metadata, the quality-control thresholds, a summary of the
data, the furthest step reached and links to the background jobs of each section. Like a
job it belongs to the browser session that created it (the same owner token as
:class:`climpact_web.jobs.models.Job`), and is deleted ``JOB_RETENTION_DAYS`` after it was
last changed (:mod:`.retention`).

A change to the file, the metadata or the thresholds keeps the jobs: each job records the
inputs it was produced from (``Job.inputs``), and :mod:`.workspace` compares them with the
analysis's to show the results as out of date until their replacement has finished.

The analysis keeps its own copy of the file: a job copies the file into its own
``input/`` folder when it is queued, so jobs and analyses expire independently.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

STATION_FILE = "station.txt"  # the name on disk never comes from the browser


def stations_dir() -> Path:
    """Where analyses keep their files: ``<MEDIA_ROOT>/stations``. Not under ``RUNS_DIR``,
    whose folders the jobs app purges when they belong to no job."""
    return Path(settings.MEDIA_ROOT) / "stations"


class Source(models.TextChoices):
    UPLOAD = "upload", _("Uploaded file")
    SAMPLE = "sample", _("Sample data")
    BATCH = "batch", _("From a batch")


class Step(models.TextChoices):
    """The furthest point reached: ``upload`` (a file is loaded), ``qc`` (the station
    details are confirmed, so the checks run), ``indices`` (the user chose to use the
    data, "See results" on Quality, so Results show), then ``results`` and ``sector``
    (Results and the sector comparison were opened). It only ever moves forward since
    #179: a later change makes the results out of date instead of going back."""

    UPLOAD = "upload", _("Load data")
    QC = "qc", _("Check quality")
    INDICES = "indices", _("Calculate indices")
    RESULTS = "results", _("Results and downloads")
    SECTOR = "sector", _("Compare with sector data")


STEP_ORDER = [s.value for s in Step]


def file_digest(text: str) -> str:
    """The SHA-256 of a station file's text, as kept on disk: the ``file`` input."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class StationAnalysis(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    source = models.CharField(max_length=10, choices=Source.choices, default=Source.UPLOAD)
    file_name = models.CharField(max_length=255, blank=True)  # as uploaded, for display only
    summary = models.JSONField(default=dict, blank=True)  # station_file.summarise()
    file_hash = models.CharField(max_length=64, blank=True)  # file_digest() of the file
    warnings = models.JSONField(default=list, blank=True)  # about the file, shown in step 1

    # Station metadata (climpact.config.StationMetadata); null until given.
    station_name = models.CharField(max_length=100, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    base_start = models.IntegerField(default=1971)
    base_end = models.IntegerField(default=2000)

    step = models.CharField(max_length=10, choices=Step.choices, default=Step.UPLOAD)

    # The quality-control thresholds of step 2 (#77): climpact.config.QCParams fields as
    # entered; empty until changed (R's defaults, stations.forms.QC_DEFAULTS).
    qc_params = models.JSONField(default=dict, blank=True)

    # A station opened from a batch's results (#80): {"batch": batch id, "job": the batch
    # job's id, "station": its name, "params": the IndexParams fields of its metadata
    # line, "outputs": its folder in the batch job's output/, "inputs": the inputs the
    # batch's results were produced from (#179)}. Empty otherwise. Results show the
    # batch's results until the station is calculated here, starting from these settings.
    origin = models.JSONField(default=dict, blank=True)

    # The jobs of the sections. A change to an input keeps them (#179): their results show
    # as out of date until a job of the new inputs replaces them (workspace.py).
    qc_job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    indices_job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sector_job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.station_name or self.file_name or str(self.id)

    # Files --------------------------------------------------------------------------

    @property
    def folder(self) -> Path:
        return stations_dir() / str(self.id)

    @property
    def station_file(self) -> Path:
        return self.folder / STATION_FILE

    def save_station_text(self, text: str) -> None:
        """Write the station file and set :attr:`file_hash` (the caller saves)."""
        self.folder.mkdir(parents=True, exist_ok=True)
        self.station_file.write_text(text, encoding="utf-8")
        self.file_hash = file_digest(text)

    def delete_files(self) -> None:
        import shutil

        shutil.rmtree(self.folder, ignore_errors=True)

    # State --------------------------------------------------------------------------

    @property
    def metadata_complete(self) -> bool:
        return bool(self.station_name) and None not in (self.latitude, self.longitude)

    @property
    def metadata(self) -> dict:
        """The station metadata as the ``station`` job runner takes it."""
        return {
            "name": self.station_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "base_start": self.base_start,
            "base_end": self.base_end,
        }

    def reached(self, step: str) -> bool:
        return STEP_ORDER.index(self.step) >= STEP_ORDER.index(step)

    def advance_to(self, step: str) -> None:
        if not self.reached(step):
            self.step = step

    def cancel_speculative(self) -> None:
        """Cancel the indices job if it is a speculative run not finished yet (#178)."""
        job = self.indices_job
        if job is not None and job.is_speculative and job.can_cancel:
            job.request_cancel()

    def touch(self) -> None:
        self.updated_at = timezone.now()

    @property
    def expires_at(self) -> dt.datetime:
        return self.updated_at + dt.timedelta(days=settings.JOB_RETENTION_DAYS)

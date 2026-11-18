"""Workspaces and their stations: the data model (#76, #179, #231).

A :class:`Workspace` holds stations and the settings they share (#230, decision 5): the
base period, the quality-control thresholds and the index settings. One station is a
workspace of one; a batch (:class:`climpact_web.batch.models.BatchRun`) fills one with
many. Like a job it belongs to the browser session that created it (the same owner token
as :class:`climpact_web.jobs.models.Job`). When ``WORKSPACE_EXPIRY`` is on (hosted) it is
deleted, with its stations, batch and files, ``JOB_RETENTION_DAYS`` after the last change
to it or to any of them (:mod:`.retention`); locally it stays until the user deletes it.

A :class:`Station` is one station of a workspace: Quality (#77), Indices (#78, #236) and
Files (#176), with the index settings (#178) and the optional sector comparison (#90). It
holds the uploaded file (in its own folder) and its hash, the station metadata, a summary
of the data, the furthest step reached and links to the background jobs of each section.
Its ``slug`` names it in its workspace. The base period, the thresholds and the index
settings are the workspace's since #254: a station keeps only what is its own, its file, its
name and location, and the per-station index values of a batch's metadata file
(``origin["params"]``).

A change to the file, the metadata or a workspace setting keeps the jobs: each job records the
inputs it was produced from (``Job.inputs``), and :mod:`.workspace` compares them with the
station's to show the results as out of date until their replacement has finished.

The station keeps its own copy of the file: a job copies the file into its own ``input/``
folder when it is queued. A job a station shows is kept as long as the station
(:func:`.retention.kept_jobs`).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.urls import reverse
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


class Workspace(models.Model):
    """Stations and the settings they share. ``name`` is blank until the user names it
    (#234): :attr:`display_name` gives the default."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    # The last change to the workspace or any of its stations or batches: Station.save()
    # and BatchRun.save() bring it forward to their own updated_at.
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    # The settings every station shares (#254): the base period; the quality-control
    # thresholds of Quality (#77), climpact.config.QCParams fields as entered, empty until
    # changed (R's defaults, stations.forms.QC_DEFAULTS); and the index settings and output
    # options, as a ``station`` job's ``settings`` input (workspace.settings_of), empty for
    # the defaults.
    base_start = models.IntegerField(default=1971)
    base_end = models.IntegerField(default=2000)
    qc_params = models.JSONField(default=dict, blank=True)
    index_settings = models.JSONField(default=dict, blank=True)
    # The last change to the settings, while it can be undone (#254, workspace.undo): its
    # id (the ``change`` of the jobs it queued), the settings before it, and each station's
    # jobs and own index values before it. Empty when there is nothing to undo.
    undo = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.display_name

    @property
    def display_name(self) -> str:
        """The name, or the default the Flow board gives: one station's own name, else
        "6 stations, 17 Nov"."""
        if self.name:
            return self.name
        stations = list(self.stations.all()[:2])
        if len(stations) == 1:
            return str(stations[0])
        count = self.stations.count()
        from django.utils.formats import date_format
        from django.utils.translation import ngettext

        date = date_format(timezone.localtime(self.created_at), "j M")
        return ngettext("%(count)d station, %(date)s", "%(count)d stations, %(date)s", count) % {
            "count": count,
            "date": date,
        }

    def touch(self) -> None:
        self.updated_at = timezone.now()

    def get_absolute_url(self) -> str:
        """``/w/<id>/``: its one station, or its overview (#256, #234)."""
        return reverse("stations:workspace", args=[self.pk])

    def bring_forward(self, when: dt.datetime) -> None:
        """Record a change made at ``when`` to one of the workspace's stations or batches."""
        Workspace.objects.filter(pk=self.pk, updated_at__lt=when).update(updated_at=when)
        if self.updated_at < when:
            self.updated_at = when

    @property
    def expires_at(self) -> dt.datetime | None:
        """When the workspace is deleted, or None when workspaces do not expire."""
        if not settings.WORKSPACE_EXPIRY:
            return None
        return self.updated_at + dt.timedelta(days=settings.JOB_RETENTION_DAYS)

    def delete_files(self) -> None:
        import shutil

        for station in self.stations.all():
            station.delete_files()
        for run in self.batches.all():
            run.delete_files()
        # The workspace's Files (#239): stations/workspace_files.py.
        shutil.rmtree(stations_dir() / str(self.id), ignore_errors=True)

    def delete_if_empty(self) -> None:
        """Delete the workspace once it has no station and no batch left."""
        if not self.stations.exists() and not self.batches.exists():
            self.delete()


# Words a station's slug can't be, as they name other pages of the workspace (#256):
# ``/w/<id>/batch/`` is the workspace's batch, ``/w/<id>/settings/`` its settings (#234),
# ``/w/<id>/files/`` its Files (#239).
RESERVED_SLUGS = frozenset({"batch", "add", "settings", "progress", "rename", "undo", "files"})


def slug_for(name: str, taken) -> str:
    """A slug for a station called ``name``, not among ``taken`` nor reserved: ``sydney``,
    then ``sydney-2`` and so on."""
    from django.utils.text import slugify

    base = slugify(name)[:50].strip("-") or "station"
    slug, n = base, 1
    while slug in taken or slug in RESERVED_SLUGS:
        n += 1
        slug = f"{base}-{n}"
    return slug


class Station(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="stations")
    # Names the station in its workspace (the URLs of #256): made from the station name,
    # following it until the station details are confirmed, then kept.
    slug = models.SlugField(max_length=60)
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

    step = models.CharField(max_length=10, choices=Step.choices, default=Step.UPLOAD)

    # A station of a batch (#80, #255): {"batch": batch id, "station": its name in the
    # batch, "params": the IndexParams fields of its metadata line, "run": its state in
    # the batch's latest run ({"job", "state", "error"}, batch/fill.py)} and, when the
    # batch calculated it, "job": the batch job's id, "outputs": its folder in the job's
    # output/, "inputs": the inputs those results were produced from (#179). Empty
    # otherwise. Results show the batch's results until the station is calculated here.
    # The index values of "params" are the station's own: they take the place of the
    # workspace's (#254).
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
        constraints = [
            models.UniqueConstraint(fields=["workspace", "slug"], name="station_slug_unique")
        ]

    def __str__(self) -> str:
        return self.station_name or self.file_name or str(self.id)

    def url(self, name: str = "station", *args) -> str:
        """The address of the station's page ``stations:<name>`` (#256):
        ``/w/<workspace>/<slug>/…``, with ``args`` after the station (an index's key, a
        sheet's, a check's)."""
        return reverse(f"stations:{name}", args=[self.workspace_id, self.slug, *args])

    def get_absolute_url(self) -> str:
        return self.url()

    def save(self, *args, **kwargs) -> None:
        """Save, making a workspace of one for a new station, giving it a slug, and
        recording the change on the workspace."""
        if self.workspace_id is None:
            self.workspace = Workspace.objects.create(
                owner=self.owner, created_at=self.created_at, updated_at=self.updated_at
            )
        if not self.slug or self.step == Step.UPLOAD:
            taken = set(
                Station.objects.filter(workspace_id=self.workspace_id)
                .exclude(pk=self.pk)
                .values_list("slug", flat=True)
            )
            self.slug = slug_for(self.station_name or Path(self.file_name).stem, taken)
        super().save(*args, **kwargs)
        self.workspace.bring_forward(self.updated_at)

    def delete(self, *args, **kwargs):
        """Delete the station, and its workspace if nothing else is left in it."""
        workspace = self.workspace
        result = super().delete(*args, **kwargs)
        workspace.delete_if_empty()
        return result

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
        """The station metadata as the ``station`` job runner takes it: the station's name
        and location, with its workspace's base period."""
        return {
            "name": self.station_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "base_start": self.workspace.base_start,
            "base_end": self.workspace.base_end,
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
    def expires_at(self) -> dt.datetime | None:
        """When the station's workspace, with the station, is deleted (None: never, or not
        saved yet)."""
        return self.workspace.expires_at if self.workspace_id else None

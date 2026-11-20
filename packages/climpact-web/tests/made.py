"""Stations and batches made at model level, for the tests (#271).

Add stations (#233) is the one way into a workspace: it starts every station with its
details done, and runs several as a batch of the files reviewed on it. Two states the
tests need are no longer reached from a form of their own since the old New station and
batch upload forms went (#271), so they are made here, as those forms made them:

- :func:`station_to_set_up`: a station whose file is read and whose details are not done,
  on its setup page (``stations:setup``), as the New station page's "Read the file" (or
  ``/station/sample``) left one. The setup page stays, for a new file that needs new
  details and for a batch's station whose file was missing.
- :func:`batch` and :func:`queue`: a batch of a metadata file and its station files, every
  station listed with its file as Add stations reports them (``views_add.add_many``),
  queued as Add stations queues one (``views_add.queue_batch``) with the options a test
  needs (its base period, workers, plots), which Add stations' review takes from the
  workspace instead.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.test import RequestFactory

from climpact_web.batch import check
from climpact_web.batch.models import BatchRun
from climpact_web.jobs.views import OWNER_KEY
from climpact_web.stations.models import Source, Station
from climpact_web.stations.station_file import inspect_station_bytes
from climpact_web.stations.views import SAMPLE_NAME, apply_inspection, default_name, sample_bytes

# The details /station/sample filled in before #271 (Add stations' sample is named
# "Sydney Observatory Hill", #219).
SAMPLE_DETAILS = {
    "station_name": "sydney_observatory_hill_1936-2015",
    "latitude": -33.86,
    "longitude": 151.21,
}


def owner(client) -> str:
    """The test client's owner token (``jobs.views.owner_token``), made the first time."""
    session = client.session
    token = session.get(OWNER_KEY)
    if not token:
        token = secrets.token_urlsafe(24)
        session[OWNER_KEY] = token
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
    return token


def station_to_set_up(client, text=None, name="my station.txt", sample=False) -> Station:
    """A station of a workspace of its own with ``text`` read as the file ``name`` (or the
    Sydney sample with its details filled in), its details not done: its address leads to
    its setup page, the file card focused as after "Read the file"."""
    if sample:
        data, name = sample_bytes(), SAMPLE_NAME
    else:
        data = text.encode() if isinstance(text, str) else text
    inspection = inspect_station_bytes(data)
    assert inspection.ok, inspection.problems
    station = Station(
        owner=owner(client),
        source=Source.SAMPLE if sample else Source.UPLOAD,
        station_name=default_name(name),
    )
    apply_inspection(station, inspection, name)
    if sample:
        for field, value in SAMPLE_DETAILS.items():
            setattr(station, field, value)
        station.save()
    session = client.session
    session["setup_read"] = str(station.pk)
    session.save()
    return station


def batch(client, meta, metadata_name="stations.txt", workspace=None, **stations) -> BatchRun:
    """A batch of the metadata file ``meta`` (text, or None for the one in a zip) and the
    station files (text or bytes by name; a zip is unpacked, with any metadata file in it),
    waiting to be queued, in a workspace of its own or ``workspace``. Every station the
    metadata file lists has its file, as on Add stations, which adds only stations it can
    run (#311)."""
    from dataclasses import asdict

    uploads = [(n, t.encode() if isinstance(t, str) else t) for n, t in stations.items()]
    unpacked = check.unpack(uploads)
    metadata = meta.encode() if isinstance(meta, str) else meta
    if metadata is None:
        metadata_name, metadata = unpacked.metadata
    result = check.BatchCheck()
    listed = check.check_metadata(metadata, result)
    assert result.metadata_ok, result.metadata_problems
    for station in listed:
        assert inspect_station_bytes(unpacked.files[station.station_file]).ok, station.name
    run = BatchRun(owner=owner(client), metadata_name=metadata_name, workspace=workspace)
    run.save()
    run.save_metadata(metadata)
    run.save_files(unpacked.files)
    run.report = {"stations": [asdict(s) for s in listed]}
    run.save()
    return run


def queue(client, run: BatchRun, options=None) -> BatchRun:
    """Queue the batch with ``options``, as the batch's options took them (the base period's
    ``base_start`` and ``base_end``, ``workers``, ``plots``; no plots unless given): each
    station is its workspace's, waiting."""
    from climpact_web.stations.calculation import forget_undo
    from climpact_web.stations.views_add import queue_batch

    options = {"base_start": 1971, "base_end": 2000, "workers": 1, **(options or {})}
    space = run.workspace
    period = (int(options["base_start"]), int(options["base_end"]))
    if (space.base_start, space.base_end) != period:
        forget_undo(space)
        space.base_start, space.base_end = period
        space.touch()
        space.save()
    run.workers = int(options["workers"])
    run.plots = options.get("plots") not in (None, False, "", "0")
    request = RequestFactory().post("/")
    request.session = client.session
    queue_batch(request, run, title=f"Batch: {run.metadata_name or 'stations'}")
    run.refresh_from_db()
    return run

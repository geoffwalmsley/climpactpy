"""The workspace model (#231): a station or batch makes a workspace of its own, slugs,
default names, and changes recorded on the workspace."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from climpact_web.batch.models import BatchRun
from climpact_web.stations.models import Station, Step, Workspace, slug_for

pytestmark = pytest.mark.django_db


def test_a_new_station_makes_a_workspace_of_one():
    station = Station.objects.create(owner="o", station_name="Sydney", base_start=1981,
                                     base_end=2010, qc_params={"jump": 25.0})  # fmt: skip
    workspace = station.workspace
    assert workspace.owner == "o" and list(workspace.stations.all()) == [station]
    assert (workspace.base_start, workspace.base_end) == (1981, 2010)
    assert workspace.qc_params == {"jump": 25.0}
    assert workspace.display_name == "Sydney"


def test_a_new_batch_makes_its_own_workspace():
    run = BatchRun.objects.create(owner="o", metadata_name="metadata.txt")
    assert run.workspace.owner == "o" and list(run.workspace.batches.all()) == [run]


def test_the_default_name_of_several_stations():
    created = timezone.make_aware(dt.datetime(2026, 11, 17, 12))
    workspace = Workspace.objects.create(owner="o", created_at=created)
    for name in ("A", "B", "C"):
        Station.objects.create(owner="o", workspace=workspace, station_name=name)
    assert workspace.display_name == "3 stations, 17 Nov"
    workspace.name = "NSW coast"
    assert workspace.display_name == "NSW coast"


def test_slugs_are_unique_in_a_workspace():
    assert slug_for("Sydney Observatory Hill", set()) == "sydney-observatory-hill"
    assert slug_for("Sydney", {"sydney", "sydney-2"}) == "sydney-3"
    assert slug_for("–", set()) == "station"
    workspace = Workspace.objects.create(owner="o")
    a = Station.objects.create(owner="o", workspace=workspace, station_name="Sydney")
    b = Station.objects.create(owner="o", workspace=workspace, station_name="Sydney")
    assert (a.slug, b.slug) == ("sydney", "sydney-2")
    # Another workspace may use the same slug.
    assert Station.objects.create(owner="o", station_name="Sydney").slug == "sydney"


def test_the_slug_follows_the_name_until_the_details_are_confirmed():
    station = Station.objects.create(owner="o", station_name="my_file")
    station.station_name = "Sydney"
    station.save()
    assert station.slug == "sydney"
    station.step = Step.QC
    station.station_name = "Sydney Airport"
    station.save()
    assert station.slug == "sydney"  # kept, so links keep working


def test_a_change_to_a_station_or_batch_brings_the_workspace_forward():
    long_ago = timezone.now() - dt.timedelta(days=30)
    station = Station.objects.create(owner="o", station_name="A")
    Workspace.objects.filter(pk=station.workspace_id).update(updated_at=long_ago)
    station.touch()
    station.save()
    assert Workspace.objects.get(pk=station.workspace_id).updated_at == station.updated_at
    run = BatchRun.objects.create(owner="o")
    Workspace.objects.filter(pk=run.workspace_id).update(updated_at=long_ago)
    run.touch()
    run.save()
    assert Workspace.objects.get(pk=run.workspace_id).updated_at == run.updated_at


def test_deleting_the_last_station_deletes_the_workspace():
    workspace = Workspace.objects.create(owner="o")
    a = Station.objects.create(owner="o", workspace=workspace, station_name="A")
    b = Station.objects.create(owner="o", workspace=workspace, station_name="B")
    a.delete()
    assert Workspace.objects.filter(pk=workspace.pk).exists()
    b.delete()
    assert not Workspace.objects.filter(pk=workspace.pk).exists()


def test_expiry_follows_the_setting(settings):
    station = Station.objects.create(owner="o", station_name="A")
    settings.WORKSPACE_EXPIRY = False
    assert station.expires_at is None
    settings.WORKSPACE_EXPIRY = True
    days = dt.timedelta(days=settings.JOB_RETENTION_DAYS)
    assert station.expires_at == station.workspace.updated_at + days

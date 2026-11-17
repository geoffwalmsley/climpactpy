"""A batch fills its workspace (#255, part 3 of #231): once the run has finished its stations
are the stations of the batch's workspace, each showing the batch's results; the base period
and the custom index are the workspace's; a change to the workspace's settings recalculates
the batch's stations, as one change for the hosted limits; deleting the batch deletes its
workspace."""

import re

import pytest
from test_batch import created, media, metadata, run_worker, station  # noqa: F401
from test_workspace import edit, page, states

from climpact_web.batch.fill import batch_index_settings, fill_workspace
from climpact_web.batch.models import BatchRun
from climpact_web.jobs.models import Job, JobStart, Status
from climpact_web.stations import workspace
from climpact_web.stations.models import Source, Station, Step, Workspace
from climpact_web.stations.retention import kept_jobs

pytestmark = pytest.mark.django_db

OPTIONS = {"base_start": "2000", "base_end": "2001", "workers": "1"}  # no plots: faster


def finished_batch(client, *names, bad=()) -> BatchRun:
    """A batch of ``names`` (those in ``bad`` fail in the run), run to the end."""
    files = {f"{n}.txt": station(seed=k) for k, n in enumerate(names)}
    for n in bad:  # read by the check, refused by the core: dates out of order
        files[f"{n}.txt"] = "\n".join(reversed(station(days=400).splitlines())) + "\n"
    run = created(client, metadata(*files), **files)
    client.post(f"/batch/{run.pk}/run", OPTIONS)
    job = run_worker()
    assert job.status == Status.SUCCEEDED, job.error
    run.refresh_from_db()
    return run


def test_a_finished_batch_fills_its_workspace(client):
    run = finished_batch(client, "a", "b", bad=["c"])
    space = run.workspace
    # Nothing is added until the results are shown.
    assert not space.stations.exists()
    html = client.get(f"/batch/{run.pk}/results").content.decode()
    stations = {s.station_name: s for s in space.stations.all()}
    # The failed station is not added: it has no results to show.
    assert set(stations) == {"a", "b"}
    a = stations["a"]
    assert a.source == Source.BATCH and a.step == Step.QC and a.slug == "a"
    assert a.owner == run.owner and (a.latitude, a.longitude) == (-30, 150)
    assert a.origin["batch"] == str(run.pk) and a.origin["job"] == str(run.job_id)
    assert a.origin["params"]["spei_months"] == 24 and a.station_file.is_file()
    assert space.display_name.startswith("2 stations, ")
    # "Open" goes to the workspace's station; there is no separate workspace of one.
    assert f'href="/station/{a.pk}/"' in html and f'href="/station/{stations["b"].pk}/"' in html
    assert "Open as a single station" not in html and "batch/open" not in html
    assert "The stations calculated are the stations of this workspace." in html
    assert Workspace.objects.count() == 1
    # Showing the results again, or polling them, adds nothing.
    client.get(f"/batch/{run.pk}/results")
    client.get(f"/batch/{run.pk}/progress")
    assert Station.objects.count() == 2
    # The station shows the batch's results, current, with the workspace's base period.
    assert client.get(f"/station/{a.pk}/")["Location"] == f"/station/{a.pk}/results"
    html = page(client, a)
    assert states(html)["results"] == "done"
    assert not workspace.run_changes(a, workspace.shown_run(a))
    assert "These results are from the batch run." in html
    # An index page names the workspace in its breadcrumb, leading to the batch results.
    html = page(client, a, "results/txx")
    crumbs = re.findall(r'<ol class="context-bar__breadcrumb">(.*?)</ol>', html, re.S)[0]
    assert f'href="/batch/{run.pk}/results">2 stations, ' in crumbs
    # The old "Open as a single station" forms lead to the same station.
    assert client.post(f"/batch/{run.pk}/open/a")["Location"] == f"/station/{a.pk}/"
    assert client.post(f"/batch/{run.pk}/open/c").status_code == 404
    # The batch job is kept while the stations show it.
    assert str(run.job_id) in kept_jobs()


def test_a_deleted_station_is_not_added_again(client):
    run = finished_batch(client, "a", "b")
    client.get(f"/batch/{run.pk}/results")
    a = Station.objects.get(station_name="a")
    client.post(f"/station/{a.pk}/delete")
    client.get(f"/batch/{run.pk}/results")
    assert list(run.workspace.stations.values_list("station_name", flat=True)) == ["b"]
    assert 'href="/station/' in client.get(f"/batch/{run.pk}/results").content.decode()


def test_the_base_period_and_custom_index_are_the_workspaces(client):
    run = finished_batch(client, "a")
    space = Workspace.objects.get(pk=run.workspace_id)
    assert (space.base_start, space.base_end) == (2000, 2001)
    assert space.index_settings == batch_index_settings()
    assert run.job.params["custom"] is None
    fill_workspace(run)
    a = space.stations.get()
    assert workspace.station_settings(a)["params"]["custom"] is None
    # The check page starts from the workspace's base period.
    html = client.get(f"/batch/{run.pk}/").content.decode()
    assert re.search(r'name="base_start"[^>]*value="2000"', html)


def test_a_workspace_change_recalculates_the_batch_stations(client, settings):
    run = finished_batch(client, "a", "b", "c")
    client.get(f"/batch/{run.pk}/results")
    stations = list(run.workspace.stations.order_by("station_name"))
    settings.IS_HOSTED, settings.MIN_FREE_DISK_GB = True, 0
    settings.MAX_ACTIVE_JOBS_PER_IP, settings.MAX_QUEUED_JOBS = 1, 6
    starts = JobStart.objects.count()
    edit(client, stations[0], "base-period", {"base_start": "2000", "base_end": "2000"})
    # One station run each, with its own metadata line's values, and the checks (which the
    # batch's stations had not run here): one change, one start for the hosted limits.
    queued = Job.objects.filter(status=Status.QUEUED)
    assert sorted(queued.values_list("kind", flat=True)) == ["qc"] * 3 + ["station"] * 3
    assert JobStart.objects.count() == starts + 1
    for s in stations:
        s.refresh_from_db()
        assert s.indices_job.params["metadata"]["base_end"] == 2000
        assert s.indices_job.params["params"]["spei_months"] == 24
        assert s.indices_job.params["params"]["custom"] is None
        # Out of date until then: the batch's results stay on the page.
        assert workspace.shown_run(s) == run.job
        assert workspace.section_states(s)["results"] == "stale"
    # Undo puts the batch's results back, current again.
    client.post(f"/station/{stations[0].pk}/undo", {"next": f"/station/{stations[0].pk}/results"})
    for s in stations:
        s.refresh_from_db()
        assert s.indices_job is None and workspace.section_states(s)["results"] == "done"


def test_a_new_file_needing_another_base_period_changes_the_workspace(client):
    """A batch station's base period is every station's: a new file that needs another one
    (the New station page) changes the workspace and recalculates them all."""
    run = finished_batch(client, "a", "b")
    client.get(f"/batch/{run.pk}/results")
    a, b = run.workspace.stations.order_by("station_name")
    from test_batch import files

    client.post(
        f"/station/{a.pk}/setup",
        {
            "station_file": files(**{"a2.txt": station(start="2001-01-01")})[0],
            "station_name": "a",
            "latitude": "-30",
            "longitude": "150",
            "base_start": "2001",
            "base_end": "2001",
        },
    )
    space = Workspace.objects.get(pk=run.workspace_id)
    assert (space.base_start, space.base_end) == (2001, 2001)
    b.refresh_from_db()
    assert b.indices_job is not None and b.indices_job.params["metadata"]["base_start"] == 2001


def test_running_the_batch_again_updates_its_stations(client):
    run = finished_batch(client, "a")
    client.get(f"/batch/{run.pk}/results")
    a = run.workspace.stations.get()
    first_job = run.job_id
    client.post(f"/batch/{run.pk}/run", {**OPTIONS, "base_start": "2001"})
    assert run_worker().status == Status.SUCCEEDED
    run.refresh_from_db()
    assert run.job_id != first_job
    # Until the new results are shown the station is out of date (its base period changed).
    a.refresh_from_db()
    assert workspace.section_states(a)["results"] == "stale"
    client.get(f"/batch/{run.pk}/results")
    a.refresh_from_db()
    assert a.origin["job"] == str(run.job_id) and run.workspace.stations.count() == 1
    assert workspace.section_states(a)["results"] == "done"


def test_deleting_the_batch_deletes_its_workspace(client):
    run = finished_batch(client, "a")
    client.get(f"/batch/{run.pk}/results")
    a = run.workspace.stations.get()
    response = client.post(f"/batch/{run.pk}/delete", follow=True)
    assert "The batch and its stations were deleted." in response.content.decode()
    assert not Workspace.objects.exists() and not Station.objects.exists()
    assert not a.folder.exists() and not run.folder.exists()


def test_retention_keeps_the_workspace_as_a_whole(client, settings):
    """The batch and its stations share their workspace's retention (#253)."""
    import datetime as dt

    from django.utils import timezone

    from climpact_web.jobs.retention import purge_expired

    settings.WORKSPACE_EXPIRY = True
    run = finished_batch(client, "a")
    client.get(f"/batch/{run.pk}/results")
    a = run.workspace.stations.get()
    assert a.expires_at == run.expires_at == run.workspace.expires_at
    old = timezone.now() - dt.timedelta(days=8)
    Workspace.objects.update(updated_at=old)
    purge_expired()
    assert not BatchRun.objects.exists() and not Station.objects.exists()

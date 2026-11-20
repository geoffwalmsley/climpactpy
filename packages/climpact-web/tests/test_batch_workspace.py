"""A batch fills its workspace (#255, part 3 of #231): every station of the batch is a
station of its workspace from when the run is queued, with its run state (waiting,
calculating, done, not run, failed); those that calculated show the batch's results, those
that failed or were left out none, only why (``Calculate.dc.html``, #234); the base period
and the custom index are the workspace's; a change to the workspace's settings recalculates
the batch's stations, as one change for the hosted limits; deleting the batch deletes its
workspace."""

import re

import pytest
from test_batch import created, media, metadata, run_batch, run_worker, station  # noqa: F401
from test_workspace import edit, page, states

from climpact_web.batch import fill
from climpact_web.batch.fill import batch_index_settings, fill_workspace, run_progress, run_states
from climpact_web.batch.models import BatchRun
from climpact_web.jobs.models import Job, JobStart, Status
from climpact_web.stations import workspace
from climpact_web.stations.models import Source, Station, Step, Workspace
from climpact_web.stations.retention import kept_jobs

pytestmark = pytest.mark.django_db

OPTIONS = {"base_start": "2000", "base_end": "2001", "workers": "1"}  # no plots: faster


def queued_batch(client, *names, bad=(), missing=()) -> BatchRun:
    """A batch of ``names`` queued (those in ``bad`` fail in the run, those in ``missing``
    are listed but not uploaded, so the check leaves them out)."""
    files = {f"{n}.txt": station(seed=k) for k, n in enumerate([*names, *bad])}
    listed = [*files, *(f"{n}.txt" for n in missing)]
    run = run_batch(client, created(client, metadata(*listed), **files), OPTIONS)
    for n in bad:  # broken after the check, so it fails in the run itself
        (run.job.input_dir / "stations" / f"{n}.txt").write_text(
            "2000 1 1 0 20 10\n1999 1 1 0 20 10\n"
        )
    return run


def finished_batch(client, *names, bad=(), missing=()) -> BatchRun:
    """A batch of ``names`` (see :func:`queued_batch`), run to the end."""
    run = queued_batch(client, *names, bad=bad, missing=missing)
    job = run_worker()
    assert job.status == Status.SUCCEEDED, job.error
    run.refresh_from_db()
    return run


def states_of(run) -> dict[str, tuple]:
    stations = {s.pk: s.station_name for s in run.workspace.stations.all()}
    out = run_states(run.workspace.stations.all())
    return {stations[pk]: (r.state, r.percent, r.error) for pk, r in out.items()}


def test_every_station_is_added_when_the_batch_is_queued(client):
    run = queued_batch(client, "a", "b", bad=["c"], missing=["d"])
    stations = {s.station_name: s for s in run.workspace.stations.all()}
    # Every station of the metadata file, the one left out by the check too.
    assert set(stations) == {"a", "b", "c", "d"}
    a, d = stations["a"], stations["d"]
    assert a.source == Source.BATCH and a.step == Step.QC and a.slug == "a"
    assert a.owner == run.owner and (a.latitude, a.longitude) == (-30, 150)
    assert a.origin["batch"] == str(run.pk) and a.origin["params"]["spei_months"] == 24
    assert a.station_file.is_file() and a.origin["run"] == {
        "job": str(run.job_id),
        "state": "waiting",
    }
    # No results yet: none of the batch's, and none empty.
    assert not workspace.batch_results(a) and workspace.shown_run(a) is None
    # Left out: no file, not run, with why; its page is where a file is loaded.
    assert not d.station_file.exists() and d.step == Step.UPLOAD
    assert client.get(d.url())["Location"] == f"{d.url()}setup"
    assert client.get(f"{d.url()}setup").status_code == 200
    # Waiting: its address leads to Quality, its checks not yet run.
    assert client.get(a.url())["Location"] == f"{a.url()}quality"
    assert client.get(f"{a.url()}quality").status_code == 200
    got = states_of(run)
    assert got["a"] == got["b"] == got["c"] == ("waiting", None, "")
    assert got["d"][0] == "not_run" and "No file named d.txt was uploaded." in got["d"][2]
    progress = run_progress(run)
    assert (progress.total, progress.done, progress.waiting, progress.not_run) == (3, 0, 3, 1)
    assert not progress.finished and progress.elapsed is None


def test_a_station_calculating_shows_how_far_it_is(client):
    import json

    from climpact_web.jobs.runners import STATIONS_FILE

    run = queued_batch(client, "a", "b")
    job = run.job
    job.status, job.started_at = Status.RUNNING, job.created_at
    job.save()
    rows = [
        {"name": "a", "state": "running", "step": 3, "total": 12, "stage": ""},
        {"name": "b", "state": "waiting", "step": 0, "total": 12, "stage": ""},
    ]
    job.output_dir.mkdir(parents=True, exist_ok=True)
    (job.output_dir / STATIONS_FILE).write_text(json.dumps({"stations": rows}))
    assert states_of(run) == {"a": ("calculating", 25, ""), "b": ("waiting", None, "")}
    progress = run_progress(run)
    assert (progress.total, progress.done, progress.calculating, progress.waiting) == (2, 0, 1, 1)
    assert progress.elapsed is not None and not progress.finished


def test_a_finished_batch_fills_its_workspace(client):
    run = finished_batch(client, "a", "b", bad=["c"], missing=["d"])
    space = run.workspace
    # The run's states, as the runner left them, before the results are shown.
    got = states_of(run)
    assert got["a"] == ("done", None, "") and got["c"][0] == "failed" and got["c"][2]
    html = client.get(f"/w/{run.workspace_id}/").content.decode()
    stations = {s.station_name: s for s in space.stations.all()}
    assert set(stations) == {"a", "b", "c", "d"}
    a, c = stations["a"], stations["c"]
    assert a.origin["job"] == str(run.job_id) and a.origin["run"]["state"] == "done"
    assert space.display_name.startswith("4 stations, ")
    # The failed station stays, with R's or our error in words, and no results.
    got = states_of(run)
    assert got["c"][0] == "failed" and "Error" not in got["c"][2] and got["c"][2]
    assert got["d"][0] == "not_run"
    assert "job" not in c.origin and workspace.shown_run(c) is None
    progress = run_progress(run)
    assert (progress.total, progress.done, progress.failed, progress.not_run) == (3, 2, 1, 1)
    assert progress.finished and progress.elapsed is not None and progress.remaining is None
    # A failed station opens on its Indices: nothing calculated, the settings to change.
    assert client.get(c.url())["Location"] == f"{c.url()}indices"
    assert "The indices are not calculated yet." in page(client, c)
    # The overview's rows lead to the workspace's stations (#234); there is no separate
    # workspace of one.
    assert f'href="{a.url()}indices"' in html and f'href="{stations["b"].url()}indices"' in html
    assert "Open as a single station" not in html and "batch/open" not in html
    assert 'id="stations-title"' in html and 'data-indices="failed"' in html
    assert Workspace.objects.count() == 1
    # Showing the overview again, or polling it, adds nothing.
    client.get(f"/w/{run.workspace_id}/")
    client.get(f"/w/{run.workspace_id}/progress")
    assert Station.objects.count() == 4
    # The station shows the batch's results, current, with the workspace's base period.
    assert client.get(a.url())["Location"] == f"{a.url()}indices"
    html = page(client, a)
    assert states(html)["results"] == "done"
    assert not workspace.run_changes(a, workspace.shown_run(a))
    assert "These results are from the batch run." in html
    # The results record the file the batch read, for their provenance line (#269).
    data = a.origin["inputs"]["data"]
    assert data == workspace.file_record("a.txt", a.summary) and data["first_year"]
    # An index page names the workspace in its breadcrumb, leading to its overview.
    html = page(client, a, "indices/txx")
    crumbs = re.findall(r'<ol class="context-bar__breadcrumb">(.*?)</ol>', html, re.S)[0]
    assert f'href="/w/{run.workspace_id}/">4 stations, ' in crumbs
    # The old "Open as a single station" forms are gone (#256).
    assert client.post(f"/batch/{run.pk}/open/a").status_code == 405
    # The batch job is kept while the stations show it.
    assert str(run.job_id) in kept_jobs()


def test_a_job_from_before_stations_were_added_when_queued(client):
    """A batch job queued before #255 added its stations when queued: they are all added
    when it has finished, as they would have been."""
    run = queued_batch(client, "a", bad=["c"], missing=["d"])
    Station.objects.all().delete()
    run.job.params.pop(fill.ADDED)
    run.job.save()
    assert run_worker().status == Status.SUCCEEDED
    run.refresh_from_db()
    fill_workspace(run)
    space = Workspace.objects.get(pk=run.workspace_id)
    stations = {s.station_name: s for s in space.stations.all()}
    assert set(stations) == {"a", "c", "d"}
    assert workspace.batch_results(stations["a"]) and not workspace.batch_results(stations["c"])
    got = states_of(run)
    assert [got[n][0] for n in "acd"] == ["done", "failed", "not_run"]


def test_a_deleted_station_is_not_added_again(client):
    run = queued_batch(client, "a", "b")
    a = Station.objects.get(station_name="a")
    client.post(f"{a.url()}delete")  # during the run
    run_worker()
    client.get(f"/w/{run.workspace_id}/")
    assert list(run.workspace.stations.values_list("station_name", flat=True)) == ["b"]
    # One station left: the workspace's address opens it, and the overview's progress
    # reloads the page, which then opens it (#234).
    assert client.get(f"/w/{run.workspace_id}/")["Location"] == Station.objects.get().url("results")
    response = client.get(f"/w/{run.workspace_id}/progress")
    assert response.status_code == 204 and response["HX-Refresh"] == "true"


def test_the_base_period_and_custom_index_are_the_workspaces(client):
    run = finished_batch(client, "a")
    space = Workspace.objects.get(pk=run.workspace_id)
    assert (space.base_start, space.base_end) == (2000, 2001)
    assert space.index_settings == batch_index_settings()
    assert run.job.params["custom"] is None
    fill_workspace(run)
    a = space.stations.get()
    assert workspace.station_settings(a)["params"]["custom"] is None


def test_a_workspace_change_recalculates_the_batch_stations(client, settings):
    run = finished_batch(client, "a", "b", "c")
    client.get(f"/w/{run.workspace_id}/")
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
    # Each station's state is its own run's now, for the overview's Stations table.
    assert {v[0] for v in states_of(run).values()} == {"waiting"}
    for s in stations:
        s.refresh_from_db()
        assert s.indices_job.params["metadata"]["base_end"] == 2000
        assert s.indices_job.params["params"]["spei_months"] == 24
        assert s.indices_job.params["params"]["custom"] is None
        # Out of date until then: the batch's results stay on the page.
        assert workspace.shown_run(s) == run.job
        assert workspace.section_states(s)["results"] == "stale"
    # Undo puts the batch's results back, current again.
    client.post(f"{stations[0].url()}undo", {"next": f"{stations[0].url()}indices"})
    for s in stations:
        s.refresh_from_db()
        assert s.indices_job is None and workspace.section_states(s)["results"] == "done"


def test_a_new_file_needing_another_base_period_changes_the_workspace(client):
    """A batch station's base period is every station's: a new file that needs another one
    (the New station page) changes the workspace and recalculates them all."""
    run = finished_batch(client, "a", "b")
    client.get(f"/w/{run.workspace_id}/")
    a, b = run.workspace.stations.order_by("station_name")
    from test_batch import files

    client.post(
        f"{a.url()}setup",
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
    client.get(f"/w/{run.workspace_id}/")
    a = run.workspace.stations.get()
    first_job, first_job_id = run.job_id, str(run.job_id)
    run_batch(client, run, {**OPTIONS, "base_start": "2001"})
    assert states_of(run)["a"][0] == "waiting"
    assert workspace.batch_results(Station.objects.get(pk=a.pk))
    assert run_worker().status == Status.SUCCEEDED
    run.refresh_from_db()
    assert run.job_id != first_job
    a.refresh_from_db()
    # Its earlier results stay on the page while the new run goes.
    assert a.origin["job"] == first_job_id and a.origin["run"]["job"] == str(run.job_id)
    # Until the new results are shown the station is out of date (its base period changed).
    a.refresh_from_db()
    assert workspace.section_states(a)["results"] == "stale"
    client.get(f"/w/{run.workspace_id}/")
    a.refresh_from_db()
    assert a.origin["job"] == str(run.job_id) and run.workspace.stations.count() == 1
    assert workspace.section_states(a)["results"] == "done"


def test_deleting_the_workspace_deletes_its_batch(client):
    run = finished_batch(client, "a", "b")
    client.get(f"/w/{run.workspace_id}/")
    a = run.workspace.stations.first()
    assert client.post(f"/w/{run.workspace_id}/delete")["Location"] == "/w/"
    assert not Workspace.objects.exists() and not Station.objects.exists()
    assert not BatchRun.objects.exists()
    assert not a.folder.exists() and not run.folder.exists()


def test_retention_keeps_the_workspace_as_a_whole(client, settings):
    """The batch and its stations share their workspace's retention (#253)."""
    import datetime as dt

    from django.utils import timezone

    from climpact_web.jobs.retention import purge_expired

    settings.WORKSPACE_EXPIRY = True
    run = finished_batch(client, "a")
    client.get(f"/w/{run.workspace_id}/")
    a = run.workspace.stations.get()
    assert a.expires_at == run.expires_at == run.workspace.expires_at
    old = timezone.now() - dt.timedelta(days=8)
    Workspace.objects.update(updated_at=old)
    purge_expired()
    assert not BatchRun.objects.exists() and not Station.objects.exists()

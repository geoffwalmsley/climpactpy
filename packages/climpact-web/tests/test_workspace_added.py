"""A station added to a workspace of several stations (#277): its run is the user's own at
once, as a batch's stations are, so the overview, the station's Indices, Files and the
trend grid say the same thing about it, before "Go to indices" and after it."""

import pytest
from test_add_stations import review_url, stage
from test_batch import created, media, metadata, run_worker, station  # noqa: F401
from test_batch_workspace import finished_batch
from test_workspace_overview import rows

from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.worker import claim, run_job
from climpact_web.stations import overview, trend_grid, workspace, workspace_files
from climpact_web.stations.models import Station, Step, Workspace

pytestmark = pytest.mark.django_db


def run_all() -> None:
    """Run every queued job, speculative ones too."""
    while (job := claim("test-worker")) is not None:
        run_job(job)


def add_one(client, space, name="C", seed=3):
    run = stage(client, url=f"/w/{space.pk}/add/", c__txt=station(seed=seed))
    data = {"intent": "add", "file-0": "c.txt", "name-0": name, "lat-0": "-30", "lon-0": "150"}
    assert client.post(review_url(run), data)["Location"] == f"/w/{space.pk}/"
    return Station.objects.get(workspace=space, station_name=name)


def states(space, owner, c):
    """What each place says about ``c``: the overview's Indices and Significant, its
    Indices tab, Files' reason and whether the trend grid has its trends."""
    table = overview.rows(space, owner)
    row = next(r for r in table if r.station.pk == c.pk)
    items = workspace_files.entries(space, owner, table)
    entry = next(e for e in items if e.station.pk == c.pk)
    grid = trend_grid._stations(items)
    cards = next(s.cards for s in grid if s.entry.station.pk == c.pk)
    return {
        "overview": row.indices.state,
        "significant": row.significant,
        "tab": workspace.section_states(c)["results"],
        "files": entry.why,
        "grid": bool(cards),
    }


def test_a_station_added_to_a_workspace_is_calculated_at_once(client):
    run = finished_batch(client, "a", "b")
    space = run.workspace
    c = add_one(client, space)
    # Its run is the user's own, not speculative: the workspace has chosen to calculate.
    assert c.reached(Step.INDICES) and workspace.committed(c)
    assert c.indices_job.kind == "station" and not c.indices_job.is_speculative
    html = client.get(f"/w/{space.pk}/").content.decode()
    assert rows(html)["c"] in ("waiting", "calculating")
    run_all()
    c.refresh_from_db()
    assert c.indices_job.status == Status.SUCCEEDED
    # Before "Go to indices": every place shows its results.
    seen = states(space, c.owner, c)
    assert seen["overview"] == "done" and " of " in seen["significant"]
    assert seen["tab"] == "done" and seen["files"] == "" and seen["grid"]
    html = client.get(f"/w/{space.pk}/").content.decode()
    assert rows(html)["c"] == "done"
    assert client.get(c.url("results")).status_code == 200
    # After "Go to indices" (its Quality's button): nothing changes, no run is queued.
    jobs = Job.objects.count()
    assert client.post(c.url("qc_continue"))["Location"] == c.url("results")
    c.refresh_from_db()
    assert Job.objects.count() == jobs
    assert states(space, c.owner, c) == seen


def test_the_first_station_is_calculated_once_a_second_is_added(client):
    client.post("/add/sample")
    first = Station.objects.get()
    space = first.workspace
    # A workspace of one: the run is speculative until "Go to indices".
    assert not workspace.committed(first) and first.indices_job.is_speculative
    add_one(client, space)
    first.refresh_from_db()
    assert workspace.committed(first) and not first.indices_job.is_speculative
    assert Workspace.objects.count() == 1 and space.stations.count() == 2


def test_a_run_not_in_use_shows_nowhere(client):
    """Whatever the way in, a station whose run is not in use yet (speculative, before "Go
    to indices") reads the same everywhere: no results, its Indices locked."""
    run = finished_batch(client, "a", "b")
    space = run.workspace
    c = add_one(client, space)
    run_all()
    Station.objects.filter(pk=c.pk).update(step=Step.QC)  # as if never committed
    c.refresh_from_db()
    seen = states(space, c.owner, c)
    assert seen == {
        "overview": "",
        "significant": "–",
        "tab": "locked",
        "files": "not calculated",
        "grid": False,
    }
    # "Go to indices" puts it in use: everything shows its results.
    assert client.post(c.url("qc_continue"))["Location"] == c.url("results")
    c.refresh_from_db()
    seen = states(space, c.owner, c)
    assert seen["overview"] == "done" and seen["tab"] == "done" and seen["grid"]
    assert seen["files"] == ""

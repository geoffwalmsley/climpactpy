"""Copy to workspace… (#241): a station copied to another workspace, or to a new one, is
checked and calculated with that workspace's settings, and the station copied is not
changed."""

import re

import made
import pytest
from test_batch import created, media, metadata, run_worker, station  # noqa: F401
from test_batch_workspace import finished_batch
from test_workspace_added import run_all

from climpact_web.jobs.models import Job, Status
from climpact_web.stations import workspace
from climpact_web.stations.models import Station, Workspace

pytestmark = pytest.mark.django_db


def snapshot(s: Station) -> tuple:
    s.refresh_from_db()
    return (
        s.workspace_id,
        s.slug,
        s.step,
        s.qc_job_id,
        s.indices_job_id,
        s.origin,
        s.station_name,
        s.file_hash,
    )


def test_copy_a_station_to_another_workspace(client):
    run = finished_batch(client, "a", "b")
    batch_space = run.workspace  # base 2000–2001
    client.post("/add/sample")
    sydney = Station.objects.get(source="sample")
    home = sydney.workspace
    client.get(f"/w/{batch_space.pk}/")  # the batch's results recorded (fill_workspace)
    a = Station.objects.get(workspace=batch_space, station_name="a")
    before = snapshot(a)
    url = a.url("copy")
    html = client.get(url).content.decode()
    # The page: its heading, the workspaces to choose from and a new one, Copy and Cancel.
    assert '<h1 class="sheet__title">Copy to workspace</h1>' in html
    assert f'value="{home.pk}"' in html and "Sydney Observatory Hill · 1 station" in html
    assert "base 1971–2000" in html
    assert 'value="new"' in html and "A new workspace, with this workspace&#x27;s settings" in html
    assert f'value="{batch_space.pk}"' not in html  # not its own workspace
    response = client.post(url, {"target": str(home.pk)})
    assert response["Location"] == f"/w/{home.pk}/"
    copy = Station.objects.get(workspace=home, station_name="a")
    # The file, name, location and own values are copied; the jobs are new, with the
    # workspace's settings (its base period, not the batch's).
    assert copy.file_hash == a.file_hash and (copy.latitude, copy.longitude) == (-30, 150)
    assert copy.origin == {"params": a.origin["params"]}
    assert copy.qc_job.params["metadata"]["base_start"] == 1971
    assert copy.indices_job.params["metadata"]["base_start"] == 1971
    # A workspace of several: its run is in use at once, as the first station's now is.
    assert workspace.committed(copy) and not copy.indices_job.is_speculative
    sydney.refresh_from_db()
    assert workspace.committed(sydney)
    # The station copied is not changed, nor its workspace.
    assert snapshot(a) == before and batch_space.stations.count() == 2
    batch_space.refresh_from_db()
    assert (batch_space.base_start, batch_space.base_end) == (2000, 2001)
    page = client.get(f"/w/{home.pk}/").content.decode()
    # Its default name is now the one of several stations (the Flow board's rule).
    assert "a was copied to 2 stations, " in page and "being calculated with its settings" in page


def test_copy_a_station_to_a_new_workspace(client):
    run = finished_batch(client, "a", "b")
    client.get(f"/w/{run.workspace_id}/")  # the batch's results recorded (fill_workspace)
    a = Station.objects.get(workspace=run.workspace, station_name="a")
    before = snapshot(a)
    response = client.post(a.url("copy"), {"target": "new"})
    copy = Station.objects.exclude(workspace=run.workspace).get()
    space = copy.workspace
    assert space.stations.count() == 1 and Workspace.objects.count() == 2
    # The new workspace has the settings of the station's workspace.
    assert (space.base_start, space.base_end) == (2000, 2001)
    assert space.index_settings == run.workspace.index_settings
    # The batch's results were in use, so the copy's are: it opens on its Indices.
    assert workspace.committed(copy) and response["Location"] == copy.url("results")
    run_all()
    copy.refresh_from_db()
    assert copy.indices_job.status == Status.SUCCEEDED
    assert workspace.section_states(copy)["results"] == "done"
    assert snapshot(a) == before


def test_a_station_not_yet_in_use_is_copied_as_it_is(client):
    client.post("/add/sample")
    sydney = Station.objects.get()
    response = client.post(sydney.url("copy"), {"target": "new"})
    copy = Station.objects.exclude(pk=sydney.pk).get()
    # Before "Go to indices", the copy waits for it too: it opens on its Quality.
    assert not workspace.committed(copy) and copy.indices_job.is_speculative
    assert response["Location"] == copy.url("qc")


def test_a_workspace_with_a_station_of_that_name_is_refused(client):
    client.post("/add/sample")
    sydney = Station.objects.get()
    client.post(sydney.url("copy"), {"target": "new"})
    jobs = Job.objects.count()
    copy = Station.objects.exclude(pk=sydney.pk).get()
    html = client.get(sydney.url("copy")).content.decode()
    assert "has a station of this name" in html
    response = client.post(sydney.url("copy"), {"target": str(copy.workspace_id)})
    assert response.status_code == 200
    html = response.content.decode()
    assert "already has a station called Sydney Observatory Hill" in html
    assert Station.objects.count() == 2 and Job.objects.count() == jobs
    assert "Choose a workspace." in client.post(sydney.url("copy"), {}).content.decode()


def test_copy_is_offered_on_the_station_and_in_the_stations_table(client):
    run = finished_batch(client, "a", "b")
    a = Station.objects.get(station_name="a")
    html = client.get(a.url("results")).content.decode()
    provenance = html.split('class="context-bar__provenance"')[1].split("</p>")[0]
    assert re.search(rf'href="{a.url("copy")}\?next=[^"]+">Copy to workspace…</a>', provenance)
    overview = client.get(f"/w/{run.workspace_id}/").content.decode()
    row = overview.split('data-station="a"')[1].split("</tr>")[0]
    assert f'href="{a.url("copy")}?next=/w/{run.workspace_id}/"' in row
    assert "Copy…" in row and "a to another workspace" in row
    # Cancel goes back where the copy was asked from.
    page = client.get(f"{a.url('copy')}?next=/w/{run.workspace_id}/").content.decode()
    assert f'href="/w/{run.workspace_id}/"' in page.split("sheet__title")[1]
    # A station not set up yet has nothing to copy.
    unset = made.station_to_set_up(client, station())
    assert client.get(unset.url("copy"))["Location"] == workspace.home_url(unset)

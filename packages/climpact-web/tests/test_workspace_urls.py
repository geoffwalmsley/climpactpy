"""Workspace URLs (#256, part 4 of #231): ``/w/<id>/`` for the workspace, its stations
under ``/w/<id>/<slug>/…`` and its batch under ``/w/<id>/batch/…``; what ``/w/<id>/``
opens; the old ``/station/<id>/…`` and ``/batch/<id>/…`` addresses redirecting while their
station or batch is kept; and no session reaching another's workspace."""

import re

import pytest
from django.test import Client
from test_batch import created, media, metadata, run_worker, station  # noqa: F401
from test_batch_workspace import finished_batch, queued_batch
from test_indices_results import STATION, ready_analysis

from climpact_web.jobs.models import Status
from climpact_web.jobs.views import OWNER_KEY
from climpact_web.stations.models import Station, Workspace, slug_for

pytestmark = pytest.mark.django_db


def other_session() -> Client:
    other = Client()
    session = other.session
    session[OWNER_KEY] = "someone-else"
    session.save()
    return other


def test_a_stations_pages_are_under_its_workspace(client):
    analysis = ready_analysis(client)
    base = f"/w/{analysis.workspace_id}/sydney_observatory_hill_1936-2015/"
    assert analysis.slug == STATION.lower() and analysis.url() == base
    assert analysis.url("qc") == base + "quality"
    assert analysis.url("results") == base + "indices"
    assert analysis.url("result", "txx") == base + "indices/txx"
    assert analysis.url("edit_input", "base-period") == base + "inputs/base-period"
    assert analysis.url("recalculate") == base + "recalculate"
    assert analysis.workspace.get_absolute_url() == f"/w/{analysis.workspace_id}/"
    html = client.get(base + "quality").content.decode()
    # The tabs, the polling and the Inputs panel's links all use the new addresses.
    assert f'href="{base}quality" data-tab="quality"' in html
    assert f'hx-get="{base}quality/progress"' in html
    assert f'href="{base}inputs/base-period?next=' in html
    # The header's Workspaces is current on it (#227).
    assert '<a href="/w/" data-nav="workspaces" aria-current="true">' in html
    # Only the charts' data keeps the station's id (an API, not a page: /charts/station/).
    assert not re.findall(r'"/station/(?!new")', html.replace("/charts/station/", ""))


def test_a_workspace_of_one_station_opens_it_straight_away(client):
    load = client.post("/station/sample")["Location"]
    analysis = Station.objects.get()
    assert load == analysis.url("setup")
    # Not set up yet: the New station page.
    assert client.get(f"/w/{analysis.workspace_id}/")["Location"] == load
    analysis = ready_analysis(client)
    space = f"/w/{analysis.workspace_id}/"
    assert client.get(space)["Location"] == analysis.url("qc")
    assert client.get(analysis.url())["Location"] == analysis.url("qc")


def test_a_batch_workspace_opens_its_overview(client):
    run = created(client, metadata("a", "b"), **{"a.txt": station(), "b.txt": station(seed=1)})
    space = f"/w/{run.workspace_id}/"
    # Not run yet: the check page, at the workspace's address.
    response = client.get(space)
    assert response.status_code == 200 and 'action="' + space + 'batch/run"' in response.text
    # Run: the workspace's overview (#234), with the batch's stations (added when it was
    # queued).
    run = finished_batch(client, "c", "d")
    space = f"/w/{run.workspace_id}/"
    html = client.get(space).content.decode()
    assert 'id="stations-title"' in html and "2 stations calculated in" in html
    assert set(run.workspace.stations.values_list("slug", flat=True)) == {"c", "d"}
    assert f'href="{space}c/indices"' in html and f'href="{space}d/indices"' in html
    # Down to one station, the workspace opens it.
    Station.objects.get(slug="c").delete()
    d = Station.objects.get(slug="d")
    assert client.get(space)["Location"] == d.url("results")


def test_old_station_addresses_redirect_while_the_station_is_kept(client):
    analysis = ready_analysis(client)
    old, new = f"/station/{analysis.pk}/", analysis.url()
    for path, target in [
        ("", ""),
        ("quality", "quality"),
        ("quality/checks/outliers?group=prcp-high", "quality/checks/outliers?group=prcp-high"),
        ("results", "indices"),
        ("results?show=txx", "indices?show=txx"),
        ("results/txx?series=txx_MON&view=anomaly", "indices/txx?series=txx_MON&view=anomaly"),
        ("results/progress", "indices/progress"),
        ("indices?index=txx", "recalculate?index=txx"),
        ("inputs/settings?next=%2Fx", "inputs/settings?next=%2Fx"),
        ("downloads", "downloads"),
        ("series.csv", "series.csv"),
    ]:
        response = client.get(old + path)
        # Temporary: the new address follows the slug, which follows the name until the
        # details are confirmed.
        assert response.status_code == 302 and response["Location"] == new + target, path
    # Another session's station, or one deleted: 404. A POST is not redirected.
    assert other_session().get(old + "quality").status_code == 404
    assert client.post(old + "quality/continue").status_code == 405
    analysis.delete()
    assert client.get(old + "quality").status_code == 404


def test_old_batch_addresses_redirect_while_the_batch_is_kept(client):
    run = created(client, metadata("a"), **{"a.txt": station()})
    space = f"/w/{run.workspace_id}/"
    old, new = f"/batch/{run.pk}/", space + "batch/"
    for path, target in [
        ("", new),
        ("progress", new + "progress"),
        ("files?x=1", new + "files?x=1"),
        # The results are the workspace's own address, where the overview will be (#234).
        ("results", space),
        ("results?x=1", space + "?x=1"),
    ]:
        response = client.get(old + path)
        assert response.status_code == 302 and response["Location"] == target, path
    assert client.get(new).status_code == 200
    # The results' interim address under the workspace leads there too.
    assert client.get(new + "results")["Location"] == space
    assert other_session().get(new + "results").status_code == 404
    assert other_session().get(old).status_code == 404
    assert client.post(old + "run").status_code == 405
    run.workspace.delete()
    assert client.get(old).status_code == 404


def test_no_session_reaches_another_sessions_workspace(client):
    analysis = ready_analysis(client)
    run = created(client, metadata("a"), **{"a.txt": station()})
    other = other_session()
    for url in (
        f"/w/{analysis.workspace_id}/",
        analysis.url(),
        analysis.url("qc"),
        analysis.url("results"),
        analysis.url("edit_input", "base-period"),
        f"/w/{run.workspace_id}/",
        f"/w/{run.workspace_id}/batch/",
        f"/w/{run.workspace_id}/",
    ):
        assert other.get(url).status_code == 404, url
    assert other.post(analysis.url("undo")).status_code == 404
    assert other.post(f"/w/{run.workspace_id}/batch/delete").status_code == 404
    # A wrong slug, or a station under a workspace it is not in, is not found either.
    assert client.get(f"/w/{analysis.workspace_id}/nope/quality").status_code == 404
    assert client.get(f"/w/{run.workspace_id}/{analysis.slug}/quality").status_code == 404
    assert client.get(f"/w/{analysis.workspace_id}/batch/").status_code == 404
    assert client.get(f"/w/{Workspace().pk}/").status_code == 404


def test_batch_is_not_a_station_slug():
    assert slug_for("Batch", set()) == "batch-2"
    assert slug_for("batch", {"batch-2"}) == "batch-3"
    assert slug_for("Batchelor", set()) == "batchelor"


def test_an_edit_returns_only_to_its_own_stations_pages(client):
    analysis = ready_analysis(client)
    sheet = analysis.url("edit_input", "base-period")
    data = {"base_start": "1971", "base_end": "2000"}
    for back, target in [
        (analysis.url("qc"), analysis.url("qc")),
        (f"/station/{analysis.pk}/quality", analysis.url("qc")),  # the old one: home
        ("/w/" + str(analysis.workspace_id) + "/other/quality", analysis.url("qc")),
        ("https://example.com/", analysis.url("qc")),
    ]:
        response = client.post(sheet, {**data, "next": back})
        assert response["Location"] == target, back


def test_a_batchs_waiting_failed_and_left_out_stations_open(client):
    """Every station of a batch is in its workspace (#255), those that wait, failed or
    were left out too: each address opens a page, never an error."""
    run = queued_batch(client, "a", bad=["c"], missing=["d"])
    a, c, d = (Station.objects.get(station_name=n) for n in "acd")
    # Queued: the waiting stations lead to Quality, the one without a file to the New
    # station page, where a file is loaded.
    assert client.get(a.url())["Location"] == a.url("qc")
    assert client.get(c.url())["Location"] == c.url("qc")
    assert client.get(d.url())["Location"] == d.url("setup")
    assert client.get(d.url("qc"))["Location"] == d.url("setup")
    for station_ in (a, c, d):
        for name in ("qc", "results", "downloads", "recalculate", "station"):
            response = client.get(station_.url(name), follow=True)
            assert response.status_code == 200, (station_.station_name, name)
    assert run_worker().status == Status.SUCCEEDED
    # Finished: the workspace's overview; the failed station opens on its Indices, which
    # say why and lead to the settings.
    html = client.get(f"/w/{run.workspace_id}/").text
    assert 'id="stations-title"' in html and "c failed:" in html
    c.refresh_from_db()
    assert client.get(c.url())["Location"] == c.url("results")
    html = client.get(c.url("results")).content.decode()
    assert "The batch could not calculate this station." in html
    assert "The last row of the station file" in html and "Check the settings and calculate" in html
    assert client.get(a.url("results")).status_code == 200
    assert "could not calculate" not in client.get(a.url("results")).content.decode()


def test_a_workspace_of_one_failed_station_opens_it(client):
    run = finished_batch(client, bad=["c"])
    c = Station.objects.get()
    # The workspace's address, and the results' old ones, lead to the station's Indices,
    # where it says why it failed.
    for url in (f"/w/{run.workspace_id}/", f"/w/{run.workspace_id}/batch/results"):
        response = client.get(url, follow=True)
        assert response.redirect_chain[-1][0] == c.url("results"), url
        assert "The batch could not calculate this station." in response.text
    # A batch of one station still waiting: its Quality, its checks not yet run.
    run = queued_batch(client, "a")
    assert client.get(f"/w/{run.workspace_id}/")["Location"] == Station.objects.get(
        station_name="a"
    ).url("qc")

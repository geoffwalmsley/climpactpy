"""The landing page, Get started and Workspaces (#242): the Workspaces list replaced "Your
calculations", Get started offers the workspaces changed last, a workspace can be deleted,
and the landing page shows real output and true facts."""

import csv
import datetime as dt
import re
from pathlib import Path

import pytest
from django.test import override_settings
from django.utils import timezone
from test_batch import created, media, metadata, run_worker, station  # noqa: F401
from test_batch_workspace import finished_batch
from test_workspace_added import run_all

from climpact_web.core import landing
from climpact_web.jobs.models import Job, Status
from climpact_web.stations import views_add, workspace_list
from climpact_web.stations.models import Station, Workspace

pytestmark = pytest.mark.django_db

REPOSITORY = Path(__file__).resolve().parents[3]


def rows(html: str) -> list[str]:
    body = re.search(r'<table class="table table--data workspaces-table">.*?</table>', html, re.S)
    return re.findall(r'<tr data-workspace="[^"]+">.*?</tr>', body.group(0), re.S) if body else []


def test_the_header_leads_to_workspaces(client):
    html = client.get("/w/").content.decode()
    nav = re.search(r'<nav class="site-nav".*?</nav>', html, re.S).group(0)
    assert re.findall(r'href="([^"]+)"', nav) == ["/w/", "/gridded/"]
    assert re.search(r'<a href="/w/" data-nav="workspaces" aria-current="page">', nav)
    # Current under a workspace too.
    client.post("/add/sample")
    space = Workspace.objects.get()
    page = client.get(f"/w/{space.pk}/", follow=True).content.decode()
    assert '<a href="/w/" data-nav="workspaces" aria-current="true">' in page


def test_no_workspaces_yet(client):
    html = client.get("/w/").content.decode()
    assert "<h1>Workspaces</h1>" in html
    assert "You have no workspaces yet." in html and 'href="/add/"' in html
    assert "On this computer. Workspaces stay until you delete them." in html
    assert not rows(html)


@override_settings(WORKSPACE_EXPIRY=True)
def test_the_list_of_workspaces(client):
    run = finished_batch(client, "a", "b", bad=["c"])
    client.get(f"/w/{run.workspace_id}/")  # the batch's results recorded
    client.post("/add/sample")
    run_all()
    sydney = Station.objects.get(source="sample").workspace
    # Another session's workspace is not listed.
    Workspace.objects.create(owner="someone else", name="Not mine")
    # One deleted in two days.
    soon = timezone.now() - dt.timedelta(days=5, hours=1)
    Workspace.objects.filter(pk=run.workspace_id).update(updated_at=soon)

    html = client.get("/w/").content.decode()
    assert "In this browser only. Each is deleted 7 days after its last change." in html
    assert "Not mine" not in html
    found = rows(html)
    assert len(found) == 2
    first, second = found  # most recently changed first
    assert f'href="/w/{sydney.pk}/"' in first and "Sydney Observatory Hill" in first
    assert "1936–2015" in first  # one station: its years
    assert re.search(r'status-dot--(ready|usable|fix)">(Ready|Usable|Fix first)', first)
    assert '<td class="code">1971–2000</td>' in first
    assert "today " in first
    # Several stations: their names, the counts by verdict, the deletion date highlighted.
    assert "a, b and 1 more" in second
    assert '<td class="num">3</td>' in second
    assert "workspaces-table__soon" in second and "· in 2 days" in second
    assert f'href="/w/{run.workspace_id}/delete"' in second
    assert "Running Climpact on your own computer?" in html


def test_status_summary_counts_verdicts_and_failures(client):
    run = finished_batch(client, "a", "b")
    client.get(f"/w/{run.workspace_id}/")
    a = Station.objects.get(station_name="a")
    origin = dict(a.origin)
    origin["run"] = {**origin["run"], "state": "failed", "error": "no data"}
    Station.objects.filter(pk=a.pk).update(origin=origin)
    entry = workspace_list.entry(run.workspace, a.owner)
    labels = [s.label for s in entry.statuses]
    assert labels[-1] == "1 failed"
    assert entry.stations == 2 and entry.hint == "a and b"


def test_files_waiting_to_be_added_are_listed(client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    client.post("/add/", {"files": [SimpleUploadedFile("x.txt", station().encode())]})
    html = client.get("/w/").content.decode()
    (row,) = rows(html)
    assert "1 file waiting to be added" in row and '<td class="num">0</td>' in row


def test_when_and_soon_texts():
    now = timezone.make_aware(dt.datetime(2026, 11, 18, 12, 0))
    assert workspace_list.when_text(now - dt.timedelta(hours=1), now) == "today 11:00"
    assert workspace_list.when_text(now - dt.timedelta(days=1), now) == "yesterday 12:00"
    assert workspace_list.when_text(now - dt.timedelta(days=3), now) == "15 Nov"
    assert workspace_list.when_text(now - dt.timedelta(days=400), now) == "14 Oct 2025"
    assert workspace_list.soon_text(now + dt.timedelta(days=4), now) == ""
    assert workspace_list.soon_text(now + dt.timedelta(days=2), now) == "in 2 days"
    assert workspace_list.soon_text(now + dt.timedelta(hours=20), now) == "tomorrow"
    assert workspace_list.soon_text(now + dt.timedelta(hours=2), now) == "today"


def test_delete_a_workspace(client):
    run = finished_batch(client, "a", "b")
    space = run.workspace
    url = f"/w/{space.pk}/delete"
    html = client.get(url).content.decode()
    assert f"<h1>Delete {space.display_name}?</h1>" in html
    assert "This deletes its 2 stations" in html and "<li>a</li>" in html
    folders = [s.folder for s in space.stations.all()]
    assert all(f.exists() for f in folders)
    response = client.post(url)
    assert response["Location"] == "/w/"
    assert not Workspace.objects.filter(pk=space.pk).exists()
    assert not Station.objects.filter(workspace_id=space.pk).exists()
    assert not any(f.exists() for f in folders)
    assert client.get(url).status_code == 404  # gone, and so is its address


def test_delete_cancels_what_is_queued(client):
    client.post("/add/sample")
    station_ = Station.objects.get()
    queued = [j for j in (station_.qc_job, station_.indices_job) if j is not None]
    assert queued and all(j.status == Status.QUEUED for j in queued)
    client.post(f"/w/{station_.workspace_id}/delete")
    assert all(Job.objects.get(pk=j.pk).status == Status.CANCELLED for j in queued)


def test_another_sessions_workspace_cannot_be_deleted(client):
    space = Workspace.objects.create(owner="someone else")
    assert client.get(f"/w/{space.pk}/delete").status_code == 404
    assert client.post(f"/w/{space.pk}/delete").status_code == 404
    assert Workspace.objects.filter(pk=space.pk).exists()


def test_get_started_offers_the_workspaces_changed_last(client):
    html = client.get("/add/").content.decode()
    assert "Or continue a workspace" not in html  # a first visit
    for _ in range(4):
        client.post("/add/sample")
    html = client.get("/add/").content.decode()
    recent = re.search(r'aria-labelledby="recent-title">.*?</section>', html, re.S).group(0)
    assert "Or continue a workspace" in html and 'href="/w/"' in recent
    assert recent.count('<th scope="row"') == views_add.RECENT


def test_see_an_example_opens_the_samples_indices(client):
    response = client.post("/add/sample", {"show": "indices"})
    sample = Station.objects.get(source="sample")
    assert response["Location"] == sample.url("results")
    # The run is the user's at once, as "Go to indices" makes it.
    assert sample.indices_job is not None and not sample.indices_job.is_speculative
    assert client.get(response["Location"]).status_code == 200


def test_the_landing_page(client):
    html = client.get("/").content.decode()
    assert '<h1 class="landing-hero__title" id="hero-title">' in html
    assert "How have the extremes changed at your stations?" in html
    # Get started (Add stations) and See an example, a one-click POST.
    assert re.search(r'<a href="/add/"[^>]*>\s*<span>Get started</span>', html)
    assert re.search(
        r'<form method="post" action="/add/sample">.*?name="show" value="indices".*?'
        r"See an example: Sydney, 1936–2015",
        html,
        re.S,
    )
    # The preview is the sample's real output: TXx's trend and four rows.
    assert "+0.03\xa0°C/decade" in html and "−0.22 to 0.31" in html
    for code in ("SU", "TR", "TN10p", "PRCPTOT"):
        assert f'<th scope="row" class="code">{code}</th>' in html
    assert "+5.15" in html and "3.79 to 6.54" in html
    assert 'role="img" aria-label="Annual TXx from 1936 to 2015.' in html
    # The facts.
    assert ">16</dt>" in html and "14 stations from Yakutsk to Darwin, and 2 test cases" in html
    assert "of the 1,791 files written for them identical to Climpact for R 3.4.3" in html
    for title in ("How it works", "What you get", "What you need", "Try it with your own stations"):
        assert title in html
    assert "Welcome back" not in html


def test_a_returning_visitor_is_welcomed_back(client):
    client.post("/add/sample")
    space = Workspace.objects.get()
    html = client.get("/").content.decode()
    welcome = re.search(r'<div class="landing__welcome".*?</div>', html, re.S).group(0)
    assert f'Continue with <a href="/w/{space.pk}/">Sydney Observatory Hill</a>' in welcome
    assert "1 station, updated today" in welcome and 'href="/w/"' in welcome


def test_preview_rows_use_percentage_points():
    rows_ = {r["code"]: r for r in landing.preview()["rows"]}
    assert rows_["TN10p"]["units"] == "pp" and rows_["TN10p"]["pp"]
    assert rows_["SU"]["units"] == "days" and rows_["SU"]["significant"]
    assert not rows_["PRCPTOT"]["significant"]


@pytest.mark.skipif(not (REPOSITORY / "reference" / "stations.csv").exists(), reason="no reference")
def test_the_facts_match_the_reference_runs():
    with (REPOSITORY / "reference" / "stations.csv").open() as f:
        runs = list(csv.DictReader(f))
    # The test cases: the Sydney file at latitude 0 and the synthetic quality-check file.
    cases = [r for r in runs if r["run"] == "lat0" or r["source"] == "synthetic"]
    assert len(runs) == landing.REFERENCE_RUNS
    assert len(cases) == landing.REFERENCE_TEST_CASES
    names = {r["run"] for r in runs}
    assert {"yakutsk", "darwin"} <= names
    trend = next((REPOSITORY / "reference" / "output" / "sydney").glob("*/trend/*_trend.csv"))
    assert f'"Climpact_version: ","{landing.R_VERSION}"' in trend.read_text()

"""The workspace overview (#234, the Workspace and Calculate boards): a workspace of two or
more stations opens on its context bar, run status line and Stations table, live while the
stations calculate; Rename, Workspace settings with Undo, the station pages' way round the
workspace, and the page of a workspace that is not here. It replaced the batch results
page and the batch steps."""

import re
import uuid

import pytest
from test_batch import created, metadata, run_worker, station  # noqa: F401
from test_batch_workspace import finished_batch, queued_batch
from test_workspace import page

from climpact_web.jobs.models import Job, Status
from climpact_web.stations import overview
from climpact_web.stations.models import Station, Workspace

pytestmark = pytest.mark.django_db


def status_line(html: str) -> str:
    pattern = r'<div class="run-status run-status--(\w+)" role="status">(.*?)</div>\s*</div>'
    found = re.search(pattern, html, re.S)
    assert found, "no run status line"
    text = re.sub(r"<[^>]+>", " ", found.group(2))
    return found.group(1) + ": " + " ".join(text.split())


def rows(html: str) -> dict[str, str]:
    """Each station's row of the Stations table: its indices state."""
    return dict(re.findall(r'<tr data-station="([\w-]+)" data-indices="(\w+)"', html))


def test_a_workspace_of_several_stations_opens_its_overview(client):
    run = finished_batch(client, "a", "b", missing=["d"])
    space = run.workspace
    url = f"/w/{space.pk}/"
    html = client.get(url).content.decode()
    # The context bar: "Workspace", the name as the h1, the provenance line with Workspace
    # settings and Rename, Add stations, then the tabs.
    assert '<p class="m-0 text-xs text-text-muted">Workspace</p>' in html
    assert f'<h1 class="context-bar__name">{space.display_name}</h1>' in html
    provenance = html.split('class="context-bar__provenance"')[1].split("</p>")[0]
    # A batch's workspace calculates no custom index, as R's batch: one setting changed.
    for part in ("3 stations", "base 2000–2001", "1 setting not the default", "climpact "):
        assert part in provenance, part
    assert f'href="{url}settings/"' in provenance and f'href="{url}rename"' in provenance
    assert f'href="{url}add/"' in html and ">Add stations<" in html
    tabs = html.split('aria-label="Workspace sections"')[1].split("</nav>")[0]
    assert f'href="{url}" data-tab="overview" aria-current="page">Overview</a>' in tabs
    assert "Compare an index" in tabs and f'href="{url}files/" data-tab="files"' in tabs
    assert tabs.count("<a ") == 2  # Compare an index is not a link until #238
    # No batch steps, no per-station downloads, no bottom links (#234).
    assert "steps__" not in html and "What is in the zip" not in html
    assert "Start a new batch" not in html and "Change the files or options" not in html
    # The run status line, quiet once finished, and a row a station in the order added.
    assert status_line(html).startswith("done: 2 stations calculated in")
    assert "d was not run: the station file is missing." in status_line(html)
    assert "Download all (zip, " not in html and "hx-get" not in html  # Export ▾ (#239)
    assert rows(html) == {"a": "done", "b": "done", "d": "not_run"}
    assert list(rows(html)) == ["a", "b", "d"]
    # Each row: its page, coordinates, years, missing values, verdict and significance.
    a = Station.objects.get(station_name="a")
    row = html.split('data-station="a"')[1].split("</tr>")[0]
    assert f'href="{a.url()}indices"' in row and "2000–2002" in row and "0.0%" in row
    assert re.search(r"\d+ of \d+</span>", row) and "with a significant trend" in row
    d_row = html.split('data-station="d"')[1].split("</tr>")[0]
    assert ">Not run<" in d_row and "Fix the file" in d_row and "–" in d_row


def test_the_overview_is_live_while_the_stations_calculate(client):
    run = queued_batch(client, "a", "b")
    url = f"/w/{run.workspace_id}/"
    html = client.get(url).content.decode()
    assert status_line(html).startswith("running: Calculating indices: 0 of 2 stations done.")
    assert f'hx-get="{url}progress"' in html and 'data-status="running"' in html
    assert f'action="/jobs/{run.job_id}/cancel"' in html and ">Cancel</button>" in html
    assert "Rows update as each station finishes." in html
    # The fragment polled is the same block, alone.
    fragment = client.get(f"{url}progress").content.decode()
    assert fragment.lstrip().startswith('<div id="workspace-progress"')
    assert "<html" not in fragment
    run_worker()
    fragment = client.get(f"{url}progress").content.decode()
    assert 'data-status="finished"' in fragment and "hx-get" not in fragment
    assert rows(fragment) == {"a": "done", "b": "done"}


def test_a_failed_station_is_named_in_red(client):
    run = finished_batch(client, "a", bad=["c"])
    html = client.get(f"/w/{run.workspace_id}/").content.decode()
    line = status_line(html)
    assert line.startswith("failed: 1 of 2 stations calculated in") and "c failed:" in line
    assert f'href="/w/{run.workspace_id}/settings/">Workspace settings</a>' in html
    assert rows(html)["c"] == "failed"
    assert 'class="stations-table__failed"' in html and "Failed: " in html


def test_the_failed_rows_fix_is_the_base_period_when_that_is_why():
    assert overview.base_period_problem("No data in the base period 1971-2000.")
    assert not overview.base_period_problem("The rows are not in date order.")
    assert overview.not_run_reason("Not calculated: the station file is missing.\nmore") == (
        "the station file is missing."
    )


def test_old_batch_results_addresses_lead_to_the_overview(client):
    run = finished_batch(client, "a", "b")
    url = f"/w/{run.workspace_id}/"
    assert client.get(f"{url}batch/results")["Location"] == url
    assert client.get(f"/batch/{run.pk}/results")["Location"] == url
    assert client.get(f"{url}batch/progress").status_code == 404


def test_a_one_station_workspace_never_shows_the_overview(client):
    run = finished_batch(client, "a")
    a = Station.objects.get()
    assert client.get(f"/w/{run.workspace_id}/")["Location"] == a.url("results")
    # Its pages offer Add stations instead, and no breadcrumb.
    html = page(client, a)
    assert f'<a class="context-bar__add" href="/w/{run.workspace_id}/add/">Add stations</a>' in html
    assert "context-bar__breadcrumb" not in html


def test_station_pages_lead_round_the_workspace(client):
    run = finished_batch(client, "a", "b", "c")
    a, b, c = (Station.objects.get(station_name=n) for n in "abc")
    for path in ("indices", "quality", "downloads"):
        html = page(client, b, path)
        crumbs = re.findall(r'<ol class="context-bar__breadcrumb">(.*?)</ol>', html, re.S)[0]
        assert f'href="/w/{run.workspace_id}/">{run.workspace.display_name}</a>' in crumbs
        assert "Station 2 of 3" in crumbs
        assert f'href="{a.url()}indices" rel="prev"' in html, path
        assert f'href="{c.url()}indices" rel="next"' in html, path
        assert "context-bar__add" not in html
    first = page(client, a)
    assert 'rel="prev"' not in first and 'rel="next"' in first


def test_rename_the_workspace(client):
    run = finished_batch(client, "a", "b")
    url = f"/w/{run.workspace_id}/"
    html = client.get(f"{url}rename").content.decode()
    assert 'name="name"' in html and "2 stations, " in html
    response = client.post(f"{url}rename", {"name": "  NSW coast "})
    assert response["Location"] == url
    assert Workspace.objects.get().name == "NSW coast"
    assert '<h1 class="context-bar__name">NSW coast</h1>' in client.get(url).content.decode()
    # The breadcrumb of its stations follows.
    a = Station.objects.get(station_name="a")
    assert f'href="{url}">NSW coast</a>' in page(client, a)
    # Empty: the default name again.
    client.post(f"{url}rename", {"name": ""})
    assert Workspace.objects.get().display_name.startswith("2 stations, ")
    assert client.post(f"{url}rename", {"name": "x" * 101}).status_code == 200


def test_workspace_settings_change_every_station_and_can_be_undone(client):
    run = finished_batch(client, "a", "b")
    url = f"/w/{run.workspace_id}/"
    html = client.get(f"{url}settings/").content.decode()
    for key in ("base-period", "thresholds", "settings"):
        assert f'href="{url}settings/{key}"' in html
    assert "2000–2001" in html
    html = client.get(f"{url}settings/base-period").content.decode()
    assert f'action="{url}settings/base-period"' in html and 'name="base_start"' in html
    assert "It applies to all 2 stations of this workspace." in html
    assert client.get(f"{url}settings/nope").status_code == 404
    # An error stays on the page.
    bad = client.post(f"{url}settings/base-period", {"base_start": "2001", "base_end": "2000"})
    assert bad.status_code == 200 and "The last year must not be before the first year." in (
        bad.content.decode()
    )
    response = client.post(f"{url}settings/base-period", {"base_start": "2000", "base_end": "2000"})
    assert response["Location"] == url
    space = Workspace.objects.get()
    assert (space.base_start, space.base_end) == (2000, 2000)
    for s in space.stations.all():
        assert s.indices_job is not None and s.indices_job.status == Status.QUEUED
    # The overview shows the recalculation, with Undo on the run status line.
    html = client.get(url).content.decode()
    assert status_line(html).startswith("running: Calculating indices: 0 of 2 stations done.")
    assert f'action="{url}undo"' in html and "Undo the change" in html
    client.post(f"{url}undo")
    space.refresh_from_db()
    assert (space.base_start, space.base_end) == (2000, 2001)
    assert not Job.objects.filter(status=Status.QUEUED, cancel_requested=False).exists()
    html = client.get(url).content.decode()
    assert status_line(html).startswith("done: 2 stations calculated")
    # The thresholds and index settings apply the same way.
    client.post(f"{url}settings/thresholds", {**_qc_defaults(), "iqr_temp": "4"})
    assert Workspace.objects.get().qc_params["iqr_temp"] == 4
    assert "2 settings not the default" in client.get(url).content.decode()


def _qc_defaults() -> dict:
    from climpact_web.stations.forms import QCParamsForm

    return {k: str(v) for k, v in QCParamsForm.initial_for({}).items()}


def test_a_workspace_that_is_not_here_says_why(client):
    html = client.get(f"/w/{uuid.uuid4()}/").content.decode()
    assert "This workspace is not here" in html and 'href="/add/"' in html
    assert "There is no page at this address." not in html
    other = client.get("/no-such-page/").content.decode()
    assert "There is no page at this address." in other

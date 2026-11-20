"""The workspace's Files (#239, the Files board): the files that span its stations
(Everything, Trends and Indices of all stations), each station's R files in one table,
``climpact_run.json`` in every zip with "Copy methods text", and how long the files are
kept; Export ▾ on the overview."""

import csv
import io
import json
import math
import zipfile

import pytest
from test_batch import created, media, metadata, run_batch, run_worker, station  # noqa: F401
from test_batch_workspace import OPTIONS, finished_batch, queued_batch
from test_downloads import complete
from test_indices_results import STATION, finished_analysis

from climpact_web.jobs.models import Status
from climpact_web.stations import workspace_files as model
from climpact_web.stations.models import RESERVED_SLUGS, Station, Workspace

pytestmark = pytest.mark.django_db


def long_batch(client, *names, bad=()):
    """A batch of 12-year stations, long enough for annual trends (10 values or more)."""
    files = {f"{n}.txt": station(days=4400, seed=k) for k, n in enumerate([*names, *bad])}
    run = run_batch(client, created(client, metadata(*files), **files), OPTIONS)
    for n in bad:
        (run.job.input_dir / "stations" / f"{n}.txt").write_text(
            "2000 1 1 0 20 10\n1999 1 1 0 20 10\n"
        )
    job = run_worker()
    assert job.status == Status.SUCCEEDED, job.error
    run.refresh_from_db()
    return run


def get(client, url) -> bytes:
    response = client.get(url)
    assert response.status_code == 200, url
    return b"".join(response.streaming_content)


def rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def test_the_files_tab_shows_the_workspace_files_and_each_stations(client):
    run = finished_batch(client, "a", "b", bad=["c"])
    space = run.workspace
    url = f"/w/{space.pk}/files/"
    # The tab is a link now, on the overview too.
    overview = client.get(f"/w/{space.pk}/").content.decode()
    tabs = overview.split('aria-label="Workspace sections"')[1].split("</nav>")[0]
    assert f'href="{url}" data-tab="files">Files</a>' in tabs
    html = client.get(url).content.decode()
    tabs = html.split('aria-label="Workspace sections"')[1].split("</nav>")[0]
    assert f'href="{url}" data-tab="files" aria-current="page">Files</a>' in tabs
    # The three workspace files, each with its size and its link.
    for title, link in (
        ("Everything", "everything.zip"),
        ("Trends, all stations", "trends.csv"),
        ("Indices, all stations", "indices.csv"),
    ):
        assert f'<h3 class="m-0 text-base">{title}</h3>' in html
        assert f'href="{url}{link}" download>Download<' in html
    assert "zip · " in html and "csv · " in html
    columns = "station, index, slope, lower, upper, significant, years_used, units, out_of_date"
    assert columns in html
    assert "station, index, year, month, value (long format)" in html
    assert "What is in the zip" in html
    # By station: a row a station in the overview's order, R's files or why they are not.
    table = html.split('class="table table--data"')[1].split("</table>")[0]
    for column in (
        "Folder (zip)",
        "Report (PDF)",
        "All plots (PDF)",
        "Trends",
        "Thresholds",
        "Missing values",
        "Quality flags",
    ):
        assert f'<th scope="col">{column}</th>' in table
    a = table.split('data-station="a"')[1].split("</tr>")[0]
    assert f'href="/w/{space.pk}/a/zip"' in a and "_trend.csv" in a and "_thres.csv" in a
    # No report nor plots in this run (OPTIONS): "–", said as "none".
    assert '<span class="text-text-muted">–</span><span class="sr-only">none</span>' in a
    c = table.split('data-station="c"')[1].split("</tr>")[0]
    assert c.count(">failed<") == 5  # not run: test_batch_workspace.py
    # The provenance file, the methods text and how long the files are kept.
    assert "climpact_run.json</span> into every zip" in html
    assert "&quot;base_period&quot;: [\n    2000,\n    2001\n  ]" in html
    assert "Copy methods text" in html and "data-copy-text" in html
    assert "Climate indices for 2 stations were calculated with climpact " in html
    assert "Keeping the files" in html and "provenance file lets you rerun" in html


def test_keeping_the_files_says_when_they_are_deleted(client, settings):
    settings.WORKSPACE_EXPIRY = True
    run = finished_batch(client, "a", "b")
    html = client.get(f"/w/{run.workspace_id}/files/").content.decode()
    date = run.workspace.expires_at.strftime("%-d %b %Y")
    assert f"Input files and results are deleted on <b>{date}</b>." in html


def test_keep_7_more_days_moves_the_deletion_date(client, settings):
    """Keep 7 more days (#274): the workspace counts as changed now, so the panel and the
    context bar's "kept until" move to JOB_RETENTION_DAYS from now."""
    import datetime as dt

    from django.utils import timezone

    settings.WORKSPACE_EXPIRY = True
    run = finished_batch(client, "a", "b")
    space = run.workspace
    url = f"/w/{space.pk}/files/"
    html = client.get(url).content.decode()
    keep = f'<form method="post" action="/w/{space.pk}/keep">'
    assert keep in html and '<button type="submit" class="link-button">Keep 7 more days' in html
    assert f'href="/w/{space.pk}/delete?from=files">Delete workspace now</a>' in html
    # Five days on, it is deleted in two; Keep makes it seven again.
    Workspace.objects.filter(pk=space.pk).update(updated_at=timezone.now() - dt.timedelta(days=5))
    assert client.get(f"/w/{space.pk}/keep").status_code == 405  # a POST only
    response = client.post(f"/w/{space.pk}/keep")
    assert response["Location"] == url
    space.refresh_from_db()
    assert abs(space.expires_at - (timezone.now() + dt.timedelta(days=7))) < dt.timedelta(minutes=1)
    date = timezone.localtime(space.expires_at).strftime("%-d %b %Y")
    html = client.get(url).content.decode()
    assert f"{space.display_name} is now kept until {date}." in html
    assert f"Input files and results are deleted on <b>{date}</b>." in html
    assert f"kept until {date}" in html.split('aria-label="Workspace sections"')[0]


def test_local_installs_have_no_keep_but_delete_stays(client):
    run = finished_batch(client, "a", "b")
    space = run.workspace
    html = client.get(f"/w/{space.pk}/files/").content.decode()
    assert "Keep 7 more days" not in html and "/keep" not in html
    assert f'href="/w/{space.pk}/delete?from=files">Delete workspace now</a>' in html
    assert client.post(f"/w/{space.pk}/keep").status_code == 404


def test_another_sessions_workspace_cannot_be_kept(client, settings):
    settings.WORKSPACE_EXPIRY = True
    space = Workspace.objects.create(owner="someone else")
    before = space.updated_at
    assert client.post(f"/w/{space.pk}/keep").status_code == 404
    space.refresh_from_db()
    assert space.updated_at == before


def test_delete_from_files_cancels_back_to_files(client):
    """Delete workspace now (#274) is the Workspaces list's confirmation; its Cancel goes
    back to Files, and the POST deletes the workspace and goes to Workspaces."""
    run = finished_batch(client, "a", "b")
    space = run.workspace
    html = client.get(f"/w/{space.pk}/delete?from=files").content.decode()
    assert f"<h1>Delete {space.display_name}?</h1>" in html
    assert f'href="/w/{space.pk}/files/"' in html and ">Cancel<" in html
    html = client.get(f"/w/{space.pk}/delete").content.decode()
    assert f'href="/w/{space.pk}/files/"' not in html  # from Workspaces: back there
    response = client.post(f"/w/{space.pk}/delete?from=files")
    assert response["Location"] == "/w/"
    assert not Workspace.objects.filter(pk=space.pk).exists()


def test_every_zip_holds_the_provenance_file(client):
    run = finished_batch(client, "a", "b", bad=["c"])
    space = run.workspace
    data = get(client, f"/w/{space.pk}/files/everything.zip")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        record = json.loads(archive.read(model.PROVENANCE_FILE))
        trends = archive.read(model.TRENDS_FILE).decode()
    # Each station's folder in R's layout, the failed one's error file, the workspace files.
    assert "a/indices/a_txx_ANN.csv" in names and "b/trend/b_trend.csv" in names
    assert "a/qc/a_nastatistics.csv" in names and "c.errors.txt" in names
    assert not any(n.startswith("c/") for n in names)
    assert {model.TRENDS_FILE, model.INDICES_FILE} <= set(names)
    assert trends.startswith(
        "station,index,slope,lower,upper,significant,years_used,units,out_of_date\n"
    )
    # The provenance: software, created, base period, settings, trend method, stations.
    assert record["software"].startswith("climpact ") and "Climpact 3.4.3" in record["software"]
    assert record["created"].endswith("Z") and record["base_period"] == [2000, 2001]
    assert record["index_settings"] == "1 setting not the default"
    assert "quality_thresholds" in record["settings"] and "indices" in record["settings"]
    assert record["trend"].startswith("Sen's slope per decade, 95% interval (zyp)")
    by_name = {s["name"]: s for s in record["stations"]}
    a = Station.objects.get(station_name="a")
    assert by_name["a"]["file"] == "a.txt" and by_name["a"]["sha256"] == a.file_hash
    assert (by_name["a"]["lat"], by_name["a"]["lon"]) == (-30, 150)
    assert by_name["a"]["folder"] == "a" and by_name["c"]["results"] == "none (failed)"
    # A station's own zip: R's station zip (entries relative to its folder) and its record.
    data = get(client, f"/w/{space.pk}/a/zip")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        one = json.loads(archive.read(model.PROVENANCE_FILE))
    assert "indices/a_txx_ANN.csv" in names and model.PROVENANCE_FILE in names
    assert [s["name"] for s in one["stations"]] == ["a"]


def test_a_stations_zip_is_rs_with_the_provenance_file_added(client):
    """A run that wrote R's zip: the station's Files and Indices offer it with
    ``climpact_run.json`` added, its other entries unchanged."""
    analysis, job = finished_analysis(client)
    complete(job)
    url = f"{analysis.url()}zip"
    for page in ("downloads", "indices"):
        assert f'href="{url}"' in client.get(f"{analysis.url()}{page}").content.decode(), page
    response = client.get(url)
    assert response["Content-Disposition"].endswith(f'filename="{STATION}.zip"')
    data = b"".join(response.streaming_content)
    with zipfile.ZipFile(job.output_dir / f"{STATION}.zip") as original:
        r_names = original.namelist()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.namelist() == [*r_names, model.PROVENANCE_FILE]
        record = json.loads(archive.read(model.PROVENANCE_FILE))
    assert record["stations"][0]["sha256"] == analysis.file_hash
    # A workspace of one station has no Files of its own: its station's Files.
    assert client.get(f"/w/{analysis.workspace_id}/files/")["Location"] == (
        f"{analysis.url()}downloads"
    )


def test_the_all_station_csvs_agree_with_the_station_files(client):
    run = long_batch(client, "a", "b")
    space = run.workspace
    trends = rows(get(client, f"/w/{space.pk}/files/trends.csv").decode())
    indices = rows(get(client, f"/w/{space.pk}/files/indices.csv").decode())
    folder = run.job.output_dir / run.job.result["folder"]
    for name in ("a", "b"):
        # Trends: R's trend file's annual slope and bounds, per decade.
        mine = {r["index"]: r for r in trends if r["station"] == name}
        assert mine["TXx"]["units"] == "°C/decade" and mine["TXx"]["years_used"] == "12"
        assert mine["TXx"]["out_of_date"] == "no"
        assert mine["TXx"]["out_of_date"] == "no"
        lines = (folder / name / "trend" / f"{name}_trend.csv").read_text().splitlines()
        header = lines.index("Index,Frequency,StartYear,EndYear,Lower bound,Slope,Upper bound")
        checked = 0
        for line in lines[header + 1 :]:
            index, frequency, _start, _end, lower, slope, upper = line.split(",")
            code = {"txx": "TXx", "su": "SU", "prcptot": "PRCPTOT", "tnn": "TNn"}.get(index)
            if frequency != "annual" or code is None or slope == "NA":
                continue
            row = mine[code]
            assert float(row["slope"]) == pytest.approx(10 * float(slope), abs=1e-9)
            assert float(row["lower"]) == pytest.approx(10 * float(lower), abs=1e-9)
            assert float(row["upper"]) == pytest.approx(10 * float(upper), abs=1e-9)
            significant = float(lower) > 0 or float(upper) < 0
            assert row["significant"] == ("yes" if significant else "no")
            checked += 1
        assert checked == 4, name
        # Indices: every value of the station's yearly and monthly tables.
        for table, step in (("txx_ANN", "year"), ("txx_MON", "month"), ("su_ANN", "year")):
            text = (folder / name / "indices" / f"{name}_{table}.csv").read_text()
            lines = text.splitlines()
            body = lines[next(i for i, line in enumerate(lines) if line.startswith("time")) + 1 :]
            code = "TXx" if table.startswith("txx") else "SU"
            want = []
            for line in body:
                time, value = (p.strip() for p in line.split(",")[:2])
                year, _, month = time.partition("-")
                want.append((year, str(int(month)) if month else "", value))
            got = [
                (r["year"], r["month"], r["value"])
                for r in indices
                if r["station"] == name
                and r["index"] == code
                and bool(r["month"]) == (step == "month")
            ]
            assert len(got) == len(want), table
            for (gy, gm, gv), (wy, wm, wv) in zip(got, want, strict=True):
                assert (gy, gm) == (wy, wm)
                if wv in ("NA", "-99.9"):
                    assert gv == ""
                else:
                    assert math.isclose(float(gv), float(wv), rel_tol=1e-12)


def test_the_files_wait_for_the_stations_and_are_made_again_after_a_change(client):
    run = queued_batch(client, "a", "b")
    space = run.workspace
    url = f"/w/{space.pk}/files/"
    html = client.get(url).content.decode()
    assert "The workspace files are made once every station has been calculated" in html
    assert "everything.zip" not in html and "Written when the workspace files are made." in html
    assert client.get(f"{url}everything.zip")["Location"] == url  # Files says why
    # Export ▾ on the overview says so too.
    overview = client.get(f"/w/{space.pk}/").content.decode()
    assert "The files are made once every station has finished." in overview
    run_worker()
    client.get(url)
    folders = list(model.files_dir(space).iterdir())
    assert len(folders) == 1
    first = folders[0].name
    # Renamed: made again (the name is in the provenance file), the old ones deleted.
    client.post(f"/w/{space.pk}/rename", {"name": "NSW coast"})
    html = client.get(url).content.decode()
    assert [f.name for f in model.files_dir(space).iterdir()] != [first]
    assert len(list(model.files_dir(space).iterdir())) == 1
    assert "&quot;workspace&quot;: &quot;NSW coast&quot;" in html
    response = client.get(f"{url}trends.csv")
    assert response["Content-Disposition"].endswith('filename="nsw_coast_trends.csv"')
    # Deleted with the workspace.
    Workspace.objects.get(pk=space.pk).delete_files()
    assert not model.files_dir(space).exists()


def test_export_is_on_the_overview_and_download_all_moved_to_it(client):
    run = finished_batch(client, "a", "b")
    space = run.workspace
    html = client.get(f"/w/{space.pk}/").content.decode()
    menu = html.split('<details class="pop__details" data-menu>')[1].split("</details>")[0]
    assert ">Export<" in menu
    for link in ("everything.zip", "trends.csv", "indices.csv"):
        assert f'href="/w/{space.pk}/files/{link}" download' in menu
    assert f'href="/w/{space.pk}/files/">All files</a>' in menu
    # The run status line no longer offers the batch's zip: Export and Files do.
    assert "Download all (zip" not in html
    # Not on the workspace's settings pages.
    settings_page = client.get(f"/w/{space.pk}/settings/").content.decode()
    assert "data-menu" not in settings_page


def test_files_is_not_a_station_slug():
    assert {"files", "delete", "keep"} <= RESERVED_SLUGS

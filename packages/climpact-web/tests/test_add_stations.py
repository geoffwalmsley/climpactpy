"""Add stations (#233): the one way into a workspace. One file or many, a metadata file
and a zip; the review table with every problem found in one pass; the names, latitudes
and longitudes typed in it (and checked as they are typed); one station added and checked
with its own jobs, several as a batch that fills the workspace; the settings before
anything is calculated; New station and the batch's first page leading here."""

import io
import re
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from test_batch import HEADER, media, run_worker, station  # noqa: F401

from climpact_web.batch.models import BatchRun
from climpact_web.jobs.models import Job, Status
from climpact_web.stations import add_stations, workspace
from climpact_web.stations.add_stations import tidy_name
from climpact_web.stations.models import Source, Station, Step, Workspace

pytestmark = pytest.mark.django_db


def meta_line(name, lat="-30", lon="150", params="1\t1\t18\t18\t10\t3\t30\t2\t24") -> str:
    return f"{name}\t{lat}\t{lon}\t{params}\n"


def uploads(**named) -> list:
    return [
        SimpleUploadedFile(n.replace("__", "."), t.encode() if isinstance(t, str) else t)
        for n, t in named.items()
    ]


def stage(client, url="/add/", **named) -> BatchRun:
    """Drop files on Add stations; the files wait for review."""
    response = client.post(url, {"files": uploads(**named)})
    assert response.status_code == 302, response.content.decode()[:3000]
    _, _, space, _, run, _ = response["Location"].split("/")  # /w/<id>/add/<run>/
    return BatchRun.objects.get(pk=run, workspace=space)


def review_url(run) -> str:
    return f"/w/{run.workspace_id}/add/{run.pk}/"


def row_of(html, file_name) -> str:
    return re.search(rf'<tr [^>]*data-add-row="{re.escape(file_name)}".*?</tr>', html, re.S)[0]


LONG = "a_station_with_a_very_long_file_name_from_the_national_archive_1910_2015.txt"


def zipped(**named) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in named.items():
            archive.writestr(name.replace("__", "."), text)
    return buffer.getvalue()


# ---- names --------------------------------------------------------------------------------


def test_a_station_name_starts_from_the_tidied_file_name():
    assert tidy_name("moruya_heads_069018.txt") == "Moruya Heads 069018"
    assert tidy_name("sydney_observatory_hill_1936-2015.txt") == "Sydney Observatory Hill"
    assert tidy_name("other_place_1936-2015.txt") == "Other Place"
    assert tidy_name("BEGA AWS.csv") == "BEGA AWS"
    assert tidy_name("1950-2000.txt") == "1950-2000"  # nothing left without the years


# ---- the ways in --------------------------------------------------------------------------


def test_new_station_and_the_batch_page_lead_here(client):
    for old in ("/station/new", "/station/", "/batch/", "/station/sample", "/batch/sample"):
        response = client.get(old)
        assert response.status_code == 302 and response["Location"] in ("/add/", "/batch/")
    assert client.get("/batch/")["Location"] == "/add/"
    assert client.get("/station/new")["Location"] == "/add/"


def test_starting_a_workspace_works_without_javascript(client):
    html = client.get("/add/").content.decode()
    assert "<h1>Start a workspace</h1>" in html
    form = re.search(r'<form method="post" action="/add/".*?</form>', html, re.S)[0]
    assert 'enctype="multipart/form-data"' in form
    assert 'type="file" name="files" multiple' in form
    assert 'value="files"' in form and "Add the files" in form  # sent without JS
    assert "Use the sample station" in html and 'action="/add/sample"' in html
    assert 'Base period <span class="code">1971–2000</span>' in html
    # Nothing is made until files come.
    assert not Workspace.objects.exists()
    response = client.post("/add/", {"intent": "files"})
    assert response.status_code == 400 and "Choose the station files." in response.content.decode()
    assert not Workspace.objects.exists()


def test_the_sample_station_opens_its_quality_at_once(client):
    response = client.post("/add/sample")
    analysis = Station.objects.get()
    assert response["Location"] == analysis.url("qc")
    assert analysis.station_name == "Sydney Observatory Hill"  # #219
    assert (analysis.latitude, analysis.longitude) == (-33.86, 151.21)
    assert analysis.source == Source.SAMPLE and analysis.reached(Step.QC)
    assert analysis.qc_job is not None and analysis.indices_job is not None
    assert analysis.indices_job.is_speculative
    assert analysis.workspace.display_name == "Sydney Observatory Hill"


# ---- the review ---------------------------------------------------------------------------


def test_every_problem_in_a_set_of_files_is_found_in_one_pass(client):
    repeated = station(days=800) + "2001 1 1 0 20 10\n2001 1 1 0 21 10\n"
    run = stage(
        client,
        stations__txt=HEADER
        + meta_line("moruya_heads_069018.txt", "-35.91", "150.15")
        + meta_line("port_macquarie.txt", "-31.43", "152.87", "4\t1\t18\t18\t10\t3\t30\t2\t24")
        + meta_line("gone.txt")
        + meta_line("bega.txt")
        + meta_line("inzip.txt")
        + meta_line(LONG),
        moruya_heads_069018__txt=station(seed=1),
        port_macquarie__txt=station(seed=2),
        coffs_harbour__txt=station(seed=3),
        bega__txt=repeated,
        taree_airport__csv="2000 1 1 0\n2000 1 2 0\n",
        **{LONG: station()},
        more__zip=zipped(inzip__txt=station(seed=4)),
    )
    html = client.get(review_url(run)).content.decode()
    assert "<h1>Add stations</h1>" in html
    assert "6 files read" in html and "metadata from stations.txt" in html  # gone.txt: no file
    moruya = row_of(html, "moruya_heads_069018.txt")
    assert 'value="Moruya Heads 069018"' in moruya and 'value="-35.91"' in moruya
    assert "Read · under a year in the base period" in moruya and "Defaults" in moruya
    assert "1990" not in moruya and "2000–2002" in moruya and ">800<" in moruya
    port = row_of(html, "port_macquarie.txt")
    assert "Custom (wsdin 4)" in port
    coffs = row_of(html, "coffs_harbour.txt")
    assert "Latitude and longitude needed" in coffs and 'aria-invalid="true"' in coffs
    assert "is-problem" in coffs
    bega = row_of(html, "bega.txt")
    assert "Read · 1 repeated date; checks will list it" in bega and "is-problem" not in bega
    taree = row_of(html, "taree_airport.csv")
    assert "Not read: line 1 has 4 values, expected 6 (year month day PR TX TN)" in taree
    assert "(and 1 more)" in taree and "<input" not in taree
    assert "Not added: the metadata names this file" in row_of(html, "gone.txt")
    assert 'value="Inzip"' in row_of(html, "inzip.txt")
    long_row = row_of(html, LONG)
    assert 'title="a_station_with_a_very_long_file_name' in long_row
    # The line under the table names every problem, and the button counts the rest.
    assert "3 problems to fix before these stations can be added" in html
    assert "a missing latitude and longitude" in html and "an unreadable file" in html
    assert "a missing file" in html
    assert "Add 5 stations and check them" in html
    # Every problem with its line, in one disclosure.
    assert "Every problem and warning, with its line in the file" in html
    assert "<code>2000 1 2 0</code>" in html


def test_the_table_is_checked_as_it_is_typed_and_keeps_what_was_typed(client):
    run = stage(client, a__txt=station(), b__txt=station(seed=1))
    data = {"file-0": "a.txt", "name-0": "Alpha", "lat-0": "−35,5", "lon-0": "150"}
    data |= {"file-1": "b.txt", "name-1": "Alpha", "lat-1": "100", "lon-1": ""}
    result = client.post(review_url(run) + "check", data).json()
    rows = {r["file"]: r for r in result["rows"]}
    # Both are named Alpha: neither can be added until one is renamed.
    assert rows["a.txt"]["state"] == "needs" and rows["a.txt"]["name_error"]
    assert rows["b.txt"]["status"] == "Two files have this station name"
    assert result["count"] == 0 and result["button"] == "Add 0 stations and check them"
    data["name-1"] = "Beta"
    result = client.post(review_url(run) + "check", data).json()
    rows = {r["file"]: r for r in result["rows"]}
    assert rows["a.txt"]["state"] == "ready"  # U+2212 and a decimal comma are read
    assert rows["b.txt"]["latitude_error"] == "Latitude must be between -90 and 90."
    assert result["button"] == "Add 1 station and check it"
    assert (
        "1 problem to fix" in result["summary"]
        and "The others can be added now." in result["summary"]
    )
    # What was typed is kept: the page shows it.
    html = client.get(review_url(run)).content.decode()
    assert 'value="Beta"' in row_of(html, "b.txt") and 'value="100"' in row_of(html, "b.txt")
    # Another session sees nothing.
    from django.test import Client

    assert Client().post(review_url(run) + "check", data).status_code == 404


def test_more_files_keep_what_was_typed(client):
    run = stage(client, a__txt=station())
    response = client.post(
        review_url(run),
        {
            "intent": "files",
            "file-0": "a.txt",
            "name-0": "Alpha",
            "lat-0": "-30",
            "lon-0": "",
            "files": uploads(b__txt=station(seed=1)),
        },
    )
    assert response["Location"] == review_url(run)
    html = client.get(review_url(run)).content.decode()
    assert 'value="Alpha"' in row_of(html, "a.txt") and 'value="-30"' in row_of(html, "a.txt")
    assert 'value="B"' in row_of(html, "b.txt")
    assert "2 files read" in html


def test_cancel_deletes_the_files_and_a_workspace_with_nothing_else(client):
    run = stage(client, a__txt=station())
    folder = run.folder
    assert folder.is_dir()
    assert client.post(review_url(run), {"intent": "cancel"})["Location"] == "/add/"
    assert not Workspace.objects.exists() and not folder.exists()


def test_nothing_is_added_until_a_row_is_complete(client):
    run = stage(client, a__txt=station())
    response = client.post(review_url(run), {"intent": "add", "file-0": "a.txt", "name-0": "A"})
    assert response.status_code == 400
    assert "Nothing can be added yet." in response.content.decode()
    assert not Station.objects.exists()


# ---- adding -------------------------------------------------------------------------------


def test_one_station_is_added_and_checked_with_its_own_jobs(client):
    run = stage(client, my_place_1950_2000__txt=station())
    data = {"intent": "add", "file-0": "my_place_1950_2000.txt", "name-0": "My Place"}
    data |= {"lat-0": "-33.9", "lon-0": "151.2"}
    response = client.post(review_url(run), data)
    analysis = Station.objects.get()
    assert response["Location"] == analysis.url("qc")
    assert analysis.station_name == "My Place" and analysis.file_name == "my_place_1950_2000.txt"
    assert (analysis.latitude, analysis.longitude) == (-33.9, 151.2)
    assert analysis.qc_job.kind == "qc" and analysis.indices_job.is_speculative
    assert workspace.set_up(analysis) and not analysis.origin
    # The files that waited are gone; the workspace stays, with the station.
    assert not BatchRun.objects.exists()
    assert analysis.workspace.display_name == "My Place"


def test_the_settings_change_before_anything_is_calculated(client):
    run = stage(client, a__txt=station())
    html = client.get(review_url(run)).content.decode()
    assert "Applies to every station" in html and "Change workspace settings" in html
    assert 'form="add-form"' in html
    data = {"intent": "settings", "base_start": "2000", "base_end": "2001", "workers": "1"}
    assert client.post(review_url(run), data)["Location"] == review_url(run)
    space = Workspace.objects.get()
    assert (space.base_start, space.base_end) == (2000, 2001)
    assert space.index_settings["plots"] is False  # the box was not ticked
    html = client.get(review_url(run)).content.decode()
    assert "2000–2001" in html and ">Off<" in html
    # A base period the data do not reach blocks the station, with why.
    data["base_start"], data["base_end"] = "1971", "1980"
    client.post(review_url(run), data)
    html = client.get(review_url(run)).content.decode()
    assert "has no data: the file covers 2000 to 2002" in row_of(html, "a.txt")
    assert "a file outside the base period" in html


def test_several_stations_fill_the_workspace_as_a_batch(client):
    meta = HEADER + meta_line("a.txt", "-30", "150", "4\t1\t18\t18\t10\t3\t30\t2\t24")
    meta += meta_line("b.txt", "-31", "151")
    run = stage(client, meta__txt=meta, a__txt=station(seed=1), b__txt=station(seed=2))
    client.post(
        review_url(run),
        {"intent": "settings", "base_start": "2000", "base_end": "2001", "workers": "1"},
    )
    data = {"intent": "add", "file-0": "a.txt", "name-0": "Alpha Hill"}
    data |= {"file-1": "b.txt", "name-1": "Beta"}
    response = client.post(review_url(run), data)
    space = Workspace.objects.get()
    assert response["Location"] == f"/w/{space.pk}/"
    run.refresh_from_db()
    job = run.job
    assert job.kind == "batch" and job.params["names"] == {"a": "Alpha Hill", "b": "Beta"}
    assert (job.params["base_start"], job.params["base_end"]) == (2000, 2001)
    stations = {s.station_name: s for s in space.stations.all()}
    assert set(stations) == {"Alpha Hill", "Beta"}
    alpha = stations["Alpha Hill"]
    assert alpha.origin["station"] == "a" and alpha.origin["run"]["state"] == "waiting"
    assert alpha.origin["params"] == {
        "wsdi_days": 4,
        "csdi_days": 1,
        "hdd_base": 18.0,
        "cdd_base": 18.0,
        "gdd_base": 10.0,
        "rx_days": 3,
        "rnnmm": 30.0,
        "txtn_days": 2,
        "spei_months": 24,
    }
    # Each station's quality checks are queued beside the batch, as one change.
    assert alpha.qc_job is not None and stations["Beta"].qc_job is not None
    assert alpha.qc_job.params["change"] == job.params["change"]
    # The batch runs; its results are each station's, current with the name given.
    run_worker()
    job.refresh_from_db()
    assert job.status == Status.SUCCEEDED, job.error
    assert client.get(f"/w/{space.pk}/").status_code == 200
    alpha.refresh_from_db()
    assert alpha.origin["run"]["state"] == "done"
    assert not workspace.run_changes(alpha, workspace.shown_run(alpha))
    assert space.display_name.startswith("2 stations, ")


def test_stations_are_added_to_an_existing_workspace(client):
    client.post("/add/sample")
    space = Workspace.objects.get()
    html = client.get(f"/w/{space.pk}/add/").content.decode()
    assert f'<a href="/w/{space.pk}/">Sydney Observatory Hill</a>' in html
    assert "Change them from a station's Inputs" in html  # the settings are in use
    run = stage(client, url=f"/w/{space.pk}/add/", b__txt=station(seed=1))
    assert run.workspace == space
    data = {"intent": "add", "file-0": "b.txt", "name-0": "B", "lat-0": "-30", "lon-0": "150"}
    data |= {"base_start": "1990"}  # not offered: the workspace has stations
    response = client.post(review_url(run), data)
    assert response["Location"] == f"/w/{space.pk}/"
    space.refresh_from_db()
    assert space.stations.count() == 2 and space.base_start == 1971
    assert Job.objects.filter(kind="qc").count() == 2


def test_the_sample_batch_waits_for_review(client):
    response = client.post("/add/sample-batch")
    run = BatchRun.objects.get()
    assert response["Location"] == review_url(run)
    html = client.get(review_url(run)).content.decode()
    assert "metadata from climpact.sample.batch.metadata.txt" in html
    assert 'value="Sydney Observatory Hill"' in html
    assert "Add 2 stations and check them" in html


def test_files_waiting_open_from_the_workspace_address(client):
    run = stage(client, a__txt=station())
    assert client.get(f"/w/{run.workspace_id}/")["Location"] == review_url(run)
    assert client.get(f"/w/{run.workspace_id}/batch/")["Location"] == review_url(run)


def test_a_station_cannot_take_the_slug_add():
    from climpact_web.stations.models import slug_for

    assert slug_for("Add", set()) == "add-2"


def test_the_sample_constants_match_the_station_pages():
    from climpact_web.stations.views import SAMPLE_NAME

    assert add_stations.SAMPLE_FILE == SAMPLE_NAME

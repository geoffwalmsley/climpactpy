"""The batch (#80): zips, the pre-flight check and its messages, the options, one job for
the ready stations with per-station progress, the results (errors, downloads, a station
failing alone), ownership and retention. Add stations (#233, ``test_add_stations.py``)
makes and queues a batch since the batch's own pages went (#271); the batches here are
made at model level (``made.py``), with stations the check leaves out. Its stations in
its workspace (#255) are ``test_batch_workspace.py``'s."""

import datetime as dt
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

import made
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from climpact_web.batch import check
from climpact_web.batch.fill import plain_error
from climpact_web.batch.forms import OptionsForm
from climpact_web.batch.models import BatchRun, batches_dir
from climpact_web.batch.views import sample_files
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.retention import purge_expired
from climpact_web.jobs.views import OWNER_KEY
from climpact_web.jobs.worker import claim, run_job
from climpact_web.stations.models import Workspace
from climpact_web.stations.views_add import default_workers

REPO = Path(__file__).resolve().parents[3]
R_SAMPLE = REPO / "packages" / "climpact" / "tests" / "data" / "climpact.sample.batch.metadata.txt"
HEADER = "\t".join(check.COLUMNS) + "\n"


def row(name, lat="-30", lon="150", params="3\t3\t18\t18\t10\t3\t30\t2\t24") -> str:
    return f"{name}\t{lat}\t{lon}\t{params}\n"


def metadata(*names) -> str:
    return HEADER + "".join(row(n) for n in names)


def station(start="2000-01-01", days=800, seed=0) -> str:
    first = dt.date.fromisoformat(start)
    lines = []
    for k in range(days):
        d = first + dt.timedelta(days=k)
        j = k + seed
        lines.append(f"{d.year} {d.month} {d.day} {j % 7 * 0.5:.1f} {20 + j % 5} {10 + j % 3}")
    return "\n".join(lines) + "\n"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    settings.JOB_RETENTION_DAYS = 7
    settings.JOB_PROGRESS_INTERVAL = 0
    return settings


def files(**named) -> list:
    return [
        SimpleUploadedFile(n, t.encode() if isinstance(t, str) else t) for n, t in named.items()
    ]


def created(client, meta, **stations) -> BatchRun:
    """A batch of ``meta`` and the station files, checked and waiting to run, in a
    workspace of its own (``made.checked_batch``)."""
    return made.checked_batch(client, meta, **stations)


def run_batch(client, run: BatchRun, options) -> BatchRun:
    """Queue the batch with ``options`` (``made.queue``), as "Calculate" did."""
    return made.queue(client, run, options)


def zipped(**named) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in named.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def run_worker() -> Job:
    job = claim("test-worker")
    assert job is not None
    return run_job(job)


def statuses(run: BatchRun) -> dict[str, str]:
    run.refresh_from_db()
    return {s["name"]: s["status"] for s in run.stations}


# ---- The check --------------------------------------------------------------------------


def test_r_sample_metadata_is_bundled_unchanged():
    from climpact_web.batch.views import sample_metadata

    assert sample_metadata() == R_SAMPLE.read_bytes()


def test_sample_batch_is_ready():
    result = check.check_batch(R_SAMPLE.read_bytes(), sample_files())
    assert result.metadata_ok
    assert [s.status for s in result.stations] == ["ready", "ready"]
    first = result.stations[0]
    assert (first.name, first.latitude, first.params["spei_months"]) == (
        "sydney_observatory_hill_1936-2015",
        -10,
        24,
    )
    assert first.summary["first_year"] == 1936


@pytest.mark.parametrize(
    "text, message, line",
    [
        ("", "The metadata file is empty.", None),
        ("# only a comment\n", "The metadata file is empty.", None),
        (HEADER, "column names but no stations", None),
        (HEADER + "a.txt -30 150 3 3\n", "Line 2 has 5 values; each line needs 12", 2),
        (HEADER + "a.txt,-30,150,3,3,18,18,10,3,30,2,24\n", "not commas", 2),
        (HEADER + row("a.txt", lat="south"), "“south” in the latitude column is not a number", 2),
        (
            HEADER + row("a.txt", params="2.5\t3\t18\t18\t10\t3\t30\t2\t24"),
            "wsdin (days for WSDI) must be a whole number",
            2,
        ),
        (HEADER + row("a.txt") + row("a.csv"), "Lines 2 and 3 both give the station name “a”", 3),
    ],
)
def test_metadata_problems_name_the_line(text, message, line):
    result = check.check_batch(text.encode(), {})
    assert not result.metadata_ok and result.stations == []
    found = result.metadata_problems[0]
    assert message in found["message"], found
    assert found["line"] == line


def test_metadata_not_text_and_missing():
    assert (
        "not a text file"
        in check.check_batch(b"PK\x03\x04junk", {}).metadata_problems[0]["message"]
    )
    assert (
        check.check_batch(None, {}).metadata_problems[0]["message"]
        == "Choose the batch metadata file."
    )


def test_core_reads_what_the_check_accepts(tmp_path):
    """Every file the check accepts, the core reads to the same stations and parameters."""
    from climpact.batch import read_batch_metadata

    text = (
        "# a comment\n\n"
        + HEADER
        + row("a.txt", lat="-40.992345")
        + "\n"
        + row("b.dat").rstrip()
        + "  # x\n"
    )
    result = check.check_batch(text.encode(), {})
    assert result.metadata_ok
    path = tmp_path / "m.txt"
    path.write_text(text)
    core = read_batch_metadata(path)
    assert [s.station_file for s in core] == [s.station_file for s in result.stations]
    assert [s.latitude for s in core] == [s.latitude for s in result.stations]
    # The metadata file written for the job reads back the same.
    path.write_text(check.metadata_text(result.to_json()["stations"]))
    again = read_batch_metadata(path)
    assert [(s.station_file, s.latitude, s.params) for s in again] == [
        (s.station_file, s.latitude, s.params) for s in core
    ]


def test_first_line_that_looks_like_a_station_is_a_warning():
    result = check.check_batch(
        (row("a.txt") + row("b.txt")).encode(), {"b.txt": station().encode()}
    )
    assert "looks like a station" in result.metadata_warnings[0]
    assert [s.name for s in result.stations] == ["b"]


def test_station_statuses_and_reasons():
    text = (
        HEADER
        + row("good.txt", lat="0")
        + row("missing.txt")
        + row("Capital.txt")
        + row("bad.txt")
        + row("far.txt", lat="95", params="12\t3\t18\t18\t10\t0\t-1\t2\t24")
        + row("../escape.txt")
        + row(".hidden.txt")
    )
    uploads = {
        "good.txt": station().encode(),
        "capital.txt": station().encode(),
        "bad.txt": b"2000 1 1 0 20\n2000 1 2 x 20 10\n",
        "far.txt": station().encode(),
        "unused.txt": station().encode(),
    }
    result = check.check_batch(text.encode(), uploads)
    by_name = {s.name: s for s in result.stations}
    assert {n: s.status for n, s in by_name.items()} == {
        "good": "ready",
        "missing": "missing",
        "Capital": "missing",
        "bad": "invalid",
        "far": "invalid",
        "../escape": "invalid",
        ".hidden": "invalid",
    }
    assert "Latitude 0 is treated as the Southern Hemisphere" in by_name["good"].warnings[0]
    assert by_name["missing"].problems[0]["message"] == "No file named missing.txt was uploaded."
    assert "but capital.txt was" in by_name["Capital"].problems[0]["message"]
    bad = [p["message"] for p in by_name["bad"].problems]
    assert bad[0].startswith("Line 1 has 5 values") and "“x” in the precipitation column" in bad[1]
    assert by_name["bad"].problems[1]["text"] == "2000 1 2 x 20 10"
    far = " ".join(p["message"] for p in by_name["far"].problems)
    for expected in (
        "Latitude 95 is outside -90 to 90.",
        "wsdin (days for WSDI) must be between 1 and 10. It is 12.",
        "rxnday (days for Rxnday) must be 1 or more. It is 0.",
        "rnnmm (millimetres for Rnnmm) must be 0 or more. It is -1.",
    ):
        assert expected in far
    assert "is a folder path" in by_name["../escape"].problems[0]["message"]
    assert "cannot be used" in by_name[".hidden"].problems[0]["message"]
    assert result.extra_files == ["capital.txt", "unused.txt"]


def test_station_files_with_na_are_ready(tmp_path):
    """NA is a missing value, as R's read.table reads it, in the check and in the core."""
    from climpact.io.station import read_station_file

    lines = station().splitlines()
    lines[3] = "2000 1 4 NA 20 NA"
    text = "\n".join(lines) + "\n"
    result = check.check_batch((HEADER + row("na.txt")).encode(), {"na.txt": text.encode()})
    assert [s.status for s in result.stations] == ["ready"]
    path = tmp_path / "na.txt"
    path.write_text(text)
    df = read_station_file(path)
    assert df["prcp"].isna().sum() == 1 and df["tmin"].isna().sum() == 1


def test_parameter_rules_match_the_core():
    """The check refuses exactly what climpact.batch.validate_params refuses."""
    from dataclasses import replace

    from climpact.batch import validate_params
    from climpact.config import IndexParams

    for field, values in {
        "wsdi_days": (0, 1, 10, 11),
        "csdi_days": (0, 1, 10, 11),
        "rx_days": (0, 1),
        "txtn_days": (0, 1),
        "rnnmm": (-0.5, 0),
        "spei_months": (0, 1),
    }.items():
        for value in values:
            params = replace(IndexParams(custom=None), **{field: value})
            try:
                validate_params(params)
                core_ok = True
            except ValueError:
                core_ok = False
            from dataclasses import asdict

            fields = {k: v for k, v in asdict(params).items() if k in check.PARAM_FIELDS.values()}
            s = check.StationCheck("a", "a.txt", 2, 0.0, 0.0, fields)
            check.check_parameters(s)
            assert (s.problem_count == 0) == core_ok, (field, value)


def test_unpack_zip_with_folders_and_metadata():
    data = zipped(
        **{
            "batch/meta.txt": metadata("a.txt", "b.txt"),
            "batch/data/a.txt": station(),
            "batch/data/b.txt": station(seed=1),
            "__MACOSX/batch/._a.txt": "junk",
            "batch/.DS_Store": "junk",
        }
    )
    out = check.unpack([("all.zip", data), ("c.txt", b"x")])
    assert sorted(out.files) == ["a.txt", "b.txt", "c.txt"]
    assert out.metadata[0] == "meta.txt" and out.problems == []


def test_unpack_reports_bad_zips_and_repeats():
    out = check.unpack([("x.zip", b"PK\x03\x04broken"), ("a.txt", b"1"), ("a.txt", b"2")])
    assert out.files == {"a.txt": b"2"}
    assert any("not a zip file" in p for p in out.problems)
    assert any("Two files are named a.txt" in p for p in out.problems)
    two = zipped(**{"m1.txt": metadata("a.txt"), "m2.txt": metadata("a.txt")})
    assert "more than one metadata file" in check.unpack([("b.zip", two)]).problems[0]


def test_default_workers(monkeypatch):
    monkeypatch.setattr("climpact_web.stations.views_add.cpu_count", lambda: 8)
    assert [default_workers(n) for n in (1, 2, 13)] == [1, 2, 4]
    monkeypatch.setattr("climpact_web.stations.views_add.cpu_count", lambda: 1)
    assert default_workers(13) == 1


def test_plain_error_hides_paths_and_class_names():
    class FakeJob:
        input_dir = Path("/runs/x/input")
        output_dir = Path("/runs/x/output")

    assert plain_error("ValueError: data row 3 has 2 fields", FakeJob) == "data row 3 has 2 fields"
    assert (
        plain_error(
            "FileNotFoundError: station file not found: /runs/x/input/stations/a.txt", FakeJob
        )
        == "The station file was not found."
    )
    assert plain_error("something odd: here", FakeJob) == "something odd: here"


# ---- The pages ------------------------------------------------------------------------------


@pytest.mark.django_db
def test_start_page_is_add_stations(client):
    # The batch's first page and its sample are Add stations since #233; their forms went
    # with #271, so a form sent from before leads there too.
    for url in ("/batch/", "/batch/sample"):
        assert client.get(url)["Location"] == "/add/"
        assert (
            client.post(url, {"station_files": files(**{"a.txt": station()})})["Location"]
            == "/add/"
        )
    assert not BatchRun.objects.exists()
    response = client.get("/batch/sample-metadata.txt")
    assert response.content == R_SAMPLE.read_bytes()


@pytest.mark.django_db
def test_a_checked_batch_keeps_its_files_and_each_stations_status(client):
    run = created(
        client,
        metadata("a.txt", "b.txt", "missing.txt", "bad.txt"),
        **{"a.txt": station(), "b.txt": station(seed=1), "bad.txt": "nonsense\n1 2\n"},
    )
    assert statuses(run) == {"a": "ready", "b": "ready", "missing": "missing", "bad": "invalid"}
    assert run.metadata_name == "stations.txt" and run.folder_name == "stations"
    assert (run.files_dir / "a.txt").is_file() and run.metadata_path.is_file()
    # Its check page went with #271: a batch checked before and never run leads to Add
    # stations, whose review cannot read its check.
    for url in (f"/w/{run.workspace_id}/batch/", f"/w/{run.workspace_id}/"):
        assert client.get(url)["Location"] == "/add/"


@pytest.mark.django_db
def test_zip_with_metadata_inside(client):
    data = zipped(**{"meta.txt": metadata("a.txt"), "a.txt": station()})
    run = created(client, None, **{"all.zip": data})
    assert run.metadata_name == "meta.txt" and statuses(run) == {"a": "ready"}


def test_options_errors_in_plain_words(settings):
    """The batch's options, Add stations' "Applies to every station" since #233."""
    settings.IS_HOSTED = False
    data = {"base_start": "1971", "base_end": "2000", "workers": "1", "plots": "on"}

    def errors(**changes):
        form = OptionsForm({**data, **changes})
        form.is_valid()
        return [e for field in form.errors.values() for e in field]

    assert errors() == []
    assert errors(base_end="1960") == ["The last year must not be before the first year."]
    assert errors(workers="100000")[0].startswith("You cannot use more than")
    assert errors(workers="0") == ["You need at least 1."]
    # R: "Please specify start year"
    assert errors(base_start="") == ["Enter the first year of the base period."]


@pytest.mark.django_db
def test_hosted_mode_has_no_workers_field(client, settings):
    settings.IS_HOSTED = True
    settings.MIN_FREE_DISK_GB = 0
    response = client.post("/add/", {"files": files(**{"a.txt": station()})})
    html = client.get(response["Location"]).content.decode()  # Add stations' review
    assert 'name="workers"' not in html and 'name="base_start"' in html


@pytest.mark.django_db
def test_adding_needs_valid_options(client):
    response = client.post("/add/", {"files": files(**{"a.txt": station()})})
    data = {"intent": "add", "file-0": "a.txt", "name-0": "A", "lat-0": "-30", "lon-0": "150"}
    data |= {"base_start": "2000", "base_end": "1990", "workers": "1"}
    response = client.post(response["Location"], data)
    assert response.status_code == 400 and not Job.objects.exists()
    assert "The last year must not be before the first year." in response.content.decode()


@pytest.mark.django_db
def test_batch_runs_and_a_bad_station_fails_alone(client):
    """The ready stations run as one job; a station failing at run time fails alone, a
    station left out before the run is reported with its reason, and everything is in
    the zip."""
    run = created(
        client,
        metadata("a.txt", "b.txt", "c.txt", "missing.txt"),
        **{"a.txt": station(), "b.txt": station(seed=1), "c.txt": station(seed=2)},
    )
    data = {"base_start": "2000", "base_end": "2001", "workers": "1"}  # no plots: faster
    run = run_batch(client, run, data)
    job = run.job
    assert job.kind == "batch" and job.status == Status.QUEUED
    assert job.params["folder"] == "stations" and job.params["zip"] and not job.params["plots"]
    assert [s["name"] for s in job.params["skipped"]] == ["missing"]
    assert "missing.txt" not in (job.input_dir / "batch_metadata.txt").read_text()
    assert sorted(p.name for p in (job.input_dir / "stations").iterdir()) == [
        "a.txt",
        "b.txt",
        "c.txt",
    ]

    # The workspace's overview (#234): the run status line and a row a station.
    html = client.get(f"/w/{run.workspace_id}/").content.decode()
    assert "Calculating indices: 0 of 3 stations done." in html
    assert f'hx-get="/w/{run.workspace_id}/progress"' in html
    assert html.count('data-indices="waiting"') == 3 and 'data-indices="not_run"' in html

    # Break b's file after the check, so it fails in the run itself.
    (job.input_dir / "stations" / "b.txt").write_text("2000 1 1 0 20 10\n1999 1 1 0 20 10\n")
    job = run_worker()
    assert job.status == Status.SUCCEEDED, job.log
    by_name = {s["name"]: s for s in job.result["stations"]}
    assert by_name["a"]["ok"] and by_name["c"]["ok"] and not by_name["b"]["ok"]
    assert by_name["b"]["error_file"] == "stations/b.errors.txt"
    assert by_name["a"]["zip"] == "stations/a.zip" and by_name["a"]["folder"] == "stations/a"
    assert job.result["zip"] == "stations.zip"
    progress = json.loads((job.output_dir / "stations.json").read_text())["stations"]
    assert {s["name"]: s["state"] for s in progress} == {
        "a": "done",
        "b": "failed",
        "c": "done",
        "missing": "skipped",
    }
    with zipfile.ZipFile(job.output_dir / "stations.zip") as archive:
        names = archive.namelist()
    assert "b.errors.txt" in names and "missing.errors.txt" in names
    assert any(n.startswith("a/indices/") for n in names) and not any(
        n.startswith("b/") for n in names
    )
    with zipfile.ZipFile(job.output_dir / "stations" / "a.zip") as archive:
        assert any(n.startswith("indices/") for n in archive.namelist())

    html = client.get(f"/w/{run.workspace_id}/").content.decode()
    assert "hx-get" not in html and "run-status--failed" in html
    assert "2 of 3 stations calculated in" in html and "b failed:" in html
    assert "missing was not run: the station file is missing." in html
    # The workspace files are in Export ▾ and on Files, not on the status line (#239).
    assert f"/w/{run.workspace_id}/files/everything.zip" in html
    assert "Download all (zip, " not in html
    # Each station's own files are on its Files tab, not here (#234, #239).
    assert f"/jobs/{job.pk}/files/stations/a.zip" not in html
    assert "What is in the zip" not in html
    assert str(job.input_dir) not in html
    assert client.get(f"/jobs/{job.pk}/files/stations.zip").status_code == 200

    # The batch's address is its workspace's.
    assert client.get(f"/w/{run.workspace_id}/batch/")["Location"] == f"/w/{run.workspace_id}/"


@pytest.mark.django_db
def test_progress_fragment_shows_each_station(client):
    run = created(
        client, metadata("a.txt", "b.txt"), **{"a.txt": station(), "b.txt": station(seed=1)}
    )
    run = run_batch(client, run, {"base_start": "2000", "base_end": "2001", "workers": "1"})
    job = run.job
    now = timezone.now()
    Job.objects.filter(pk=job.pk).update(
        status=Status.RUNNING, started_at=now, heartbeat_at=now, step=7, total=30,
        stage="a: indices:climpact:txx",
    )  # fmt: skip
    job.output_dir.mkdir(parents=True)
    (job.output_dir / "stations.json").write_text(
        json.dumps(
            {
                "stations": [
                    {
                        "name": "a",
                        "state": "running",
                        "step": 7,
                        "total": 15,
                        "stage": "indices:climpact:txx",
                    },
                    {"name": "b", "state": "waiting", "step": 0, "total": 15, "stage": ""},
                ]
            }
        )
    )
    html = client.get(f"/w/{run.workspace_id}/progress").content.decode()
    assert html.lstrip().startswith('<div id="workspace-progress"')
    assert "Calculating indices: 0 of 2 stations done." in html
    assert "Calculating · 46%" in html and 'value="46"' in html
    assert "Waiting" in html and ">Cancel</button>" in html and "hx-get" in html


@pytest.mark.django_db
def test_other_sessions_get_404(client):
    run = created(client, metadata("a.txt"), **{"a.txt": station()})
    other = Client()
    session = other.session
    session[OWNER_KEY] = "someone-else"
    session.save()
    other.cookies["sessionid"] = session.session_key
    for url in (
        f"/w/{run.workspace_id}/batch/",
        f"/w/{run.workspace_id}/batch/results",
        f"/w/{run.workspace_id}/",
        f"/w/{run.workspace_id}/progress",
        f"/batch/{run.pk}/",
    ):
        assert other.get(url).status_code == 404
    assert client.get(f"/batch/{uuid.uuid4()}/").status_code == 404
    # The results' old address leads to the workspace's.
    space = f"/w/{run.workspace_id}/"
    assert client.get(f"{space}batch/results")["Location"] == space


@pytest.mark.django_db
def test_retention(client, settings):
    """A batch goes with its workspace (#231), and stray batch folders after the period."""
    settings.WORKSPACE_EXPIRY = True
    run = created(client, metadata("a.txt"), **{"a.txt": station()})
    old = timezone.now() - dt.timedelta(days=8)
    Workspace.objects.filter(pk=run.workspace_id).update(updated_at=old)
    stray = batches_dir() / str(uuid.uuid4())
    stray.mkdir(parents=True)
    import os

    os.utime(stray, (old.timestamp(), old.timestamp()))
    keep = created(client, metadata("a.txt"), **{"a.txt": station()})
    purge_expired()
    assert list(BatchRun.objects.all()) == [keep]
    assert not run.folder.exists() and not stray.exists() and keep.folder.exists()
    assert not Workspace.objects.filter(pk=run.workspace_id).exists()


@pytest.mark.django_db
def test_running_batch_is_not_purged(client, settings):
    settings.WORKSPACE_EXPIRY = True
    run = created(client, metadata("a.txt"), **{"a.txt": station()})
    run_batch(client, run, {"base_start": "2000", "base_end": "2001", "workers": "1"})
    Job.objects.update(status=Status.RUNNING, heartbeat_at=timezone.now())
    Workspace.objects.update(updated_at=timezone.now() - dt.timedelta(days=30))
    purge_expired()
    assert BatchRun.objects.count() == 1


@pytest.mark.django_db
def test_landing_page_and_header_link_to_batch(client):
    html = client.get("/").content.decode()
    assert 'href="/add/"' in html and 'href="/batch/"' not in html  # Add stations, #233
    nav = re.findall(r'<nav class="site-nav".*?</nav>', html, re.S)[0]
    # The header is Workspaces and Gridded since #227; the landing page starts a batch.
    assert re.findall(r'href="([^"]+)"', nav) == ["/w/", "/gridded/"]
    batch = client.get("/add/").content.decode()
    nav = re.findall(r'<nav class="site-nav".*?</nav>', batch, re.S)[0]
    assert '<a href="/w/" data-nav="workspaces" aria-current="true">' in nav


def test_skipped_names_are_safe_and_never_collide():
    from climpact_web.jobs.runners import _skipped_stations

    items = _skipped_stations(
        [
            {"name": ".a", "station_file": ".a.txt", "error": "bad"},
            {"name": "../a", "station_file": "../a.txt", "error": "bad"},
            {"station_file": "b c.txt", "error": "x"},
        ],
        {"a"},
    )
    assert items[0]["name"] == "a_2" and items[2]["name"] == "b c"
    assert len({i["name"] for i in items} | {"a"}) == 4
    assert all("/" not in i["name"] and not i["name"].startswith(".") for i in items)

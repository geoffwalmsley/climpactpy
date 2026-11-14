"""The batch page (#80): uploads and zips, the pre-flight check and its messages, the
options, one job for the ready stations with per-station progress, the results (errors,
downloads, a station failing alone), opening a station as a single-station analysis,
ownership and retention."""

import datetime as dt
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from climpact_web.batch import check
from climpact_web.batch.models import BatchRun, batches_dir
from climpact_web.batch.views import default_workers, plain_error, sample_files
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.retention import purge_expired
from climpact_web.jobs.views import OWNER_KEY
from climpact_web.jobs.worker import claim, run_job
from climpact_web.stations.models import Source, StationAnalysis, Step

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


def post_batch(client, meta=None, meta_name="stations.txt", **stations):
    data = {"station_files": files(**stations)}
    if meta is not None:
        data["metadata_file"] = SimpleUploadedFile(meta_name, meta.encode())
    return client.post("/batch/", data)


def created(client, meta, **stations) -> BatchRun:
    response = post_batch(client, meta, **stations)
    assert response.status_code == 302, response.content.decode()[:3000]
    return BatchRun.objects.get(pk=response["Location"].split("/")[2])


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
    monkeypatch.setattr("climpact_web.batch.views.cpu_count", lambda: 8)
    assert [default_workers(n) for n in (1, 2, 13)] == [1, 2, 4]
    monkeypatch.setattr("climpact_web.batch.views.cpu_count", lambda: 1)
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
def test_start_page(client):
    html = client.get("/batch/").content.decode()
    assert re.search(r'<form method="post" action="/batch/" enctype="multipart/form-data"', html)
    assert re.search(r'<input type="file" name="station_files"[^>]*multiple', html)
    assert re.search(r'<input type="file" name="metadata_file"', html)
    assert "Drop files here or choose them" in html
    assert 'action="/batch/sample"' in html and "/batch/sample-metadata.txt" in html
    assert 'aria-current="step"' in html and "Load files" in html
    assert "kept for 7 days" in html
    response = client.get("/batch/sample-metadata.txt")
    assert response.content == R_SAMPLE.read_bytes()


@pytest.mark.django_db
def test_nothing_chosen_gives_r_s_messages(client):
    html = client.post("/batch/", {}).content.decode()
    assert "Choose the batch metadata file." in html
    assert "Choose the station files, or a zip of them." in html
    assert "data-error-summary" in html
    html = post_batch(client, metadata("a.txt")).content.decode()
    assert "Choose the station files, or a zip of them." in html
    assert not BatchRun.objects.exists()


@pytest.mark.django_db
def test_upload_and_check_page(client):
    run = created(
        client,
        metadata("a.txt", "b.txt", "missing.txt", "bad.txt"),
        **{"a.txt": station(), "b.txt": station(seed=1), "bad.txt": "nonsense\n1 2\n"},
    )
    assert statuses(run) == {"a": "ready", "b": "ready", "missing": "missing", "bad": "invalid"}
    assert run.metadata_name == "stations.txt" and run.folder_name == "stations"
    assert (run.files_dir / "a.txt").is_file() and run.metadata_path.is_file()
    html = client.get(f"/batch/{run.pk}/").content.decode()
    assert "Calculate 2 stations" in html
    assert "No file named missing.txt was uploaded." in html
    assert "2 stations with missing files or problems will be left out" in html
    assert html.count("badge--success") == 2 and "File missing" in html and "Has problems" in html
    assert 'href="/batch/"' in html and 'aria-current="step"' in html
    assert "Index parameters from the metadata file" in html
    # The add-files panel opens when something is missing.
    assert re.search(
        r'<details class="disclosure" open>\s*<summary>.*?Add or replace files', html, re.S
    )


@pytest.mark.django_db
def test_zip_upload_with_metadata_inside(client):
    data = zipped(**{"meta.txt": metadata("a.txt"), "a.txt": station()})
    response = client.post("/batch/", {"station_files": files(**{"all.zip": data})})
    run = BatchRun.objects.get(pk=response["Location"].split("/")[2])
    assert run.metadata_name == "meta.txt" and statuses(run) == {"a": "ready"}
    # A zip in the metadata box works too.
    response = client.post("/batch/", {"metadata_file": SimpleUploadedFile("all.zip", data)})
    assert response.status_code == 302


@pytest.mark.django_db
def test_metadata_problems_on_the_check_page(client):
    run = created(client, HEADER + "a.txt -30\n", **{"a.txt": station()})
    html = client.get(f"/batch/{run.pk}/").content.decode()
    assert "The metadata file cannot be used: it has 1 problem" in html
    assert "Line 2 has 2 values" in html and "No station is ready" in html
    assert re.search(r"<button[^>]*disabled[^>]*>.*?No station is ready", html, re.S)


@pytest.mark.django_db
def test_adding_files_checks_again(client):
    run = created(client, metadata("a.txt", "b.txt"), **{"a.txt": station()})
    assert statuses(run) == {"a": "ready", "b": "missing"}
    response = client.post(
        f"/batch/{run.pk}/files", {"station_files": files(**{"b.txt": station(seed=2)})}
    )
    assert response.status_code == 302
    assert statuses(run) == {"a": "ready", "b": "ready"}
    response = client.post(
        f"/batch/{run.pk}/files",
        {"metadata_file": SimpleUploadedFile("new.txt", metadata("a.txt").encode())},
    )
    assert statuses(run) == {"a": "ready"} and run.metadata_name == "new.txt"
    html = client.post(f"/batch/{run.pk}/files", {}).content.decode()
    assert "Choose the files to add." in html


@pytest.mark.django_db
def test_sample_batch_in_one_click(client):
    response = client.post("/batch/sample")
    run = BatchRun.objects.get(pk=response["Location"].split("/")[2])
    assert run.source == "sample" and statuses(run) == {
        "sydney_observatory_hill_1936-2015": "ready",
        "sydney_observatory_hill_batch_file_2": "ready",
    }
    assert client.get("/batch/sample").status_code == 302


@pytest.mark.django_db
def test_options_are_checked_as_they_change(client, settings):
    run = created(client, metadata("a.txt"), **{"a.txt": station()})
    url = f"/batch/{run.pk}/options"
    assert client.post(url, {}).status_code == 400  # htmx only
    data = {"base_start": "1971", "base_end": "2000", "workers": "1", "plots": "on"}
    html = client.post(url, {**data, "base_end": "1999"}, HTTP_HX_REQUEST="true").content.decode()
    assert 'id="batch-options"' in html and "<html" not in html
    assert (
        "Less than a year of the base period is covered" in html and "a (data 2000 to 2002)" in html
    )
    assert "about 1 minute" in html
    html = client.post(
        url, {**data, "base_start": "2000", "base_end": "2001"}, HTTP_HX_REQUEST="true"
    ).content.decode()
    assert "Less than a year" not in html
    html = client.post(url, {**data, "base_end": "1960"}, HTTP_HX_REQUEST="true").content.decode()
    assert "The last year must not be before the first year." in html
    html = client.post(url, {**data, "workers": "100000"}, HTTP_HX_REQUEST="true").content.decode()
    assert "You cannot use more than" in html
    html = client.post(url, {**data, "workers": "0"}, HTTP_HX_REQUEST="true").content.decode()
    assert "You need at least 1." in html
    html = client.post(url, {**data, "base_start": ""}, HTTP_HX_REQUEST="true").content.decode()
    assert "Enter the first year of the base period." in html  # R: "Please specify start year"


@pytest.mark.django_db
def test_hosted_mode_has_no_workers_field(client, settings):
    settings.IS_HOSTED = True
    run = created(client, metadata("a.txt"), **{"a.txt": station()})
    html = client.get(f"/batch/{run.pk}/").content.decode()
    assert 'name="workers"' not in html and 'name="base_start"' in html


@pytest.mark.django_db
def test_run_needs_valid_options_and_a_ready_station(client):
    run = created(client, metadata("missing.txt"), **{"other.txt": station()})
    data = {"base_start": "2000", "base_end": "2001", "workers": "1"}
    html = client.post(f"/batch/{run.pk}/run", data).content.decode()
    assert "No station is ready" in html and not Job.objects.exists()
    run = created(client, metadata("a.txt"), **{"a.txt": station()})
    html = client.post(f"/batch/{run.pk}/run", {**data, "base_end": "1990"}).content.decode()
    assert "There is 1 problem with the form" in html and not Job.objects.exists()


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
    response = client.post(f"/batch/{run.pk}/run", data)
    run.refresh_from_db()
    assert response["Location"] == f"/batch/{run.pk}/results"
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

    html = client.get(f"/batch/{run.pk}/results").content.decode()
    assert "Calculating the batch" in html and f'hx-get="/batch/{run.pk}/progress"' in html
    assert "Waiting to start" in html

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

    html = client.get(f"/batch/{run.pk}/results").content.decode()
    assert "Batch results" in html and "hx-get" not in html
    assert "2 of 3 stations calculated" in html
    assert "1 station failed; its error is below." in html
    assert "1 station was left out before the run." in html
    assert f"/jobs/{job.pk}/files/stations.zip" in html and "Download everything (zip)" in html
    assert f"/jobs/{job.pk}/files/stations/a.zip" in html
    assert f"/jobs/{job.pk}/files/stations/b.errors.txt" in html
    assert "No file named missing.txt was uploaded." in html
    assert str(job.input_dir) not in html
    # Failures are listed first.
    assert html.index(">b</h3>") < html.index(">a</h3>")
    assert client.get(f"/jobs/{job.pk}/files/stations.zip").status_code == 200

    # Running again while it runs is not possible; after it, the check page offers it.
    check_html = client.get(f"/batch/{run.pk}/").content.decode()
    assert "This batch is being calculated." not in check_html
    assert "Calculate and download" in check_html


@pytest.mark.django_db
def test_progress_fragment_shows_each_station(client):
    run = created(
        client, metadata("a.txt", "b.txt"), **{"a.txt": station(), "b.txt": station(seed=1)}
    )
    client.post(f"/batch/{run.pk}/run", {"base_start": "2000", "base_end": "2001", "workers": "1"})
    run.refresh_from_db()
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
    html = client.get(f"/batch/{run.pk}/progress").content.decode()
    assert "0 of 2 stations finished" in html
    assert "Calculating indices (txx)" in html and 'value="46"' in html
    assert "Waiting" in html and "Cancel the batch" in html and "hx-get" in html


@pytest.mark.django_db
def test_open_a_station_as_a_single_station(client):
    run = created(client, metadata("a.txt"), **{"a.txt": station()})
    client.post(f"/batch/{run.pk}/run", {"base_start": "2000", "base_end": "2001", "workers": "1"})
    run_worker()
    url = f"/batch/{run.pk}/open/a"
    assert client.get(url).status_code == 405
    response = client.post(url)
    analysis = StationAnalysis.objects.get()
    assert response["Location"] == f"/station/{analysis.pk}/load"
    assert analysis.source == Source.BATCH and analysis.step == Step.QC
    assert (analysis.station_name, analysis.latitude, analysis.longitude) == ("a", -30, 150)
    assert (analysis.base_start, analysis.base_end) == (2000, 2001)
    assert analysis.origin["params"]["spei_months"] == 24 and analysis.origin["station"] == "a"
    assert analysis.station_file.is_file() and analysis.summary["first_year"] == 2000
    assert client.get(response["Location"]).status_code == 200
    # Opening it again goes to the same analysis, and the results link to it.
    assert client.post(url)["Location"] == response["Location"]
    assert StationAnalysis.objects.count() == 1
    html = client.get(f"/batch/{run.pk}/results").content.decode()
    assert f'href="/station/{analysis.pk}/load"' in html
    assert client.post(f"/batch/{run.pk}/open/nope").status_code == 404


@pytest.mark.django_db
def test_other_sessions_get_404(client):
    run = created(client, metadata("a.txt"), **{"a.txt": station()})
    other = Client()
    session = other.session
    session[OWNER_KEY] = "someone-else"
    session.save()
    other.cookies["sessionid"] = session.session_key
    for url in (f"/batch/{run.pk}/", f"/batch/{run.pk}/results", f"/batch/{run.pk}/progress"):
        assert other.get(url).status_code == 404
    for url in (f"/batch/{run.pk}/run", f"/batch/{run.pk}/delete", f"/batch/{run.pk}/files"):
        assert other.post(url).status_code == 404
    assert client.get(f"/batch/{uuid.uuid4()}/").status_code == 404
    assert client.get(f"/batch/{run.pk}/results").status_code == 302  # not started yet


@pytest.mark.django_db
def test_delete_now(client):
    run = created(client, metadata("a.txt"), **{"a.txt": station()})
    response = client.post(f"/batch/{run.pk}/delete")
    assert response["Location"] == "/batch/"
    assert not BatchRun.objects.exists() and not run.folder.exists()


@pytest.mark.django_db
def test_retention(client):
    run = created(client, metadata("a.txt"), **{"a.txt": station()})
    old = timezone.now() - dt.timedelta(days=8)
    BatchRun.objects.filter(pk=run.pk).update(updated_at=old)
    stray = batches_dir() / str(uuid.uuid4())
    stray.mkdir(parents=True)
    import os

    os.utime(stray, (old.timestamp(), old.timestamp()))
    keep = created(client, metadata("a.txt"), **{"a.txt": station()})
    purge_expired()
    assert list(BatchRun.objects.all()) == [keep]
    assert not run.folder.exists() and not stray.exists() and keep.folder.exists()


@pytest.mark.django_db
def test_running_batch_is_not_purged(client):
    run = created(client, metadata("a.txt"), **{"a.txt": station()})
    client.post(f"/batch/{run.pk}/run", {"base_start": "2000", "base_end": "2001", "workers": "1"})
    Job.objects.update(status=Status.RUNNING, heartbeat_at=timezone.now())
    BatchRun.objects.update(updated_at=timezone.now() - dt.timedelta(days=30))
    purge_expired()
    assert BatchRun.objects.count() == 1


@pytest.mark.django_db
def test_landing_page_and_header_link_to_batch(client):
    html = client.get("/").content.decode()
    assert 'href="/batch/"' in html
    nav = re.findall(r'<nav class="site-nav".*?</nav>', html, re.S)[0]
    assert re.findall(r'href="([^"]+)"', nav) == ["/station/", "/batch/", "/jobs/"]


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

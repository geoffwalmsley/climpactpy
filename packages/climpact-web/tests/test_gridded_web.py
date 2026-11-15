"""The gridded pages (#85): choosing files by path (local mode) or upload, the folder
browser, inspecting the files and guessing the variables, the set-up form and its checks,
the thresholds and indices jobs, the results (files, map, cell series, CSVs, zip), the
hosted-mode switch and upload limit, ownership and retention."""

import datetime as dt
import io
import shutil
import zipfile
from pathlib import Path

import netCDF4
import numpy as np
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.utils import timezone

from climpact_web.gridded import inspection, maps
from climpact_web.gridded.forms import default_base
from climpact_web.gridded.models import GriddedRun, gridded_dir
from climpact_web.gridded.views import SAMPLE_DIR, SAMPLE_FILE, base_days
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.retention import purge_expired
from climpact_web.jobs.worker import claim, run_job

REPO = Path(__file__).resolve().parents[3]
GRIDS = REPO / "reference" / "gridded" / "input"
SAMPLE = SAMPLE_DIR / SAMPLE_FILE

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    settings.JOB_RETENTION_DAYS = 7
    settings.JOB_PROGRESS_INTERVAL = 0
    return settings


def run_jobs() -> list[Job]:
    done = []
    while (job := claim("test-worker")) is not None:
        done.append(run_job(job))
    return done


def setup_data(run: GriddedRun, **changes) -> dict:
    """The set-up form as the page fills it in, with changes."""
    from climpact_web.gridded.views import initial_setup, run_summary

    _infos, _problems, summary = run_summary(run)
    data = initial_setup(run, summary)
    data.update(institution="Test institute", institution_id="TI")
    data.update(changes)
    out = {}
    for key, value in data.items():
        if value is None:
            continue
        out[key] = value
    return out


def sample_run(client) -> GriddedRun:
    response = client.post("/gridded/sample")
    assert response.status_code == 302
    return GriddedRun.objects.get(pk=response["Location"].split("/")[2])


# ---- Inspection ---------------------------------------------------------------------------


def test_inspect_sample_grid():
    info = inspection.inspect_file(SAMPLE)
    assert info.ok, info.problem
    assert (info.ny, info.nx) == (3, 4)
    assert (info.first, info.last, info.days) == ("1991-01-01", "2010-12-31", 7305)
    assert info.calendar == "standard"
    assert [v.name for v in info.variables] == ["tmax", "tmin", "precip"]
    assert info.variables[0].units == "K"
    assert inspection.guess_names([info]) == {"tasmax": "tmax", "tasmin": "tmin", "pr": "precip"}


def test_inspect_separate_files_and_calendars():
    infos = [
        inspection.inspect_file(GRIDS / f)
        for f in ("grid_filled_360day_tas.nc", "grid_filled_360day_pr.nc")
    ]
    assert all(i.ok for i in infos)
    assert infos[0].calendar == "360_day" and infos[0].last.endswith("-12-30")
    names = inspection.guess_names(infos)
    assert names == {"tasmax": "tasmax", "tasmin": "tasmin", "pr": "pr"}
    problems, summary = inspection.check_names(infos, names)
    assert problems == {} and summary.cells == 12


def test_inspect_problems(tmp_path):
    text = tmp_path / "notes.nc"
    text.write_text("not netcdf")
    assert "not a netCDF" in inspection.inspect_file(text).problem
    assert "not found" in inspection.inspect_file(tmp_path / "missing.nc").problem
    flat = tmp_path / "flat.nc"
    with netCDF4.Dataset(flat, "w") as nc:
        nc.createDimension("x", 3)
        nc.createVariable("v", "f4", ("x",))
    assert "No variable with time" in inspection.inspect_file(flat).problem
    leap = tmp_path / "all_leap.nc"
    shutil.copy(SAMPLE, leap)
    with netCDF4.Dataset(leap, "a") as nc:
        nc["time"].calendar = "all_leap"
    assert "all_leap calendar is not supported" in inspection.inspect_file(leap).problem


def test_check_names_reports_each_variable(tmp_path):
    info = inspection.inspect_file(SAMPLE)
    problems, _ = inspection.check_names([info], {"tasmax": "tmax", "tasmin": "tmax", "pr": "nope"})
    assert "chosen twice" in problems["tasmin"] and "nope" in problems["pr"]
    bad = tmp_path / "bad_units.nc"
    shutil.copy(SAMPLE, bad)
    with netCDF4.Dataset(bad, "a") as nc:
        nc["precip"].units = "inches"
    problems, _ = inspection.check_names(
        [inspection.inspect_file(bad)], {"tasmax": "tmax", "tasmin": "tmin", "pr": "precip"}
    )
    assert "inches" in problems["pr"]


def test_default_max_values_gives_about_20_blocks():
    from climpact_web.gridded.views import default_max_values

    big = inspection.Summary(ny=100, nx=100, days=365 * 60)
    assert default_max_values(big, 5_000_000) == 5.0
    sample = inspection.Summary(ny=19, nx=24, days=7305)  # Climpact's full sample grid
    assert default_max_values(sample, 5_000_000) == 0.5
    assert default_max_values(inspection.Summary(ny=3, nx=4, days=7305), 5_000_000) == 0.1


def test_base_days_and_defaults():
    info = inspection.inspect_file(SAMPLE)
    _, summary = inspection.check_names(
        [info], {"tasmax": "tmax", "tasmin": "tmin", "pr": "precip"}
    )
    assert base_days(summary, 1991, 2010) == 7305
    assert base_days(summary, 1971, 2000) == 3653
    assert base_days(summary, 1971, 1980) == 0
    assert default_base(1991, 2010) == (1991, 2010)
    assert default_base(1950, 2020) == (1971, 2000)
    assert default_base(2041, 2060) == (2041, 2060)
    s360 = inspection.Summary(first="1961-01-01", last="2000-12-30", calendar="360_day")
    assert base_days(s360, 1971, 2000) == 30 * 360


# ---- Step 1: choosing files ----------------------------------------------------------------


def test_start_page_local(client):
    html = client.get("/gridded/").content.decode()
    assert "Files on this computer" in html and 'id="file-browser"' in html
    assert "Use the sample grid" in html and 'name="files"' in html


def test_paths_are_checked(client, tmp_path):
    (tmp_path / "a.txt").write_text("x")
    response = client.post(
        "/gridded/",
        {
            "paths": f"relative.nc\n{tmp_path}\n{tmp_path / 'a.txt'}\n{tmp_path / 'no.nc'}",
            "action": "use",
        },
    )
    html = response.content.decode()
    assert response.status_code == 200
    assert "give the full path" in html
    assert "is a folder" in html
    assert "is not a netCDF file" in html
    assert "no such file" in html


def test_choose_files_by_path(client):
    paths = f"{GRIDS / 'grid_stations_tas.nc'}\n{GRIDS / 'grid_stations_pr.nc'}"
    response = client.post("/gridded/", {"paths": paths, "action": "use"})
    assert response.status_code == 302
    run = GriddedRun.objects.get()
    assert run.source == "path" and run.paths == [
        str(GRIDS / "grid_stations_tas.nc"),
        str(GRIDS / "grid_stations_pr.nc"),
    ]
    assert run.names == {"tasmax": "tasmax", "tasmin": "tasmin", "pr": "pr"}
    html = client.get(response["Location"]).content.decode()
    assert "3 × 4 cells" in html and "degrees_C" in html and str(GRIDS) in html


def test_browser_lists_folders_and_adds_files(client):
    response = client.post(
        "/gridded/", {"paths": "", "action": f"browse:{GRIDS}"}, HTTP_HX_REQUEST="true"
    )
    html = response.content.decode()
    assert 'id="gridded-chooser"' in html and "<html" not in html
    assert "grid_sample.nc" in html and "Up one folder" in html
    response = client.post(
        "/gridded/",
        {"paths": "", "action": f"add:{GRIDS / 'grid_sample.nc'}"},
        HTTP_HX_REQUEST="true",
    )
    assert str(GRIDS / "grid_sample.nc") in response.content.decode()
    # Without JavaScript the whole page comes back.
    response = client.post("/gridded/", {"paths": "", "action": f"browse:{GRIDS}"})
    assert "<html" in response.content.decode()


def test_upload(client):
    data = SAMPLE.read_bytes()
    response = client.post("/gridded/upload", {"files": [SimpleUploadedFile("my grid.nc", data)]})
    assert response.status_code == 302
    run = GriddedRun.objects.get()
    assert run.source == "upload" and run.files[0]["name"] == "my grid.nc"
    assert Path(run.paths[0]).parent == run.uploads_dir and Path(run.paths[0]).name == "my_grid.nc"
    response = client.post(
        "/gridded/upload", {"files": [SimpleUploadedFile("x.nc", b"hello world")]}
    )
    assert "x.nc is not a netCDF file" in response.content.decode()


def test_upload_limit(client, settings):
    settings.GRIDDED_MAX_UPLOAD_MB = 1
    settings.GRIDDED_MAX_UPLOAD_BYTES = 1024 * 1024
    big = SimpleUploadedFile("big.nc", b"\x89HDF\r\n\x1a\n" + b"0" * (1024 * 1024 + 10))
    response = client.post("/gridded/upload", {"files": [big]})
    assert response.status_code == 413 and "1 MB" in response.content.decode()


def test_gridded_requests_may_be_larger_than_other_uploads(client, settings):
    from climpact_web.middleware import upload_limit

    settings.MAX_UPLOAD_MB, settings.MAX_UPLOAD_BYTES = 50, 50 * 2**20
    settings.GRIDDED_MAX_UPLOAD_MB, settings.GRIDDED_MAX_UPLOAD_BYTES = 200, 200 * 2**20
    assert upload_limit("/gridded/upload") == (200 * 2**20, 200)
    assert upload_limit("/station/") == (50 * 2**20, 50)
    settings.GRIDDED_ENABLED = False
    assert upload_limit("/gridded/upload") == (50 * 2**20, 50)


# ---- Hosted mode ---------------------------------------------------------------------------


@override_settings(IS_HOSTED=True, GRIDDED_ENABLED=False)
def test_hosted_off_by_default(client):
    assert client.get("/gridded/").status_code == 404
    assert client.post("/gridded/sample").status_code == 404
    assert "/gridded/" not in client.get("/").content.decode()


@override_settings(IS_HOSTED=True, GRIDDED_ENABLED=True)
def test_hosted_when_enabled_offers_uploads_not_paths(client):
    html = client.get("/gridded/").content.decode()
    assert 'name="files"' in html and 'name="paths"' not in html and "file-browser" not in html
    assert client.get("/gridded/browse").status_code == 404
    # A path posted anyway is ignored.
    response = client.post("/gridded/", {"paths": str(SAMPLE), "action": "use"})
    assert response.status_code == 302 and response["Location"] == "/gridded/"
    assert not GriddedRun.objects.exists()
    run = sample_run(client)
    html = client.get(f"/gridded/{run.pk}/").content.decode()
    assert (
        'name="copy_to"' not in html
        and 'name="workers"' not in html
        and 'name="thresholds_path"' not in html
    )
    assert 'name="thresholds_upload"' in html


def test_settings_switch(monkeypatch):
    import importlib

    import climpact_web.settings as module

    for name, value in {
        "CLIMPACT_WEB_MODE": "hosted",
        "CLIMPACT_WEB_SECRET_KEY": "x" * 50,
        "CLIMPACT_WEB_ALLOWED_HOSTS": "example.org",
        "DATABASE_URL": "sqlite:///:memory:",
        "CLIMPACT_WEB_STATIC_ROOT": "/tmp/static",
    }.items():
        monkeypatch.setenv(name, value)
    try:
        s = importlib.reload(module)
        assert s.GRIDDED_ENABLED is False and s.GRIDDED_MAX_UPLOAD_MB == 200
        monkeypatch.setenv("CLIMPACT_WEB_GRIDDED_HOSTED", "true")
        monkeypatch.setenv("CLIMPACT_WEB_GRIDDED_MAX_UPLOAD_MB", "500")
        s = importlib.reload(module)
        assert s.GRIDDED_ENABLED is True and s.GRIDDED_MAX_UPLOAD_BYTES == 500 * 2**20
    finally:
        monkeypatch.undo()
        importlib.reload(module)


# ---- Step 2: set-up -------------------------------------------------------------------------


def test_setup_page_shows_the_files_and_defaults(client):
    run = sample_run(client)
    html = client.get(f"/gridded/{run.pk}/").content.decode()
    assert "3 × 4 cells" in html and "1991-01-01 to 2010-12-31" in html
    assert '<option value="tmax" selected>' in html and '<option value="precip" selected>' in html
    assert 'value="1991"' in html and 'value="2010"' in html  # R's gridded default
    assert "var_daily_climpactpy_historical_NA_1991-2010.nc" in html
    assert "climpact.sampledata.gridded.3x4.1991-2010.thresholds.1991-2010.nc" in html
    assert "Nairn and Fawcett" in html
    assert 'name="indices" value="txx" checked' in html


def test_setup_checks_fragment(client):
    run = sample_run(client)
    data = setup_data(run, base_start=1971, base_end=1980)
    html = client.post(f"/gridded/{run.pk}/checks", data, HTTP_HX_REQUEST="true").content.decode()
    assert 'id="gridded-checks"' in html and "cover 0 days of the base period" in html
    data = setup_data(run, tasmax="precip")
    html = client.post(f"/gridded/{run.pk}/checks", data, HTTP_HX_REQUEST="true").content.decode()
    assert "chosen twice" in html
    html = client.post(
        f"/gridded/{run.pk}/checks", setup_data(run), HTTP_HX_REQUEST="true"
    ).content.decode()
    assert "7,305 days of the base period" in html and "index files will be written" in html
    assert client.post(f"/gridded/{run.pk}/checks", setup_data(run)).status_code == 400


def test_setup_validation(client, tmp_path):
    run = sample_run(client)
    cases = [
        ({"base_start": 2000, "base_end": 1990}, "must not be before"),
        ({"base_start": 1971, "base_end": 1980}, "at least 360 are needed"),
        ({"institution": ""}, "institution&#x27;s name"),
        ({"template": "bad.nc"}, "CMIP5 form"),
        ({"thresholds_name": "../x.nc", "task": "thresholds"}, "file name ending in .nc"),
        ({"wsdi_days": 11}, "Enter 10 or less"),
        ({"thresholds_source": "file", "thresholds_path": ""}, "path of the thresholds file"),
        (
            {"thresholds_source": "file", "thresholds_path": str(SAMPLE)},
            "no day in the base period",
        ),
        ({"copy_to": "relative/folder"}, "full path of a folder"),
        ({"tmp_dir": str(tmp_path / "missing")}, "existing folder"),
        ({"pr": "tmin"}, "chosen twice"),
        ({"workers": 100000}, "cannot use more than"),
    ]
    for changes, message in cases:
        response = client.post(f"/gridded/{run.pk}/", setup_data(run, **changes))
        assert response.status_code == 200, changes
        assert message in response.content.decode(), (changes, message)
    assert not Job.objects.exists()


def test_preflight_uses_the_core_reader(client, tmp_path):
    other = tmp_path / "other.nc"
    shutil.copy(GRIDS / "grid_stations_pr.nc", other)
    with netCDF4.Dataset(other, "a") as nc:
        nc["time"][:] = nc["time"][:] + 1  # every date a day later
    response = client.post(
        "/gridded/", {"paths": f"{GRIDS / 'grid_stations_tas.nc'}\n{other}", "action": "use"}
    )
    run = GriddedRun.objects.get(pk=response["Location"].split("/")[2])
    response = client.post(f"/gridded/{run.pk}/", setup_data(run, base_start=1971, base_end=2000))
    html = response.content.decode()
    assert "dates differ" in html or "cannot be read together" in html
    assert not Job.objects.exists()


# ---- Step 3: jobs and results ---------------------------------------------------------------


def test_sample_run_end_to_end(client, tmp_path):
    run = sample_run(client)
    copy_to = tmp_path / "results"
    data = setup_data(
        run,
        task="both",
        indices=["txx", "fd", "rx1day", "spi", "rxdday"],
        copy_to=str(copy_to),
        rx_days=3,
    )
    response = client.post(f"/gridded/{run.pk}/", data)
    assert response.status_code == 302 and response["Location"].endswith("/results")
    run.refresh_from_db()
    assert (
        run.thresholds_job.kind == "gridded-thresholds"
        and run.indices_job.kind == "gridded-indices"
    )
    assert run.thresholds_job.created_at <= run.indices_job.created_at
    p = run.indices_job.params
    assert p["names"] == {"tasmax": "tmax", "tasmin": "tmin", "pr": "precip"}
    assert p["indices"] == ["txx", "fd", "rx1day", "spi", "rxdday"] and p["params"]["rx_days"] == 3
    assert (
        p["institution_id"] == "TI" and p["max_values"] == 100_000
    )  # a small grid: the smallest default

    html = client.get(f"/gridded/{run.pk}/results").content.decode()
    assert "Waiting to start" in html and "hx-get" in html
    jobs = run_jobs()
    assert [j.status for j in jobs] == [Status.SUCCEEDED, Status.SUCCEEDED], [j.error for j in jobs]
    run.refresh_from_db()
    assert run.thresholds_job.result["files"] == [
        "climpact.sampledata.gridded.3x4.1991-2010.thresholds.1991-2010.nc"
    ]
    names = sorted(run.indices_job.result["files"])
    assert "rx3day_ANN_climpactpy_historical_NA_1991-2010.nc" in names
    assert "spi_MON_climpactpy_historical_NA_1991-2010.nc" in names
    assert len(names) == 9  # txx, fd, rx1day, rx3day: MON and ANN; spi: MON
    assert sorted(p.name for p in copy_to.iterdir()) == sorted(
        names + run.thresholds_job.result["files"]
    )

    # The progress fragment asks for a reload once everything has finished.
    response = client.get(f"/gridded/{run.pk}/progress?was_active=1", HTTP_HX_REQUEST="true")
    assert response["HX-Refresh"] == "true"
    html = client.get(f"/gridded/{run.pk}/progress").content.decode()
    assert "hx-get" not in html and "Download all" in html

    html = client.get(f"/gridded/{run.pk}/results").content.decode()
    assert "Explore the indices" in html and "txx, 2010" in html  # txx annual, last year
    assert 'class="gmap__svg"' in html and html.count('class="gmap__cell') == 12
    assert "View as table" in html and "Choose a cell" in html
    assert "rx3day_ANN_climpactpy_historical_NA_1991-2010.nc" in html

    # A chosen cell, time step and file, as htmx asks for them.
    spi = "spi_MON_climpactpy_historical_NA_1991-2010.nc"
    response = client.get(
        f"/gridded/{run.pk}/explore",
        {"file": spi, "t": 5, "scale": 2, "cell": "0,1"},
        HTTP_HX_REQUEST="true",
    )
    html = response.content.decode()
    assert response.status_code == 200 and "<html" not in html
    assert "1991-06" in html and "(12-month scale)" in html
    assert "gmap__cell--selected" in html
    assert "cell=0%2C1" in response["HX-Push-Url"] and "/results?" in response["HX-Push-Url"]

    # The values shown are the file's.
    path = run.indices_job.output_dir / "txx_ANN_climpactpy_historical_NA_1991-2010.nc"
    with netCDF4.Dataset(path) as nc:
        expected = np.ma.filled(nc["txx"][:, 2, 3].astype(float), np.nan)
    response = client.get(f"/gridded/{run.pk}/series.csv", {"file": path.name, "cell": "2,3"})
    rows = response.content.decode().splitlines()
    assert rows[0] == "time,txx" and rows[1].startswith("1991,") and len(rows) == 21
    assert float(rows[-1].split(",")[1]) == pytest.approx(expected[-1], abs=1e-4)
    # The interactive chart's data (#75): the same values, in the charts app's format.
    response = client.get(f"/gridded/{run.pk}/series.json", {"file": path.name, "cell": "2,3"})
    payload = response.json()
    assert payload["kind"] == "index" and payload["step"] == "year" and payload["trend"] is None
    assert payload["x"][0] == 1991 and len(payload["y"]) == 20
    assert payload["y"][-1] == pytest.approx(expected[-1], abs=1e-4)
    assert payload["csv"].startswith(f"/gridded/{run.pk}/series.csv?")
    assert "No trend" not in payload["summary"] and "1991 to 2010" in payload["summary"]
    assert (
        client.get(
            f"/gridded/{run.pk}/series.json",
            {"file": path.name, "cell": "2,3"},
            HTTP_IF_NONE_MATCH=response["ETag"],
        ).status_code
        == 304
    )
    monthly = client.get(
        f"/gridded/{run.pk}/series.json", {"file": spi, "scale": 2, "cell": "0,1"}
    ).json()
    assert monthly["step"] == "month" and monthly["bars"] and len(monthly["x"]) == 240
    html = client.get(f"/gridded/{run.pk}/results").content.decode()
    assert f'data-chart-src="/gridded/{run.pk}/series.json?' in html
    assert "uPlot.iife.min.js" in html and "<noscript>" in html and "series-preview" in html
    assert 'id="series-chart-summary" data-chart-summary></p>' in html  # filled from the data
    assert 'id="series-table-caption"' in html  # the table view
    response = client.get(f"/gridded/{run.pk}/map.csv", {"file": path.name, "t": 0})
    rows = response.content.decode().splitlines()
    assert rows[0] == "latitude,longitude,txx" and len(rows) == 13

    # Everything in one zip.
    response = client.get(f"/gridded/{run.pk}/download.zip")
    archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
    assert len(archive.namelist()) == 10
    assert all(n.startswith("climpact_gridded/") for n in archive.namelist())


def test_indices_with_a_thresholds_file(client):
    """grid_future (2001-2020) with the thresholds of grid_stations, as R's reference run."""
    response = client.post(
        "/gridded/",
        {
            "paths": f"{GRIDS / 'grid_stations_tas.nc'}\n{GRIDS / 'grid_stations_pr.nc'}",
            "action": "use",
        },
    )
    hist = GriddedRun.objects.get(pk=response["Location"].split("/")[2])
    client.post(
        f"/gridded/{hist.pk}/", setup_data(hist, task="thresholds", base_start=1971, base_end=2000)
    )
    (thresholds_job,) = run_jobs()
    assert thresholds_job.status == Status.SUCCEEDED, thresholds_job.error
    thresholds = thresholds_job.output_dir / thresholds_job.result["files"][0]

    response = client.post(
        "/gridded/",
        {
            "paths": f"{GRIDS / 'grid_future_tas.nc'}\n{GRIDS / 'grid_future_pr.nc'}",
            "action": "use",
        },
    )
    future = GriddedRun.objects.get(pk=response["Location"].split("/")[2])
    data = setup_data(
        future,
        base_start=1971,
        base_end=2000,
        thresholds_source="file",
        thresholds_path=str(thresholds),
        indices=["tx90p", "r95p"],
    )
    response = client.post(f"/gridded/{future.pk}/", data)
    assert response.status_code == 302, response.content.decode()[:2000]
    future.refresh_from_db()
    assert future.thresholds_job is None and future.indices_job.params["thresholds_file"] == str(
        thresholds
    )
    (job,) = run_jobs()
    assert job.status == Status.SUCCEEDED, job.error
    assert sorted(job.result["files"]) == [
        "r95p_ANN_climpactpy_historical_NA_2001-2020.nc",
        "tx90p_ANN_climpactpy_historical_NA_2001-2020.nc",
        "tx90p_MON_climpactpy_historical_NA_2001-2020.nc",
    ]


def test_job_failure_is_shown(client):
    run = sample_run(client)
    client.post(f"/gridded/{run.pk}/", setup_data(run, indices=["fd"]))
    run.refresh_from_db()
    params = dict(run.indices_job.params, input_files=["/no/such/file.nc"])
    Job.objects.filter(pk=run.indices_job.pk).update(params=params)
    (job,) = run_jobs()
    assert job.status == Status.FAILED
    html = client.get(f"/gridded/{run.pk}/results").content.decode()
    assert "The calculation failed." in html and "/no/such/file.nc" in html and "Try again" in html


def test_runner_passes_reading_options(tmp_path, monkeypatch):
    from climpact_web.jobs import runners
    from climpact_web.jobs.registry import JobContext

    seen = {}

    def fake_open_grid(files, names=None, max_values=0, rechunk=None, tmp_dir=None):
        seen.update(max_values=max_values, rechunk=rechunk, tmp_dir=tmp_dir)
        raise ValueError("stop")

    monkeypatch.setattr("climpact.gridded.open_grid", fake_open_grid)
    ctx = JobContext(
        "id",
        {
            "input_files": [str(SAMPLE)],
            "max_values": 1000,
            "rechunk": "yes",
            "tmp_dir": str(tmp_path),
        },
        tmp_path / "input",
        tmp_path / "output",
    )
    with pytest.raises(ValueError):
        runners._open_grid(ctx)
    assert seen == {"max_values": 1000, "rechunk": True, "tmp_dir": tmp_path}


# ---- Maps -------------------------------------------------------------------------------------


def test_draw_map_orientation_and_classes():
    values = np.array([[1.0, 2.0], [np.nan, 4.0]])
    drawing = maps.draw_map(values, lat=[-40.0, -30.0], lon=[140.0, 150.0], selected=(1, 1))
    # Latitude increases with the row: the last row is drawn at the top.
    top = [c for c in drawing.cells if c.py == 0]
    assert {c.y for c in top} == {1}
    assert [c.css for c in drawing.cells if c.y == 1 and c.x == 0] == ["gmap__na"]
    assert drawing.has_missing and drawing.lo == "1" and drawing.hi == "4"
    assert next(c for c in drawing.cells if c.selected).value == "4"
    assert drawing.rows[0]["lat"] == "30°S" and drawing.lon_headers == ["140°E", "150°E"]


def test_map_defaults_to_the_last_step_with_values(tmp_path):
    path = tmp_path / "hw_ANN_m_e_r_2001-2003.nc"
    with netCDF4.Dataset(path, "w") as nc:
        nc.createDimension("time", 3)
        nc.createDimension("lat", 2)
        nc.createDimension("lon", 2)
        t = nc.createVariable("time", "f8", ("time",))
        t.units, t.calendar = "days since 2001-01-01", "standard"
        t[:] = [182, 547, 912]
        nc.createVariable("lat", "f8", ("lat",))[:] = [-30, -20]
        nc.createVariable("lon", "f8", ("lon",))[:] = [140, 150]
        v = nc.createVariable("hwn_tx90", "f4", ("time", "lat", "lon"), fill_value=1e20)
        v[:] = np.ma.masked_all((3, 2, 2))
        v[1, 0, 0] = 2.0
    layer = maps.open_layer(path, path.name)
    assert layer.times == ["2001", "2002", "2003"]
    assert maps.last_step_with_values(path, layer) == 1


def test_draw_map_thins_a_large_grid(monkeypatch):
    monkeypatch.setattr(maps, "MAX_MAP_CELLS", 100)
    drawing = maps.draw_map(np.ones((40, 40)), lat=list(range(40)), lon=list(range(40)))
    assert drawing.stride == 4 and len(drawing.cells) == 100


def test_series_breaks_at_missing_values():
    s = maps.draw_series(np.array([1.0, np.nan, 3.0]), ["2001", "2002", "2003"])
    assert s.path.count("M") == 2 and s.count == 2 and s.rows[1]["value"] == ""
    assert maps.draw_series(np.array([np.nan]), ["2001"]) is None


# ---- Ownership and retention -------------------------------------------------------------------


def test_other_sessions_get_404(client):
    run = sample_run(client)
    other = Client()
    for url in (
        f"/gridded/{run.pk}/",
        f"/gridded/{run.pk}/results",
        f"/gridded/{run.pk}/download.zip",
    ):
        assert other.get(url).status_code == 404


def test_delete_and_retention(client):
    data = SAMPLE.read_bytes()
    client.post("/gridded/upload", {"files": [SimpleUploadedFile("g.nc", data)]})
    run = GriddedRun.objects.get()
    assert run.uploads_dir.is_dir()
    GriddedRun.objects.filter(pk=run.pk).update(updated_at=timezone.now() - dt.timedelta(days=8))
    stray = gridded_dir() / "0b3c2f5e-8a6d-4f1e-9a3b-6d7c8e9f0a1b"
    stray.mkdir(parents=True)
    old = (timezone.now() - dt.timedelta(days=8)).timestamp()
    import os

    os.utime(stray, (old, old))
    purge_expired()
    assert not GriddedRun.objects.exists() and not run.folder.exists() and not stray.exists()

    run = sample_run(client)
    response = client.post(f"/gridded/{run.pk}/delete")
    assert response.status_code == 302 and not GriddedRun.objects.exists()
    assert SAMPLE.is_file()  # a file read in place is never deleted

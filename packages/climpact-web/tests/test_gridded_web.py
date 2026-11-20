"""The gridded pages (#85, #289, #291, #292): Gridded's list of runs, choosing files (local
mode: a folder listing, paths and patterns) or uploading them, inspecting the files and
guessing the variables, the set-up form and its checks, the thresholds and indices jobs, a
run's context bar and its Map, Files and Set-up tabs (the map, cell series, CSVs, zips, the
links for wget and the run's record), the hosted-mode switch and upload limit, ownership
and retention."""

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

from climpact_web.batch.forms import cpu_count
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


def split_by_year(src: Path, folder: Path, years=None) -> list[Path]:
    """``src`` copied to one file per year (raw values, types and attributes), or to the
    files of ``years``, a list of ``(first, last)``."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    with netCDF4.Dataset(src) as nc:
        t = nc["time"]
        dates = netCDF4.num2date(t[:], t.units, getattr(t, "calendar", "standard"))
        year = np.array([d.year for d in dates])
        for first, last in years or [(y, y) for y in np.unique(year)]:
            index = np.flatnonzero((year >= first) & (year <= last))
            path = folder / f"{src.stem}_{first}.nc"
            with netCDF4.Dataset(path, "w") as dst:
                for name, dim in nc.dimensions.items():
                    dst.createDimension(name, None if dim.isunlimited() else len(dim))
                for name, var in nc.variables.items():
                    var.set_auto_maskandscale(False)
                    fill = var.getncattr("_FillValue") if "_FillValue" in var.ncattrs() else None
                    v = dst.createVariable(name, var.dtype, var.dimensions, fill_value=fill)
                    v.set_auto_maskandscale(False)
                    v.setncatts({k: var.getncattr(k) for k in var.ncattrs() if k != "_FillValue"})
                    v[:] = var[:][index] if "time" in var.dimensions else var[:]
            out.append(path)
    return out


NAMES = {"tasmax": "tmax", "tasmin": "tmin", "pr": "precip"}


def test_a_variable_split_across_files(tmp_path):
    """The files of a variable are joined in the order of their first day, as the core's
    reader joins them: one choice per variable, the joined grid and period."""
    files = split_by_year(SAMPLE, tmp_path)
    infos = [inspection.inspect_file(f) for f in reversed(files)]
    assert inspection.guess_names(infos) == NAMES
    choices = inspection.variable_choices(infos)
    assert [name for name, _label in choices] == ["tmax", "tmin", "precip"]
    assert choices[0][1].endswith(" · 20 files")
    problems, summary = inspection.check_names(infos, NAMES)
    assert problems == {}
    assert (summary.first, summary.last, summary.days, summary.cells) == (
        "1991-01-01",
        "2010-12-31",
        7305,
        12,
    )
    assert inspection.find_variable(infos, "tmax")[0].name == files[0].name
    groups = inspection.group_files(infos)
    assert len(groups) == 1 and groups[0].count == 20 and groups[0].ok
    assert [f.name for f in groups[0].files] == [f.name for f in files]
    assert (groups[0].first_year, groups[0].last_year) == ("1991", "2010")
    assert groups[0].variables == ["tmax", "tmin", "precip"]
    assert groups[0].folder == str(tmp_path)
    assert groups[0].size == sum(f.stat().st_size for f in files)


def test_split_files_that_do_not_fit(tmp_path):
    files = split_by_year(SAMPLE, tmp_path / "s")
    infos = [inspection.inspect_file(f) for f in files]
    gap = infos[:3] + infos[4:]
    problems, _ = inspection.check_names(gap, NAMES)
    assert problems["tasmax"] == (
        "There is a gap between climpact.sampledata.gridded.3x4.1991-2010_1993.nc, which "
        "ends on 1993-12-31, and climpact.sampledata.gridded.3x4.1991-2010_1995.nc, which "
        "starts on 1995-01-01."
    )
    two_years = split_by_year(SAMPLE, tmp_path / "t", years=[(1993, 1994)])
    problems, _ = inspection.check_names(infos + [inspection.inspect_file(two_years[0])], NAMES)
    assert "overlap: both have the days from 1993-01-01 to 1993-12-31." in problems["tasmax"]
    shutil.copy(files[1], tmp_path / "kelvin.nc")
    with netCDF4.Dataset(tmp_path / "kelvin.nc", "a") as nc:
        nc["tmax"].units = "degC"
    mixed = [infos[0], inspection.inspect_file(tmp_path / "kelvin.nc")]
    problems, _ = inspection.check_names(mixed, NAMES)
    assert problems["tasmax"].startswith(
        "climpact.sampledata.gridded.3x4.1991-2010_1991.nc is in K"
    )
    assert "same units" in problems["tasmax"] and "tasmin" not in problems
    with netCDF4.Dataset(tmp_path / "kelvin.nc", "a") as nc:
        nc["tmax"].units = "K"
        nc["time"].calendar = "noleap"
    problems, _ = inspection.check_names(
        [infos[0], inspection.inspect_file(tmp_path / "kelvin.nc")], NAMES
    )
    assert "in the standard calendar and kelvin.nc in the noleap calendar" in problems["pr"]


# ---- New gridded run: choosing files ----------------------------------------------------------


def test_new_run_page_local(client):
    html = client.get("/gridded/new/").content.decode()
    assert "Files on this computer" in html and 'id="file-listing"' in html
    assert "Paste paths or a pattern instead" in html and 'name="paths"' in html
    assert "Try the sample grid" in html and "(3 × 4 cells, 1991–2010, 525.0\xa0KB)" in html
    assert "Read the files" in html and "No files yet" in html
    assert "up to 200" in html and 'name="files"' not in html  # no upload locally (#292)
    assert "<h1>New gridded run</h1>" in html and 'aria-label="Breadcrumb"' in html
    assert "steps__" not in html and "Continue where you left off" not in html


def test_paths_are_checked(client, tmp_path):
    (tmp_path / "a.txt").write_text("x")
    response = client.post(
        "/gridded/new/",
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
    response = client.post("/gridded/new/", {"paths": paths, "action": "use"})
    assert response.status_code == 302
    run = GriddedRun.objects.get()
    assert run.source == "path" and run.paths == [
        str(GRIDS / "grid_stations_tas.nc"),
        str(GRIDS / "grid_stations_pr.nc"),
    ]
    assert run.names == {"tasmax": "tasmax", "tasmin": "tasmin", "pr": "pr"}
    html = client.get(response["Location"]).content.decode()
    assert '<td class="code">3 × 4</td>' in html and "degrees_C" in html and str(GRIDS) in html


def test_listing_shows_what_each_file_holds(client):
    """The folder listing (#292): each netCDF file with its daily variables and dates from
    its header, folders as links; htmx swaps the listing only, without JavaScript the
    whole page comes back."""
    response = client.post("/gridded/new/", {"action": f"browse:{GRIDS}"}, HTTP_HX_REQUEST="true")
    html = response.content.decode()
    assert html.lstrip().startswith('<div class="gridded-listing" id="file-listing">')
    assert "<html" not in html and f'value="{GRIDS}"' in html
    row = html[html.index('value="' + str(GRIDS / "grid_stations_tas.nc")) :]
    row = row[: row.index("</tr>")]
    assert '<td class="code">tasmax, tasmin</td>' in row and "1966–2005" in row
    assert "disabled" not in row and "checked" not in row
    assert f'value="browse:{GRIDS.parent}"' in html  # the folder above, in the path bar
    response = client.post("/gridded/new/", {"action": f"browse:{GRIDS.parent}"})
    html = response.content.decode()
    assert "<html" in html and f'value="browse:{GRIDS}"' in html and ">input/</button>" in html
    # The page opens where the chooser was last.
    assert f'name="current" value="{GRIDS.parent}"' in client.get("/gridded/new/").content.decode()


def test_listing_greys_files_that_cannot_be_chosen(client, tmp_path):
    shutil.copy(SAMPLE, tmp_path / "grid.nc")
    with netCDF4.Dataset(tmp_path / "orog.nc", "w") as nc:
        nc.createDimension("lat", 2)
        nc.createDimension("lon", 2)
        nc.createVariable("orog", "f4", ("lat", "lon"))[:] = 1.0
    with netCDF4.Dataset(tmp_path / "base.thresholds.nc", "w") as nc:
        nc.base_period = "1971-2000"
        for dim, n in (("time", 365), ("lat", 2), ("lon", 2)):
            nc.createDimension(dim, n)
            nc.createVariable(dim, "f8", (dim,))[:] = np.arange(n)
        nc.variables["time"].units = "days since 1986-01-01"
        nc.createVariable("tx90thresh", "f4", ("time", "lat", "lon"))[:] = 1.0
    (tmp_path / "notes.txt").write_text("not listed")
    html = client.get("/gridded/new/", {"dir": str(tmp_path)}).content.decode()
    assert "notes.txt" not in html
    assert html.count('class="gridded-listing__unusable"') == 2
    assert "– (no time axis)" in html and "– (thresholds file)" in html
    assert '<td class="code">1971–2000</td>' in html
    assert html.count(" disabled>") == 2
    assert '<td class="code">tmax, tmin, precip</td>' in html


def test_ticked_files_are_kept_across_folders(client, tmp_path):
    (tmp_path / "sub").mkdir()
    ticked = str(GRIDS / "grid_stations_tas.nc")
    html = client.post(
        "/gridded/new/",
        {"action": f"browse:{tmp_path}", "current": str(GRIDS), "file": [ticked]},
    ).content.decode()
    assert f'<input type="hidden" name="file" value="{ticked}">' in html
    assert ">sub/</button>" in html and "No folders or netCDF files here." not in html
    assert "1 file chosen · tasmax, tasmin · 658.6\xa0KB" in html
    html = client.post(
        "/gridded/new/",
        {"action": f"browse:{GRIDS}", "current": str(tmp_path), "file": [ticked]},
    ).content.decode()
    assert f'value="{ticked}" id="listed-' in html and " checked>" in html
    # Ticking a file (htmx) puts what is chosen in the line under the listing.
    html = client.post(
        "/gridded/new/?tick=1",
        {
            "current": str(GRIDS),
            "file": [ticked],
            "paths": str(GRIDS / "grid_stations_pr.nc"),
        },
        HTTP_HX_REQUEST="true",
    ).content.decode()
    assert 'id="chosen-summary"' in html and "<html" not in html
    assert "2 files chosen · tasmax, tasmin, pr · " in html
    # Read the files: those ticked and those typed.
    response = client.post(
        "/gridded/new/",
        {"action": "use", "file": [ticked], "paths": str(GRIDS / "grid_stations_pr.nc")},
    )
    assert response.status_code == 302
    assert GriddedRun.objects.get().paths == [ticked, str(GRIDS / "grid_stations_pr.nc")]


def test_folder_field(client, tmp_path):
    html = client.post(
        "/gridded/new/", {"action": "open", "folder": str(tmp_path), "current": str(GRIDS)}
    ).content.decode()
    assert f'name="current" value="{tmp_path.resolve()}"' in html
    html = client.post(
        "/gridded/new/",
        {"action": "open", "folder": str(tmp_path / "nope"), "current": str(GRIDS)},
        HTTP_HX_REQUEST="true",
    ).content.decode()
    assert f"There is no folder {tmp_path / 'nope'}." in html and 'aria-invalid="true"' in html
    assert f'name="current" value="{GRIDS}"' in html  # still the folder it was showing
    assert f'value="{tmp_path / "nope"}"' in html  # what was typed, to correct


def test_patterns_expand_to_files(client, tmp_path):
    files = split_by_year(SAMPLE, tmp_path, [(1991, 1991), (1992, 1992), (2000, 2000)])[:2]
    (tmp_path / "folder_1990.nc").mkdir()  # a folder the pattern matches: left out
    response = client.post("/gridded/new/", {"action": "use", "paths": str(tmp_path / "*_199?.nc")})
    assert response.status_code == 302, response.content.decode()
    assert GriddedRun.objects.get().paths == [str(f) for f in files]
    html = client.post(
        "/gridded/new/",
        {"action": "use", "paths": f"{tmp_path}/*.nc4\nrelative/*.nc"},
    ).content.decode()
    assert f"{tmp_path}/*.nc4 matches no files." in html
    assert "relative/*.nc: give the full path" in html
    assert "open>" in html and f"{tmp_path}/*.nc4" in html  # the box open, as typed
    html = client.post("/gridded/new/", {"action": "use"}).content.decode()
    assert "Tick at least one netCDF file, or enter its path." in html


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


def test_up_to_200_files(client, tmp_path):
    """A variable split across many files: up to 200 files, by path or uploaded (more
    than Django's default of 100 files in a request)."""
    fake = [SimpleUploadedFile(f"x{i}.nc", b"hello") for i in range(150)]
    html = client.post("/gridded/upload", {"files": fake}).content.decode()
    assert "x149.nc is not a netCDF file" in html
    fake = [SimpleUploadedFile(f"x{i}.nc", b"hello") for i in range(201)]
    assert (
        "Choose at most 200 files."
        in client.post("/gridded/upload", {"files": fake}).content.decode()
    )
    paths = "\n".join(str(tmp_path / f"y{i}.nc") for i in range(201))
    html = client.post("/gridded/new/", {"paths": paths, "action": "use"}).content.decode()
    assert "Choose at most 200 files." in html


def test_setup_groups_a_variable_split_across_files(client, tmp_path):
    files = split_by_year(SAMPLE, tmp_path)
    response = client.post(
        "/gridded/new/", {"paths": "\n".join(str(f) for f in files), "action": "use"}
    )
    run = GriddedRun.objects.get(pk=response["Location"].split("/")[2])
    assert run.names == NAMES and len(run.paths) == 20
    html = client.get(response["Location"]).content.decode()
    assert html.count('<tr>\n        <th scope="row" class="gridded-inputs__file">') == 1
    assert "<summary>20 files, 1991–2010</summary>" in html
    assert "1991-01-01 → 2010-12-31" in html and "1993-01-01 → 1993-12-31" in html
    assert f"{tmp_path}/</span>" in html  # locally, the files' folder
    assert '<li title="climpact.sampledata.gridded.3x4.1991-2010_1995.nc">' in html
    assert '<option value="tmax" selected>' in html
    html = client.post(
        f"/gridded/{run.pk}/checks", setup_data(run), HTTP_HX_REQUEST="true"
    ).content.decode()
    assert "Ready to start" in html and "the same in all 20 files." in html
    assert "all 7,305 days of 1991–2010" in html
    # A variable split across files: its Header opens the first file's.
    assert (
        f'href="/gridded/{run.pk}/setup/header/'
        in client.get(f"/gridded/{run.pk}/setup/").content.decode()
    )
    # The core's reader accepts them: the run starts.
    response = client.post(f"/gridded/{run.pk}/setup/", setup_data(run, indices=["txx"]))
    assert response.status_code == 302, response.content.decode()
    assert Job.objects.get().params["input_files"] == [str(f) for f in files]
    jobs = run_jobs()
    assert [j.status for j in jobs] == [Status.SUCCEEDED], [j.error for j in jobs]


def test_setup_shows_a_file_that_cannot_be_used(client, tmp_path):
    bad = tmp_path / "notes.nc"
    bad.write_bytes(b"\x89HDF\r\n\x1a\nnot really")
    response = client.post("/gridded/new/", {"paths": f"{SAMPLE}\n{bad}", "action": "use"})
    html = client.get(response["Location"]).content.decode()
    assert 'class="gridded-inputs__bad"' in html and "Cannot be used:" in html
    assert "notes.nc</span>" in html


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
    assert upload_limit("/station/new") == (50 * 2**20, 50)
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
    html = client.get("/gridded/new/").content.decode()
    assert 'name="files"' in html and 'name="paths"' not in html and "file-listing" not in html
    assert "Drop .nc files here" in html and "Up to 200.0\xa0MB in all on this server" in html
    assert "kept 7 days, then deleted" in html and "cdo sellonlatbox" in html
    assert client.get("/gridded/new/", {"dir": "/"}).status_code == 200
    assert "file-listing" not in client.get("/gridded/new/", {"dir": "/"}).content.decode()
    # A path posted anyway is ignored.
    response = client.post("/gridded/new/", {"paths": str(SAMPLE), "action": "use"})
    assert response.status_code == 302 and response["Location"] == "/gridded/new/"
    assert not GriddedRun.objects.exists()
    run = sample_run(client)
    html = client.get(f"/gridded/{run.pk}/setup/").content.decode()
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


# ---- Set-up --------------------------------------------------------------------------------


def test_setup_page_shows_the_files_and_defaults(client):
    run = sample_run(client)
    # A run not started yet opens its set-up, with a breadcrumb and no stepper.
    response = client.get(f"/gridded/{run.pk}/")
    assert response.status_code == 302 and response["Location"] == f"/gridded/{run.pk}/setup/"
    html = client.get(f"/gridded/{run.pk}/setup/").content.decode()
    assert "New run</a></li>" in html and '<span aria-current="page">set-up</span>' in html
    assert '<h1 class="context-bar__name">Sample grid, 1991–2010 <a' in html
    assert f"/gridded/{run.pk}/rename/" in html and "Choose other files" in html
    assert "Climpact has read the header of 1 file. Nothing has been calculated yet." in html
    assert "steps__" not in html and 'aria-label="Run sections"' not in html
    assert '<td class="code">3 × 4</td>' in html and "1991-01-01 → 2010-12-31" in html
    assert "climpact.sampledata.gridded.3x4.1991-2010.nc</span>" in html
    assert '<td class="code">tmax, tmin, precip</td>' in html
    assert '<option value="tmax" selected>' in html and '<option value="precip" selected>' in html
    assert 'value="1991"' in html and 'value="2010"' in html  # R's gridded default
    assert "var_daily_climpact_historical_NA_1991-2010.nc" in html
    assert "climpact.sampledata.gridded.3x4.1991-2010.thresholds.1991-2010.nc" in html
    assert 'name="indices" value="txx" checked' in html
    # The sections in the board's order, then the summary panel with the one Start button.
    order = [
        'id="files-title"',
        'id="variables-title"',
        'id="task-title"',
        'id="base-title"',
        'id="indices-title"',
        'id="output-title"',
        ">Computing</span>",
        'id="summary-title"',
    ]
    assert [html.index(part) for part in order] == sorted(html.index(part) for part in order)
    assert html.count('type="submit" class="button button--block') == 1
    assert ">Start the calculation<" in html and ">Ready to start</h2>" in html
    # The Variables table: each variable's units and how Climpact reads them.
    assert '<span id="var-units-tasmax">K</span>' in html
    assert (
        "°C (K − 273.15)" in html
        and '<span id="var-read-pr" class="gridded-vars__read">mm/day<' in html
    )
    assert "Together: 3 × 4 cells, 33.33°\u00a0S to 29.52°\u00a0S" in html
    assert "same grid and time axis in every file ✓" in html
    # The base period's timeline and coverage, the indices by code, the panel's checks.
    assert 'class="gridded-timeline__base" x="0.0%"' in html
    assert "The data cover all 7,305 days of 1991–2010 (at least 360 needed)." in html
    assert "55 of 55 · 88 files" in html
    assert '<span class="gridded-indices__code">TXx</span>' in html
    assert html.count('class="gridded-indices__slow"') == 4
    for title in ("Grid", "Period", "Variables", "Base period", "Writes", "Disk", "Time"):
        assert f"<strong>{title}</strong>" in html, title
    assert "88 files for 55 indices and trends.nc, up to about" in html
    assert "Under a minute on " in html
    cores = cpu_count()
    workers = max(1, min(4, cores - 1))  # the default, from the machine's cores
    assert f"{workers} of {cores} cores · 0.1 M values at once · cell-first copy: automatic" in html


def test_setup_checks_fragment(client):
    """The summary panel as the form changes, with the parts of the form that follow it
    swapped out of band."""
    run = sample_run(client)

    def checks(**changes):
        data = setup_data(run, **changes)
        return client.post(
            f"/gridded/{run.pk}/checks", data, HTTP_HX_REQUEST="true"
        ).content.decode()

    html = checks(base_start=1971, base_end=1980)
    assert html.startswith('<div id="gridded-summary"') and ">Before you start</h2>" in html
    assert '1 problem to fix before starting: <a href="#id_base_start">Base period</a>.' in html
    assert "1971–1980: 0 days in the data; at least 360 are needed." in html
    assert (
        '<p id="base-coverage" class="gridded-coverage gridded-coverage--bad" hx-swap-oob="true">'
        in html
    )
    assert (
        '<div id="base-timeline" class="gridded-timeline" aria-hidden="true" hx-swap-oob="true">'
        in html
    )
    html = checks(tasmax="precip")
    assert "chosen twice" in html and "Not usable" in html
    assert '<span id="var-units-tasmax" hx-swap-oob="true">kg m-2 d-1</span>' in html
    html = checks(base_start=1995, indices=["txx", "spi"])
    assert ">Ready to start</h2>" in html and "2 of 55 · 3 files" in html
    assert "1995–2010: all 5,844 days in the data." in html
    assert "The data cover all 5,844 days of 1995–2010" in html
    assert 'x="20.0%"' in html  # the base period starts a fifth of the way along
    assert (
        'Gives <span class="font-mono">txx_MON_climpact_historical_NA_1991-2010.nc</span>' in html
    )
    html = checks(indices=[])
    assert "0 of 55 · 0 files" in html and "No index is chosen." in html
    html = checks(task="thresholds")
    assert "1 thresholds file, up to about" in html
    html = checks(rechunk="yes", workers=2)
    assert "<strong>Cell-first copy</strong>" in html and "2 of " in html
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
        ({"indices": []}, "Choose at least one index."),
        ({"workers": 100000}, "cannot use more than"),
    ]
    for changes, message in cases:
        response = client.post(f"/gridded/{run.pk}/setup/", setup_data(run, **changes))
        assert response.status_code == 200, changes
        assert message in response.content.decode(), (changes, message)
    assert not Job.objects.exists()


def era5_files(folder: Path, pr_units: str = "m") -> list[Path]:
    """The sample grid as three ERA5-like files (#293): mx2t and mn2t in K, and tp, the
    day's total in metres of water (or ``pr_units``)."""
    spec = [
        ("mx2t", "tmax", "K", "Maximum temperature at 2 metres", 1.0),
        ("mn2t", "tmin", "K", "Minimum temperature at 2 metres", 1.0),
        ("tp", "precip", pr_units, "Total precipitation", 0.001),
    ]
    out = []
    for name, var, units, long_name, scale in spec:
        path = folder / f"era5_{name}_day_SEA_1991-2010.nc"
        with netCDF4.Dataset(SAMPLE) as src, netCDF4.Dataset(path, "w") as dst:
            for dim, d in src.dimensions.items():
                dst.createDimension(dim, None if d.isunlimited() else len(d))
            for coord in ("time", "lat", "lon"):
                v = dst.createVariable(coord, src[coord].dtype, src[coord].dimensions)
                v.setncatts({a: src[coord].getncattr(a) for a in src[coord].ncattrs()})
                v[:] = src[coord][:]
            v = dst.createVariable(name, "f4", src[var].dimensions)
            v.units, v.long_name = units, long_name
            v[:] = np.asarray(src[var][:], dtype=float) * scale
        out.append(path)
    return out


def test_units_read_as_and_how_to_convert():
    from climpact_web.gridded import setup_page

    assert setup_page.read_as("tasmax", "K") == "°C (K − 273.15)"
    assert setup_page.read_as("tasmin", "degrees_C") == "°C"
    assert setup_page.read_as("pr", "kg m-2 s-1") == "mm/day (× 86400)"
    assert setup_page.read_as("pr", "mm/day") == "mm/day"
    assert setup_page.read_as("pr", "m") == "" and setup_page.read_as("tasmax", "") == ""
    one = [inspection.FileInfo(path="/d/era5_tp.nc", name="era5_tp.nc")]
    help_ = setup_page.units_help("pr", "tp", "m", one)
    assert help_.lead == "Precipitation: Climpact cannot read the units m."
    assert "ERA5's tp" in help_.text and "multiply by 1000" in help_.text
    assert help_.command == "cdo -setattribute,tp@units=mm/day -mulc,1000 era5_tp.nc pr_mm.nc"
    for units in ("mm/h", "kg m-2 h-1", "mm hr-1"):
        help_ = setup_page.units_help("pr", "pr", units, one)
        assert "-mulc,24 era5_tp.nc pr_mm.nc" in help_.command, units
    split = [inspection.FileInfo(path=f"/d/tp_{y}.nc", name=f"tp_{y}.nc") for y in (1991, 1992)]
    help_ = setup_page.units_help("pr", "tp", "m", split)
    assert help_.command.endswith("-mulc,1000 -mergetime 'tp_199*.nc' pr_mm.nc")
    assert help_.files == 2
    help_ = setup_page.units_help("pr", "pr", "furlongs", one)
    assert not help_.command and "It reads a daily rate" in help_.text
    help_ = setup_page.units_help("tasmax", "tx", "degF", one)
    assert "cannot read the units degF" in help_.lead and "It reads K or degrees_C" in help_.text
    help_ = setup_page.units_help("pr", "pr", "", one)
    assert help_.lead == "Precipitation: the variable pr has no units attribute."


def test_estimates():
    from climpact.gridded.indices import index_files
    from climpact_web.gridded import setup_page

    summary = inspection.Summary(
        ny=47, nx=55, first="1961-01-01", last="2020-12-31", days=21915, calendar="standard"
    )
    specs = index_files()
    est = setup_page.estimate({"task": "indices"}, summary, specs, 6)
    assert est.index_files == len(specs) and est.indices == 55
    assert 0.5e9 < est.index_bytes < 2e9  # float32 values, before compression
    assert 5 * 60 < est.seconds < 10 * 60  # 0.015 s a cell-year, 2,585 cells, 60 years, 6 cores
    fast = [s for s in specs if s.index not in ("hw", "hwEHF", "spi", "spei")]
    assert setup_page.estimate({"task": "indices"}, summary, fast, 6).seconds < est.seconds
    both = setup_page.estimate(
        {"task": "both", "base_start": 1971, "base_end": 2000}, summary, specs, 6
    )
    assert both.thresholds_bytes > 3 * 10958 * 2585 * 8 and both.seconds > est.seconds
    assert setup_page.size_text(1.3e9) == "1.3 GB"
    assert setup_page.size_text(40e6) == "40 MB"
    assert setup_page.period_days("standard", 1971, 2000) == 10958
    assert setup_page.period_days("360_day", 1971, 2000) == 10800
    assert setup_page.period_days("noleap", 1971, 2000) == 10950


def test_setup_era5_precipitation_in_metres(client, tmp_path):
    """The GridSetup board's problem: ERA5's tp, in metres, which Climpact cannot read;
    the page says what it reads and how to convert, with a CDO command, and the run does
    not start."""
    files = era5_files(tmp_path)
    response = client.post(
        "/gridded/new/", {"paths": "\n".join(str(f) for f in files), "action": "use"}
    )
    run = GriddedRun.objects.get(pk=response["Location"].split("/")[2])
    assert run.names == {"tasmax": "mx2t", "tasmin": "mn2t", "pr": "tp"}
    html = client.get(f"/gridded/{run.pk}/setup/").content.decode()
    assert "Climpact has read the headers of 3 files." in html
    assert ">Before you start</h2>" in html
    assert '1 problem to fix before starting: <a href="#id_pr">Precipitation units</a>.' in html
    assert '<span id="var-units-pr">m</span>' in html
    assert '<span id="var-check-pr" class="gridded-vars__check gridded-vars__check--bad">' in html
    assert "<strong>Precipitation: Climpact cannot read the units m.</strong>" in html
    assert (
        "<code data-copy-source>cdo -setattribute,tp@units=mm/day -mulc,1000 "
        "era5_tp_day_SEA_1991-2010.nc pr_mm.nc</code>"
    ) in html
    assert "Precipitation’s units, m, cannot be read." in html
    assert "<strong>Grid</strong>" in html  # the grid and period are still described
    assert "same grid and time axis in every file" not in html
    assert ">Start checks again and stops at the problem.<" in html
    response = client.post(f"/gridded/{run.pk}/setup/", setup_data(run))
    assert response.status_code == 200 and not Job.objects.exists()
    # Converted as the command says, the files are read.
    with netCDF4.Dataset(files[2], "a") as nc:
        nc["tp"][:] = nc["tp"][:] * 1000
        nc["tp"].units = "mm/day"
    run = GriddedRun.objects.get(
        pk=client.post(
            "/gridded/new/", {"paths": "\n".join(str(f) for f in files), "action": "use"}
        )["Location"].split("/")[2]
    )
    html = client.get(f"/gridded/{run.pk}/setup/").content.decode()
    assert ">Ready to start</h2>" in html and "units-help-pr" not in html


def test_file_header(client):
    run = sample_run(client)
    html = client.get(f"/gridded/{run.pk}/setup/").content.decode()
    url = f"/gridded/{run.pk}/setup/header/0/"
    assert f'href="{url}" data-file-header="{SAMPLE_FILE}">Header' in html
    html = client.get(url).content.decode()
    assert f'<h1 class="font-mono text-xl">{SAMPLE_FILE}</h1>' in html
    response = client.get(url, {"format": "text"})
    assert response["Content-Type"] == "text/plain; charset=utf-8"
    text = response.content.decode()
    assert text.startswith("netcdf climpact.sampledata.gridded.3x4.1991-2010 {\ndimensions:\n")
    assert "\ttime = UNLIMITED ; // (7305 currently)" in text or "\ttime = 7305 ;" in text
    assert "\tfloat tmax(time, lat, lon) ;" in text or "\tdouble tmax(time, lat, lon) ;" in text
    assert '\t\ttmax:units = "K" ;' in text and text.endswith("}\n")
    assert client.get(f"/gridded/{run.pk}/setup/header/1/").status_code == 404
    assert Client().get(url).status_code == 404


def test_start_again_keeps_the_results_until_the_new_ones_are_ready(client):
    """After a run, Set-up describes it; starting again with changes keeps the results on
    Map and Files until the new run has finished, then replaces them (#293)."""
    run = sample_run(client)
    client.post(f"/gridded/{run.pk}/setup/", setup_data(run, indices=["fd", "txx"]))
    run_jobs()
    run.refresh_from_db()
    old = run.indices_job
    html = client.get(f"/gridded/{run.pk}/setup/").content.decode()
    assert f'href="/gridded/{run.pk}/setup/" data-tab="setup" aria-current="page"' in html
    assert ">This run</h2>" in html and "<strong>Calculated</strong>" in html
    assert "<strong>Wrote</strong> 4 files for 2 indices," in html
    assert "<strong>Nothing changed yet.</strong>" in html and ">Start again with changes<" in html
    assert "The results on Map and Files stay until the new run finishes" in html
    html = client.post(
        f"/gridded/{run.pk}/checks",
        setup_data(run, base_start=1995, indices=["fd", "txx"]),
        HTTP_HX_REQUEST="true",
    ).content.decode()
    assert "<strong>Changed:</strong> Base period." in html

    response = client.post(
        f"/gridded/{run.pk}/setup/", setup_data(run, base_start=1995, indices=["fd", "txx"])
    )
    assert response.status_code == 302 and response["Location"] == f"/gridded/{run.pk}/setup/"
    run.refresh_from_db()
    assert run.indices_job == old and run.options["base_start"] == 1991
    assert run.next_indices_job is not None and run.job_active
    assert run.next_settings["options"]["base_start"] == 1995
    html = client.get(f"/gridded/{run.pk}/setup/").content.decode()
    assert ">Calculating again</h2>" in html and "Follow its progress on Map" in html
    html = client.get(f"/gridded/{run.pk}/").content.decode()
    assert "Explore the indices" in html and "base 1991–2010" in html  # the old results
    assert "Waiting to start" in client.get("/gridded/").content.decode()
    # A second start waits for this one.
    client.post(f"/gridded/{run.pk}/setup/", setup_data(run, indices=["fd"]))
    assert Job.objects.filter(kind="gridded-indices").count() == 2

    (job,) = run_jobs()
    assert job.status == Status.SUCCEEDED
    html = client.get(f"/gridded/{run.pk}/").content.decode()
    run.refresh_from_db()
    assert run.indices_job == job and run.next_indices_job is None and not run.next_settings
    assert run.options["base_start"] == 1995 and "base 1995–2010" in html
    assert not Job.objects.filter(pk=old.pk).exists() and not old.output_dir.exists()

    # A new start that fails keeps the results, and Set-up says so.
    client.post(f"/gridded/{run.pk}/setup/", setup_data(run, base_start=1991, indices=["fd"]))
    run.refresh_from_db()
    pending = run.next_indices_job
    params = dict(pending.params, input_files=["/no/such/file.nc"])
    Job.objects.filter(pk=pending.pk).update(params=params)
    (failed,) = run_jobs()
    assert failed.status == Status.FAILED
    html = client.get(f"/gridded/{run.pk}/setup/").content.decode()
    run.refresh_from_db()
    assert run.indices_job == job and run.next_indices_job == failed
    assert "The last start did not finish." in html and "/no/such/file.nc" in html
    assert (
        ">This run</h2>" in html
        and "Explore the indices" in client.get(f"/gridded/{run.pk}/").content.decode()
    )


def test_preflight_uses_the_core_reader(client, tmp_path):
    other = tmp_path / "other.nc"
    shutil.copy(GRIDS / "grid_stations_pr.nc", other)
    with netCDF4.Dataset(other, "a") as nc:
        nc["time"][:] = nc["time"][:] + 1  # every date a day later
    response = client.post(
        "/gridded/new/", {"paths": f"{GRIDS / 'grid_stations_tas.nc'}\n{other}", "action": "use"}
    )
    run = GriddedRun.objects.get(pk=response["Location"].split("/")[2])
    response = client.post(
        f"/gridded/{run.pk}/setup/", setup_data(run, base_start=1971, base_end=2000)
    )
    html = response.content.decode()
    assert "dates differ" in html or "cannot be read together" in html
    assert not Job.objects.exists()


# ---- A run: jobs, Map and Files ---------------------------------------------------------------


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
    response = client.post(f"/gridded/{run.pk}/setup/", data)
    assert response.status_code == 302 and response["Location"] == f"/gridded/{run.pk}/"
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

    html = client.get(f"/gridded/{run.pk}/").content.decode()
    assert "Waiting to start" in html and "hx-get" in html
    assert ">calculating</span>" in html and "Run again with other files" not in html
    html = client.get(f"/gridded/{run.pk}/files/").content.decode()
    assert "The files are listed here once the run has finished." in html
    jobs = run_jobs()
    assert [j.status for j in jobs] == [Status.SUCCEEDED, Status.SUCCEEDED], [j.error for j in jobs]
    run.refresh_from_db()
    assert run.thresholds_job.result["files"] == [
        "climpact.sampledata.gridded.3x4.1991-2010.thresholds.1991-2010.nc"
    ]
    names = sorted(run.indices_job.result["files"])
    assert "rx3day_ANN_climpact_historical_NA_1991-2010.nc" in names
    assert "spi_MON_climpact_historical_NA_1991-2010.nc" in names
    assert "trends.nc" in names  # trends are on by default (#290)
    assert len(names) == 10  # txx, fd, rx1day, rx3day: MON and ANN; spi: MON; trends.nc
    assert sorted(p.name for p in copy_to.iterdir()) == sorted(
        names + run.thresholds_job.result["files"]
    )

    # The progress fragment asks for a reload once everything has finished.
    response = client.get(f"/gridded/{run.pk}/progress?was_active=1", HTTP_HX_REQUEST="true")
    assert response["HX-Refresh"] == "true"
    html = client.get(f"/gridded/{run.pk}/progress").content.decode()
    assert "hx-get" not in html and f'on <a href="/gridded/{run.pk}/files/">Files</a>' in html

    # The run's context bar and its Map tab.
    html = client.get(f"/gridded/{run.pk}/").content.decode()
    assert '<h1 class="context-bar__name">Sample grid, 1991–2010</h1>' in html
    assert '<a href="/gridded/">Gridded</a></li><li><span aria-current="page">run</span>' in html
    for part in (
        "3 × 4 cells, 12 with data",
        "1991–2010, standard",
        "base 1991–2010",
        "5 indices, 9 files",
        "kept until ",
    ):
        assert f">{part}" in html, part
    assert "Forget this run" in html and "Run again with other files" in html
    assert "Download all (zip, " in html and "gridded-progress" not in html
    assert f'href="/gridded/{run.pk}/" data-tab="map" aria-current="page"' in html
    assert f'href="/gridded/{run.pk}/files/" data-tab="files">' in html
    assert f'href="/gridded/{run.pk}/setup/" data-tab="setup">' in html
    assert "steps__" not in html
    assert "Explore the indices" in html and "txx, 2010" in html  # txx annual, last year
    assert 'class="gmap__svg"' in html and html.count('class="gmap__cell') == 12
    assert "View as table" in html and "Choose a cell" in html
    assert "rx3day_ANN_climpact_historical_NA_1991-2010.nc" in html

    # A chosen cell, time step and file, as htmx asks for them.
    spi = "spi_MON_climpact_historical_NA_1991-2010.nc"
    response = client.get(
        f"/gridded/{run.pk}/explore",
        {"file": spi, "t": 5, "scale": 2, "cell": "0,1"},
        HTTP_HX_REQUEST="true",
    )
    html = response.content.decode()
    assert response.status_code == 200 and "<html" not in html
    assert "1991-06" in html and "(12-month scale)" in html
    assert "gmap__cell--selected" in html
    assert "cell=0%2C1" in response["HX-Push-Url"]
    assert response["HX-Push-Url"].startswith(f"/gridded/{run.pk}/?")
    # The results page's old address keeps working.
    response = client.get(f"/gridded/{run.pk}/results", {"file": spi, "t": 5})
    assert response.status_code == 301
    assert response["Location"] == f"/gridded/{run.pk}/?file={spi}&t=5"

    # The values shown are the file's.
    path = run.indices_job.output_dir / "txx_ANN_climpact_historical_NA_1991-2010.nc"
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
    html = client.get(f"/gridded/{run.pk}/").content.decode()
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
    assert len(archive.namelist()) == 11  # 9 index files, trends.nc and the thresholds
    assert all(n.startswith("climpact_gridded/") for n in archive.namelist())

    # The Files tab: the index files by theme, Heat first and open, each group's zip.
    html = client.get(f"/gridded/{run.pk}/files/").content.decode()
    assert '<span class="font-semibold">Heat</span>' in html
    heat = html.index('<span class="font-semibold">Heat</span>')
    assert html.count('class="gridded-group__details" open') == 1
    assert 'class="gridded-group__details" open' in html[html.rfind("<details", 0, heat) : heat]
    labels = [
        label
        for label in ("Heat", "Cold", "Rain", "Drought", "Other")
        if f'<span class="font-semibold">{label}</span>' in html
    ]
    assert labels == ["Heat", "Cold", "Rain", "Drought"]
    assert '<th scope="row" class="code font-medium">Rx3day</th>' in html
    assert ">Wettest 3\xa0days<" in html and ">txx, day_of_txx<" in html
    assert "9 files · " in html and f"/gridded/{run.pk}/zip/theme/heat.zip" in html
    assert "The 11 links as a text file, for <code>wget -i</code>" in html
    assert "Copied to <span" in html and str(copy_to) in html
    assert "climpact.sampledata.gridded.3x4.1991-2010.thresholds.1991-2010.nc" in html
    assert "Thresholds, base 1991–2010" in html and "Reading the files" in html
    assert f'href="/gridded/{run.pk}/file/' in html and ">trends.nc</a>" in html  # #290
    response = client.get(f"/gridded/{run.pk}/zip/theme/rain.zip")
    archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
    assert sorted(Path(n).name.split("_")[0] for n in archive.namelist()) == [
        "rx1day",
        "rx1day",
        "rx3day",
        "rx3day",
    ]
    assert client.get(f"/gridded/{run.pk}/zip/theme/nope.zip").status_code == 404
    assert client.get(f"/gridded/{run.pk}/zip/colour/heat.zip").status_code == 404
    html = client.get(f"/gridded/{run.pk}/files/", {"by": "frequency"}).content.decode()
    assert '<span class="font-semibold">Annual</span>' in html and "hue-dot" not in html
    html = client.get(f"/gridded/{run.pk}/files/", {"by": "variable"}).content.decode()
    assert '<span class="font-semibold">Precipitation</span>' in html
    assert '<option value="variable" selected>' in html

    # The links for wget work without the session, with the run's key only.
    response = client.get(f"/gridded/{run.pk}/links.txt")
    links = response.content.decode().splitlines()
    assert len(links) == 11 and all(link.startswith("http://testserver/gridded/") for link in links)
    stranger = Client()
    link = next(link for link in links if "txx_ANN" in link)
    response = stranger.get(link.removeprefix("http://testserver"))
    assert response.status_code == 200
    assert b"".join(response.streaming_content).startswith(inspection.NETCDF_SIGNATURES)
    assert stranger.get(link.removeprefix("http://testserver").split("?")[0]).status_code == 404
    assert stranger.get(link.removeprefix("http://testserver") + "x").status_code == 404

    # The run's record.
    record = client.get(f"/gridded/{run.pk}/run.json").json()
    assert record["run"] == "Sample grid, 1991–2010" and record["inputs"][0]["file"] == SAMPLE_FILE
    import hashlib

    assert record["inputs"][0]["sha256"] == hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
    assert record["settings"]["indices"] == ["txx", "fd", "rx1day", "spi", "rxdday"]
    assert "checked" not in record["settings"] and record["grid"]["cells"] == [3, 4]
    assert [j["kind"] for j in record["jobs"]] == ["thresholds", "indices"]
    assert "climpact" in record["versions"] and record["software"].startswith("climpact ")
    log = client.get(f"/gridded/{run.pk}/climpact.log").content.decode()
    assert "# thresholds:" in log and "# indices:" in log and "attempt 1 started" in log

    # Gridded lists it.
    html = client.get("/gridded/").content.decode()
    assert f'<a href="/gridded/{run.pk}/" title="Sample grid, 1991–2010">' in html
    assert (
        ">3 × 4, 1.905° × 1.875°<" in html
        and "1991–2010, file kept" in html
        and ">5 indices<" in html
    )
    assert "Finished " in html and "gridded-state--done" in html


def test_indices_with_a_thresholds_file(client):
    """grid_future (2001-2020) with the thresholds of grid_stations, as R's reference run."""
    response = client.post(
        "/gridded/new/",
        {
            "paths": f"{GRIDS / 'grid_stations_tas.nc'}\n{GRIDS / 'grid_stations_pr.nc'}",
            "action": "use",
        },
    )
    hist = GriddedRun.objects.get(pk=response["Location"].split("/")[2])
    client.post(
        f"/gridded/{hist.pk}/setup/",
        setup_data(hist, task="thresholds", base_start=1971, base_end=2000),
    )
    (thresholds_job,) = run_jobs()
    assert thresholds_job.status == Status.SUCCEEDED, thresholds_job.error
    thresholds = thresholds_job.output_dir / thresholds_job.result["files"][0]

    response = client.post(
        "/gridded/new/",
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
    response = client.post(f"/gridded/{future.pk}/setup/", data)
    assert response.status_code == 302, response.content.decode()[:2000]
    future.refresh_from_db()
    assert future.thresholds_job is None and future.indices_job.params["thresholds_file"] == str(
        thresholds
    )
    (job,) = run_jobs()
    assert job.status == Status.SUCCEEDED, job.error
    assert sorted(job.result["files"]) == [
        "r95p_ANN_climpact_historical_NA_2001-2020.nc",
        "trends.nc",
        "tx90p_ANN_climpact_historical_NA_2001-2020.nc",
        "tx90p_MON_climpact_historical_NA_2001-2020.nc",
    ]
    # Gridded names the run whose thresholds file the scenario read.
    html = client.get("/gridded/").content.decode()
    hist.refresh_from_db()
    assert f"From {hist.display_name}" in html and "1971–2000, file kept" in html
    html = client.get(f"/gridded/{hist.pk}/").content.decode()
    assert "This run made a thresholds file only, so there is no map." in html
    html = client.get(f"/gridded/{hist.pk}/files/").content.decode()
    assert "This run made no index files" in html and "Download all (zip," in html


def test_job_failure_is_shown(client):
    run = sample_run(client)
    client.post(f"/gridded/{run.pk}/setup/", setup_data(run, indices=["fd"]))
    run.refresh_from_db()
    params = dict(run.indices_job.params, input_files=["/no/such/file.nc"])
    Job.objects.filter(pk=run.indices_job.pk).update(params=params)
    (job,) = run_jobs()
    assert job.status == Status.FAILED
    html = client.get(f"/gridded/{run.pk}/").content.decode()
    assert "The calculation failed." in html and "/no/such/file.nc" in html and "Try again" in html
    assert "Run again with other files" in html and "Download all" not in html
    html = client.get(f"/gridded/{run.pk}/files/").content.decode()
    assert "The run did not finish, so it has no files." in html
    html = client.get("/gridded/").content.decode()
    assert "gridded-state--failed" in html and ">Failed<" in html


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
        f"/gridded/{run.pk}/setup/",
        f"/gridded/{run.pk}/files/",
        f"/gridded/{run.pk}/rename/",
        f"/gridded/{run.pk}/results",
        f"/gridded/{run.pk}/download.zip",
        f"/gridded/{run.pk}/run.json",
        f"/gridded/{run.pk}/links.txt",
        f"/gridded/{run.pk}/delete",
    ):
        assert other.get(url).status_code == 404, url
    assert f"/gridded/{run.pk}/" not in other.get("/gridded/").content.decode()


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
    html = client.get(f"/gridded/{run.pk}/delete").content.decode()
    assert "Forget Sample grid, 1991–2010?" in html and "can’t be recovered" in html
    assert GriddedRun.objects.exists()
    response = client.post(f"/gridded/{run.pk}/delete")
    assert response.status_code == 302 and not GriddedRun.objects.exists()
    assert SAMPLE.is_file()  # a file read in place is never deleted


# ---- Gridded: the list, names and states (#289) -------------------------------------------------


def test_gridded_list_with_no_runs(client):
    html = client.get("/gridded/").content.decode()
    assert "<h1>Gridded</h1>" in html and 'href="/gridded/new/"' in html
    assert "New gridded run" in html and "No runs yet." in html
    assert 'action="/gridded/sample"' in html and "gridded-runs" not in html
    for box in ("Stations or a grid?", "Scenarios", "Try it", "Gridded help"):
        assert box in html, box
    assert "steps__" not in html and "Continue where you left off" not in html


def test_gridded_list_and_states(client):
    run = sample_run(client)
    html = client.get("/gridded/").content.decode()
    assert "Your gridded runs, most recently changed first" in html
    assert f'<a href="/gridded/{run.pk}/" title="Sample grid, 1991–2010">' in html
    assert ">Not started<" in html and "gridded-state--new" in html
    assert "Runs are kept on this computer for 7 days" in html
    # A variable in units Climpact cannot read: the state says which.
    files = [dict(run.files[0])]
    files[0]["variables"] = [dict(v) for v in files[0]["variables"]]
    files[0]["variables"][2]["units"] = "furlongs"
    GriddedRun.objects.filter(pk=run.pk).update(files=files)
    html = client.get("/gridded/").content.decode()
    assert ">Not started: precipitation units<" in html and "gridded-state--problem" in html
    with override_settings(IS_HOSTED=True, GRIDDED_ENABLED=True):
        html = client.get("/gridded/").content.decode()
    assert "Runs are kept in this browser for 7 days" in html


def test_rename_a_run(client):
    run = sample_run(client)
    html = client.get(f"/gridded/{run.pk}/rename/").content.decode()
    assert 'value="Sample grid, 1991–2010"' in html and "Rename the run" in html
    response = client.post(f"/gridded/{run.pk}/rename/", {"name": "  SE Australia  "})
    assert response.status_code == 302 and response["Location"] == f"/gridded/{run.pk}/"
    run.refresh_from_db()
    assert run.name == "SE Australia" and run.display_name == "SE Australia"
    client.post(f"/gridded/{run.pk}/rename/", {"name": ""})
    run.refresh_from_db()
    assert run.name == "" and run.display_name == "Sample grid, 1991–2010"


def _info(name: str, ny: int, nx: int, y_range, x_range, first="1961-01-01", last="2020-12-31"):
    return inspection.FileInfo(
        path=f"/data/{name}",
        name=name,
        ny=ny,
        nx=nx,
        y_range=y_range,
        x_range=x_range,
        first=first,
        last=last,
        calendar="standard",
    ).to_json()


def test_default_names_and_spacing():
    from climpact_web.gridded import runs

    cmip = GriddedRun(
        files=[
            _info(
                "tasmax_day_ACCESS-CM2_ssp370_r1i1p1f1_gn_20150101-21001231.nc",
                145,
                192,
                [-90.0, 90.0],
                [0.0, 358.125],
                "2015-01-01",
                "2100-12-31",
            )
        ]
    )
    assert runs.default_name(cmip) == "ACCESS-CM2 ssp370 r1i1p1f1 gn 1.25° × 1.875°, 2015–2100"
    era5 = GriddedRun(files=[_info("era5_SEA_pr.nc", 47, 55, [-44.0, -32.5], [140.0, 153.5])])
    assert runs.default_name(era5) == "era5 SEA 0.25°, 1961–2020"
    assert runs.grid_text(runs.grid_summary(era5)) == "47 × 55, 0.25°"
    assert runs.period_text(runs.grid_summary(era5)) == "1961–2020"
    unreadable = GriddedRun(files=[inspection.FileInfo(path="/x.nc", name="x.nc").to_json()])
    assert runs.default_name(unreadable) == "x"
    assert runs.grid_text(runs.grid_summary(unreadable)) == "–"


def test_short_durations():
    from climpact_web.gridded.runs import short_duration

    assert short_duration(dt.timedelta(seconds=45)) == "45 s"
    assert short_duration(dt.timedelta(minutes=21, seconds=30)) == "21 min"
    assert short_duration(dt.timedelta(hours=2, minutes=5)) == "2 h 5 min"

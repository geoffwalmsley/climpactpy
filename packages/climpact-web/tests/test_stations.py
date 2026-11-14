"""Single-station step 1 (#76): uploading the station file or the sample, the checks and
their messages, the metadata form (with and without htmx), the data summary, ownership
and retention."""

import datetime as dt
import re
import uuid
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.retention import purge_expired
from climpact_web.jobs.views import OWNER_KEY
from climpact_web.stations import preview
from climpact_web.stations.forms import MIN_BASE_DAYS, MetadataForm
from climpact_web.stations.models import StationAnalysis, Step, stations_dir
from climpact_web.stations.station_file import core_error_message, inspect_station_bytes
from climpact_web.stations.views import SAMPLE_NAME, sample_bytes

REPO = Path(__file__).resolve().parents[3]
SYDNEY = REPO / "reference" / "input" / "sydney_observatory_hill_1936-2015.txt"
HEADER = "year month day prcp tmax tmin\n"


def rows(start="2000-01-01", days=800) -> str:
    first = dt.date.fromisoformat(start)
    lines = []
    for k in range(days):
        d = first + dt.timedelta(days=k)
        lines.append(f"{d.year} {d.month} {d.day} {k % 7 * 0.5:.1f} {20 + k % 5} {10 + k % 3}")
    return "\n".join(lines) + "\n"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    settings.JOB_RETENTION_DAYS = 7
    return settings


def upload(client, text, name="my station.txt", url="/station/"):
    data = text.encode() if isinstance(text, str) else text
    return client.post(url, {"station_file": SimpleUploadedFile(name, data)})


def loaded(client, text=None, name="my station.txt") -> StationAnalysis:
    response = upload(client, text or rows(), name)
    assert response.status_code == 302, response.content.decode()[:2000]
    return StationAnalysis.objects.get(pk=response["Location"].split("/")[2])


def metadata(**changes) -> dict:
    return {
        "station_name": "Testville",
        "latitude": "-33.9",
        "longitude": "151.2",
        "base_start": "2000",
        "base_end": "2001",
        **changes,
    }


# ---- The upload page -------------------------------------------------------------------


@pytest.mark.django_db
def test_upload_page_works_without_javascript(client):
    html = client.get("/station/").content.decode()
    # A plain multipart form with a real file input: ui.js only adds drag and drop.
    assert re.search(r'<form method="post" action="/station/" enctype="multipart/form-data"', html)
    assert re.search(r'<input type="file" name="station_file"[^>]*accept="[^"]*\.txt', html)
    assert "Drop a file here or choose one" in html
    assert re.search(r'<form method="post" action="/station/sample">', html)
    assert "kept for 7 days after your last change" in html
    assert 'aria-current="step"' in html and "Load data" in html


@pytest.mark.django_db
def test_upload_creates_an_analysis_named_after_the_file(client):
    response = upload(client, rows(), name="Perth Airport 1961-2020.txt")
    analysis = StationAnalysis.objects.get()
    assert response["Location"] == f"/station/{analysis.pk}/load"
    assert analysis.station_name == "Perth Airport 1961-2020"  # the stem, as the CLI does
    assert analysis.file_name == "Perth Airport 1961-2020.txt"
    assert analysis.station_file == stations_dir() / str(analysis.pk) / "station.txt"
    assert analysis.station_file.read_text() == rows()
    assert analysis.summary["first_date"] == "2000-01-01"
    assert analysis.summary["days"] == 800
    assert analysis.step == Step.UPLOAD and analysis.latitude is None
    assert analysis.owner == client.session[OWNER_KEY]


@pytest.mark.django_db
def test_odd_file_names_become_safe_station_names(client):
    analysis = loaded(client, name="../my/sta:tion*.csv")
    assert analysis.station_name == "sta_tion_"
    assert analysis.station_file.name == "station.txt"


@pytest.mark.django_db
def test_utf8_bom_and_latin1_header_are_read(client):
    analysis = loaded(client, "﻿".encode() + rows().encode())
    assert analysis.summary["rows"] == 800  # the BOM did not make row 1 a header
    assert not analysis.station_file.read_bytes().startswith(b"\xef\xbb\xbf")
    analysis = loaded(client, "année mois jour p tx tn\n".encode("latin-1") + rows().encode())
    assert analysis.summary["rows"] == 800


# ---- Every input error, in plain language, at its line -----------------------------------

BAD_FILES = {
    # name: (contents, expected message, line shown)
    "short_row": (
        HEADER + "2000 1 1 0 20 10\n2000 1 2 0.4 21\n",
        "Line 3 has 5 values; each line needs 6: year, month, day, precipitation, "
        "maximum and minimum temperature.",
        "2000 1 2 0.4 21",
    ),
    "long_row": (
        "2000 1 1 0 20 10\n\n2000 1 2 0 21 11 99\n",
        "Line 3 has 7 values",  # the blank line is counted: line numbers are the file's
        "2000 1 2 0 21 11 99",
    ),
    "not_a_number": (
        "2000 1 1 0 20 10\n2000 1 2 0,4 21 11\n2000 1 3 abc 21 11\n",
        "Line 2 has 7 values",  # a decimal comma is a separator, as in R
        "2000 1 2 0,4 21 11",
    ),
    "text_value": (
        "2000 1 1 0 20 10\n2000 1 3 abc 21 11\n",
        "Line 2: “abc” in the precipitation column is not a number.",
        "2000 1 3 abc 21 11",
    ),
    "na_value": (
        "2000 1 1 0 20 10\n2000 1 2 0 NA 11\n",
        "Line 2: “NA” in the maximum temperature column is not a number. "
        "Write missing values as -99.9.",
        "2000 1 2 0 NA 11",
    ),
    "empty": ("", "The file is empty.", None),
    "header_only": (HEADER, "The file has no data rows, only a header.", None),
    "spreadsheet": (b"PK\x03\x04\x14\x00rest", "This is not a text file.", None),
    "binary": (b"\x00\x01\x02\x03" * 10, "This is not a text file.", None),
    "no_valid_dates": (
        "2001 2 29 0 20 10\n2001 13 1 0 20 10\n",
        "None of the rows has a valid date.",
        None,
    ),
    "last_before_first": (
        "2000 1 2 0 20 10\n1999 12 31 0 20 10\n",
        "The rows are not in date order: the last row (1999-12-31) is dated before the "
        "first (2000-01-02). Sort the file by date.",
        None,
    ),
}


@pytest.mark.django_db
@pytest.mark.parametrize("case", BAD_FILES, ids=str)
def test_bad_files_are_refused_with_a_readable_message(client, case):
    contents, message, line = BAD_FILES[case]
    response = upload(client, contents, name="bad.txt")
    assert response.status_code == 200
    assert not StationAnalysis.objects.exists()
    assert not stations_dir().exists() or not any(stations_dir().iterdir())
    html = response.content.decode()
    if case == "empty":  # refused by the form field, before the file is read
        assert 'class="field__error"' in html and message in html
        return
    assert "bad.txt was not loaded" in html and "data-error-summary" in html
    assert message in html.replace("&#x27;", "'")
    if line:
        assert f'<code class="file-problems__line">{line}</code>' in html
    assert "Traceback" not in html and "could not convert" not in html


@pytest.mark.parametrize(
    "case",
    ["short_row", "long_row", "text_value", "na_value", "no_valid_dates", "last_before_first"],
)
def test_every_core_reader_error_has_its_own_message(case, tmp_path):
    """The core raises for each of these files; the web app explains each one itself
    rather than showing the core's text (or a generic message)."""
    from climpact.io.station import merged_rows, read_station_file

    contents, message, _ = BAD_FILES[case]
    path = tmp_path / "s.txt"
    path.write_text(contents)
    with pytest.raises(ValueError) as raised:
        merged_rows(read_station_file(path))
    inspection = inspect_station_bytes(contents.encode())
    assert not inspection.ok
    assert message in inspection.problems[0].message
    assert not inspection.problems[0].message.startswith("The file could not be read")
    if case in ("no_valid_dates", "last_before_first"):  # reported from the core's error
        assert core_error_message(str(raised.value)) == inspection.problems[0].message


def test_only_the_first_problems_are_listed():
    text = "".join(f"2000 1 {d} 0 20\n" for d in range(1, 26))
    inspection = inspect_station_bytes(text.encode())
    assert inspection.problem_count == 25 and len(inspection.problems) == 10
    assert inspection.hidden_problems == 15


def test_unknown_core_errors_are_still_shown():
    assert core_error_message("something new") == "The file could not be read: something new"


@pytest.mark.django_db
def test_hidden_problems_are_counted_on_the_page(client):
    text = "".join(f"2000 1 {d} 0 20\n" for d in range(1, 26))
    html = upload(client, text).content.decode()
    assert "it has 25 problems" in html and "And 15 more lines like these." in html


# ---- Warnings: what R accepts silently -------------------------------------------------


def test_warnings_for_dates_r_drops_or_reorders():
    text = (
        "2000 1 1 0 20 10\n2000 1 3 0 20 10\n2000 1 2 0 20 10\n2000 1 2 1 21 11\n"
        "1999 2 29 0 20 10\n2000 1 5 0 20 10\n"
    )
    inspection = inspect_station_bytes(text.encode())
    assert inspection.ok
    warnings = " ".join(inspection.warnings)
    assert "1 row has a date that does not exist (line 5: 1999-2-29)" in warnings
    assert "The rows are not in date order. They are sorted by date." in warnings
    assert "1 date appears more than once (2000-01-02, lines 3, 4)" in warnings
    summary = inspection.summary
    assert (summary["first_date"], summary["last_date"], summary["days"]) == (
        "2000-01-01",
        "2000-01-05",
        5,
    )
    tmax = summary["variables"][1]
    assert (tmax["present"], tmax["missing"]) == (4, 1)  # 4 January has no row


def test_rows_outside_the_first_and_last_dates_are_reported():
    text = "2000 1 2 0 20 10\n1999 6 1 0 20 10\n2000 1 9 0 20 10\n"
    inspection = inspect_station_bytes(text.encode())
    assert "1 row is dated outside the range" in inspection.warnings[0]
    assert "(line 2)" in inspection.warnings[0]


def test_a_variable_with_no_values_is_reported():
    text = "".join(f"2000 1 {d} -99.9 20 10\n" for d in range(1, 10))
    inspection = inspect_station_bytes(text.encode())
    assert inspection.warnings == ["The file has no precipitation values: every value is missing."]


@pytest.mark.django_db
def test_warnings_are_shown_on_the_load_page(client):
    analysis = loaded(client, "2000 1 1 0 20 10\n2001 2 29 0 20 10\n2000 1 9 0 20 10\n")
    html = client.get(f"/station/{analysis.pk}/load").content.decode()
    assert "Something to check in the file" in html and "does not exist" in html


# ---- The sample --------------------------------------------------------------------------


def test_bundled_sample_is_the_r_sample():
    assert sample_bytes() == SYDNEY.read_bytes()


@pytest.mark.django_db
def test_sample_loads_in_one_click(client):
    response = client.post("/station/sample")
    analysis = StationAnalysis.objects.get()
    assert response["Location"] == f"/station/{analysis.pk}/load"
    assert (analysis.station_name, analysis.latitude, analysis.longitude) == (
        "sydney_observatory_hill_1936-2015",
        -33.86,
        151.21,
    )
    assert analysis.metadata_complete and analysis.source == "sample"
    html = client.get(response["Location"]).content.decode()
    assert "1936-01-01 to 2015-12-31" in html and "Sample data" in html
    assert 'value="sydney_observatory_hill_1936-2015"' in html
    # straight on to the next step, with nothing to type
    response = client.post(response["Location"], metadata(**{
        "station_name": analysis.station_name, "latitude": "-33.86", "longitude": "151.21",
        "base_start": "1971", "base_end": "2000"}))  # fmt: skip
    assert response["Location"] == f"/station/{analysis.pk}/quality"


@pytest.mark.django_db
def test_sample_get_goes_to_the_upload_page_and_the_file_downloads(client):
    assert client.get("/station/sample")["Location"] == "/station/"
    assert not StationAnalysis.objects.exists()
    response = client.get("/station/sample.txt")
    assert response.content == SYDNEY.read_bytes()
    assert SAMPLE_NAME in response["Content-Disposition"]


# ---- The data summary ------------------------------------------------------------------


@pytest.mark.django_db
def test_load_page_summarises_the_data(client):
    response = client.post("/station/sample")
    html = client.get(response["Location"]).content.decode()
    assert "Missing values by variable" in html
    # Sydney: 29220 days; 7 precipitation and 58 temperature values missing
    cells = re.sub(r"\s+", " ", html)
    assert (
        '<td class="num">29213</td> <td class="num">7</td> <td class="num">under 0.1%</td>' in cells
    )
    assert '<td class="num">29162</td> <td class="num">58</td> <td class="num">0.2%</td>' in cells
    assert html.count('<svg viewBox="0 0 960 170" role="img"') == 2  # the static preview
    assert "CHART HOOK" not in html  # a template comment, for #75/#77
    assert "Days with data in each year" in html and '<th scope="row">1936</th>' in html
    assert "kept for 7 days after your last change" in html


def test_preview_panels_break_at_gaps():
    summary = inspect_station_bytes(rows(days=400).encode()).summary
    summary["preview"]["tmax"][3] = None
    temperature, prcp = preview.panels(summary["preview"])
    assert temperature.key == "temperature" and prcp.key == "prcp"
    assert temperature.paths[0]["d"].count("M") == 2  # a new stroke after the gap
    assert [p["token"] for p in temperature.paths] == ["--chart-tmax", "--chart-tmin"]
    assert prcp.y_labels[0]["text"] == "0"


@pytest.mark.django_db
def test_daily_series_csv(client):
    analysis = loaded(client, "2000 1 1 0 20 10\n2000 1 3 -99.9 21.5 11\n")
    response = client.get(f"/station/{analysis.pk}/series.csv")
    assert response["Content-Type"].startswith("text/csv")
    assert response.content.decode().splitlines() == [
        "date,prcp,tmax,tmin",
        "2000-01-01,0,20,10",
        "2000-01-02,,,",
        "2000-01-03,,21.5,11",
    ]


# ---- The metadata form -----------------------------------------------------------------


def form_errors(summary, **changes):
    form = MetadataForm(metadata(**changes), summary=summary)
    form.is_valid()
    return form


@pytest.fixture
def summary():
    return inspect_station_bytes(rows("1990-01-01", 365 * 11).encode()).summary  # 1990-2000


def test_metadata_matches_the_r_app_fields_and_defaults():
    form = MetadataForm()
    assert list(form.fields) == ["station_name", "latitude", "longitude", "base_start", "base_end"]
    assert (form["base_start"].initial, form["base_end"].initial) == (None, None)
    assert StationAnalysis().base_start == 1971 and StationAnalysis().base_end == 2000


def test_min_base_days_matches_the_core():
    from climpact.thresholds import MIN_BASE_DAYS as CORE

    assert MIN_BASE_DAYS == CORE


@pytest.mark.parametrize(
    "changes, field, message",
    [
        ({"station_name": ""}, "station_name", "Enter a station name."),
        ({"station_name": ".hidden"}, "station_name", "not starting with a dot"),
        ({"station_name": "a/b"}, "station_name", "Use letters, digits"),
        ({"latitude": "-90.5"}, "latitude", "Latitude must be between -90 and 90."),
        ({"latitude": "north"}, "latitude", "Enter the latitude as a number"),
        ({"longitude": "181"}, "longitude", "Longitude must be between -180 and 180."),
        ({"longitude": ""}, "longitude", "Enter the longitude."),
        ({"base_start": "1995", "base_end": "1994"}, "base_end", "must not be before"),
        ({"base_start": "1961", "base_end": "1980"}, "base_end", "the file covers 1990 to 2000"),
        ({"base_start": "2001", "base_end": "2010"}, "base_end", "has no data"),
        ({"base_start": "x"}, "base_start", "Enter a year, e.g. 1971."),
    ],
)  # fmt: skip
def test_metadata_errors(summary, changes, field, message):
    form = form_errors(summary, **changes)
    assert message in " ".join(form.errors[field])


def test_metadata_warnings(summary):
    form = form_errors(summary, latitude="0", base_start="1981", base_end="2010")
    assert form.is_valid()
    assert "Southern Hemisphere" in form.warnings["latitude"][0]
    assert (
        "covers only 11 years of the base period (1990 to 2000)" in form.warnings["base_period"][0]
    )
    # The last year of the data is the only base year covered: 365 days, enough
    form = form_errors(summary, base_start="2000", base_end="2030")
    assert form.is_valid() and "covers only 1 year" in form.warnings["base_period"][0]
    form = form_errors(summary, base_start="1990", base_end="2000")
    assert form.is_valid() and form.warnings == {}


def test_too_little_base_period_data_is_a_warning():
    summary = inspect_station_bytes(rows("2000-07-01", 400).encode()).summary
    form = form_errors(summary, base_start="1971", base_end="2000")
    assert form.is_valid()  # R runs too; the percentile indices are just not calculated
    assert "cannot be calculated" in form.warnings["base_period"][0]


@pytest.mark.django_db
def test_metadata_without_javascript_shows_every_error(client):
    analysis = loaded(client)
    html = client.post(
        f"/station/{analysis.pk}/load", metadata(latitude="99", station_name="")
    ).content.decode()
    assert "There are 2 problems with the form" in html
    assert '<a href="#id_station_name">' in html and '<a href="#id_latitude">' in html
    assert 'aria-invalid="true"' in html
    analysis.refresh_from_db()
    assert analysis.step == Step.UPLOAD and analysis.latitude is None


@pytest.mark.django_db
def test_htmx_validates_one_group_as_it_changes(client):
    analysis = loaded(client)
    html = client.get(f"/station/{analysis.pk}/load").content.decode()
    for group in ("station_name", "latitude", "longitude", "base_period"):
        assert f'id="group-{group}" hx-post="/station/{analysis.pk}/load/validate"' in html
        assert f'hx-vals=\'{{"group": "{group}"}}\'' in html
    assert 'hx-trigger="change" hx-include="closest form"' in html

    url = f"/station/{analysis.pk}/load/validate"
    fragment = client.post(url, {**metadata(latitude="123", longitude=""), "group": "latitude"})
    text = fragment.content.decode()
    assert text.lstrip().startswith('<div class="field-group" id="group-latitude"')
    assert "Latitude must be between -90 and 90." in text
    assert "Enter the longitude." not in text  # only the group that changed
    assert "<html" not in text

    data = {**metadata(base_start="1950", base_end="1960"), "group": "base_period"}
    text = client.post(url, data).content.decode()
    assert "has no data: the file covers 2000 to 2002" in text and 'id="id_base_start"' in text
    text = client.post(url, {**metadata(latitude="0"), "group": "latitude"}).content.decode()
    assert "Southern Hemisphere" in text and "field__error" not in text
    assert client.post(url, {"group": "nope"}).status_code == 400
    assert client.get(url).status_code == 405


@pytest.mark.django_db
def test_continue_saves_and_goes_to_quality_checks(client):
    analysis = loaded(client)
    response = client.post(f"/station/{analysis.pk}/load", metadata())
    assert response["Location"] == f"/station/{analysis.pk}/quality"
    analysis.refresh_from_db()
    assert analysis.step == Step.QC
    assert analysis.metadata == {"name": "Testville", "latitude": -33.9, "longitude": 151.2,
                                 "base_start": 2000, "base_end": 2001}  # fmt: skip
    page = client.get(response["Location"]).content.decode()
    assert "Check quality" in page and f'href="/station/{analysis.pk}/load"' in page
    assert '<a class="steps__link" href="/station/' in page  # step 1 links back


@pytest.mark.django_db
def test_quality_page_needs_step_one_first(client):
    analysis = loaded(client)
    assert (
        client.get(f"/station/{analysis.pk}/quality")["Location"] == f"/station/{analysis.pk}/load"
    )
    assert client.post(f"/station/{analysis.pk}/indices/run-all").status_code == 302
    assert client.post(f"/station/{analysis.pk}/quality/run").status_code == 302
    assert not Job.objects.exists()


@pytest.mark.django_db
def test_changing_metadata_resets_the_later_steps(client):
    analysis = loaded(client)
    client.post(f"/station/{analysis.pk}/load", metadata())
    client.post(f"/station/{analysis.pk}/indices/run-all", {"zip": "on"})
    analysis.refresh_from_db()
    assert analysis.indices_job is not None and analysis.qc_job is not None
    # the same metadata again: nothing to redo
    client.post(f"/station/{analysis.pk}/load", metadata())
    analysis.refresh_from_db()
    assert analysis.indices_job is not None and analysis.step == Step.QC
    first_qc = analysis.qc_job
    client.post(f"/station/{analysis.pk}/load", metadata(latitude="-30"))
    analysis.refresh_from_db()
    assert analysis.indices_job is None and analysis.step == Step.QC
    assert analysis.qc_job != first_qc  # the checks run again (#77)
    # The jobs themselves are kept, with their own retention.
    assert Job.objects.count() == 3


@pytest.mark.django_db
def test_replacing_the_file_keeps_the_metadata(client):
    analysis = loaded(client, name="first.txt")
    client.post(f"/station/{analysis.pk}/load", metadata(station_name="first"))
    response = upload(client, rows("1980-01-01", 400), "second.txt", f"/station/{analysis.pk}/file")
    assert response["Location"] == f"/station/{analysis.pk}/load"
    analysis.refresh_from_db()
    # the name followed the file name, as it was still the default; the rest is kept
    assert (analysis.station_name, analysis.latitude) == ("second", -33.9)
    assert analysis.summary["first_date"] == "1980-01-01" and analysis.step == Step.UPLOAD
    client.post(
        f"/station/{analysis.pk}/load",
        metadata(station_name="My name", base_start="1980", base_end="1980"),
    )
    upload(client, rows(), "third.txt", f"/station/{analysis.pk}/file")
    analysis.refresh_from_db()
    assert analysis.station_name == "My name"
    # a bad file leaves everything as it was
    html = upload(client, "x\n1 2\n", "bad.txt", f"/station/{analysis.pk}/file").content.decode()
    assert "bad.txt was not loaded" in html and "Line 2 has 2 values" in html
    analysis.refresh_from_db()
    assert analysis.file_name == "third.txt"


@pytest.mark.django_db
def test_delete_now(client):
    analysis = loaded(client)
    folder = analysis.folder
    response = client.post(f"/station/{analysis.pk}/delete")
    assert response["Location"] == "/station/"
    assert not StationAnalysis.objects.exists() and not folder.exists()


@pytest.mark.django_db
def test_upload_page_lists_recent_analyses(client):
    analysis = loaded(client, name="perth.txt")
    html = client.get("/station/").content.decode()
    assert "Continue where you left off" in html and f'href="/station/{analysis.pk}/load"' in html
    assert "Continue where you left off" not in Client().get("/station/").content.decode()


# ---- Ownership -------------------------------------------------------------------------


@pytest.mark.django_db
def test_other_sessions_get_404(client):
    analysis = loaded(client)
    other = Client()
    for url in ("load", "series.csv", "quality"):
        assert other.get(f"/station/{analysis.pk}/{url}").status_code == 404
    for url in ("load", "load/validate", "file", "delete", "indices/run-all", "quality/run"):
        assert other.post(f"/station/{analysis.pk}/{url}").status_code == 404
    assert client.get(f"/station/{uuid.uuid4()}/load").status_code == 404
    assert StationAnalysis.objects.exists()


# ---- Retention -------------------------------------------------------------------------


@pytest.mark.django_db
def test_old_analyses_are_purged_with_their_files(client):
    old = loaded(client)
    recent = loaded(client)
    busy = loaded(client)
    busy.indices_job = Job.objects.create(kind="station", owner="x", status=Status.RUNNING)
    busy.save()
    long_ago = timezone.now() - dt.timedelta(days=8)
    StationAnalysis.objects.filter(pk__in=[old.pk, busy.pk]).update(updated_at=long_ago)
    stray = stations_dir() / str(uuid.uuid4())
    stray.mkdir()
    import os

    os.utime(stray, (long_ago.timestamp(), long_ago.timestamp()))

    purged = purge_expired()
    assert purged.other == 1
    assert set(StationAnalysis.objects.values_list("pk", flat=True)) == {recent.pk, busy.pk}
    assert not old.folder.exists() and recent.folder.exists() and not stray.exists()


@pytest.mark.django_db
def test_load_page_states_the_deletion_date(client):
    analysis = loaded(client)
    html = client.get(f"/station/{analysis.pk}/load").content.decode()
    expected = f"{analysis.expires_at:%-d %B %Y}"
    assert f"(until {expected} unless you change them)" in html

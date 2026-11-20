"""Single-station step 1 (#76): a station's setup page (the New station page of #201) with
its file read, a new file sent from it, the checks and their messages, the metadata form
(with and without htmx), the data summary, ownership and retention. Add stations (#233,
``test_add_stations.py``) starts every station since the New station form went (#271):
the stations here are made at model level with their details not yet done
(``made.station_to_set_up``), as that form's "Read the file" left them."""

import datetime as dt
import re
import uuid
from pathlib import Path

import made
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.retention import purge_expired
from climpact_web.jobs.views import OWNER_KEY
from climpact_web.stations import preview
from climpact_web.stations.forms import MIN_BASE_DAYS, MetadataForm
from climpact_web.stations.models import Station, Step, Workspace, stations_dir
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


def upload(client, text, name, url, **fields):
    """Send a file from a station's setup page (``url``) as it does with JavaScript: read
    it, nothing else."""
    data = text.encode() if isinstance(text, str) else text
    fields.setdefault("intent", "read")
    return client.post(url, {"station_file": SimpleUploadedFile(name, data), **fields})


def loaded(client, text=None, name="my station.txt") -> Station:
    """A station with its file read and its details not yet done, on its setup page."""
    return made.station_to_set_up(client, text or rows(), name)


def metadata(**changes) -> dict:
    return {
        "station_name": "Testville",
        "latitude": "-33.9",
        "longitude": "151.2",
        "base_start": "2000",
        "base_end": "2001",
        **changes,
    }


# ---- The New station page (#201) ------------------------------------------------------


@pytest.mark.django_db
def test_new_station_is_add_stations(client):
    # The New station page is Add stations since #233 (tests/test_add_stations.py), and its
    # form went with #271; a station's own setup page stays, for a new file that needs new
    # details.
    assert client.get("/station/new")["Location"] == "/add/"
    file = SimpleUploadedFile("Perth.txt", rows().encode())
    response = client.post("/station/new", {"station_file": file, **metadata(), "intent": "go"})
    assert response["Location"] == "/add/"
    assert not Station.objects.exists() and not Job.objects.exists()


@pytest.mark.django_db
def test_file_and_details_in_one_post_go_straight_to_quality(client):
    """Without JavaScript, or with the file chosen and the details typed before pressing
    it: one press of "Check and calculate" reads the file, saves the details and queues
    the checks and the speculative run together (#178)."""
    analysis = loaded(client)
    url = f"{analysis.url()}setup"
    response = upload(client, rows(), "Perth.txt", url, intent="go", **metadata(station_name=""))
    analysis.refresh_from_db()
    assert response["Location"] == f"{analysis.url()}quality"
    assert analysis.station_name == "Perth"  # empty: the file's name, as R does
    assert (analysis.latitude, analysis.step) == (-33.9, Step.QC)
    assert analysis.workspace.base_start == 2000
    assert {job.kind for job in Job.objects.all()} == {"qc", "station"}
    assert Job.objects.get(kind="station").is_speculative


@pytest.mark.django_db
def test_reading_a_file_keeps_the_details_typed_beside_it(client):
    """With JavaScript a chosen file is sent at once ("intent=read"): the page comes back,
    the file card focused, the valid details kept."""
    analysis = loaded(client)
    url = f"{analysis.url()}setup"
    client.get(url)  # the first visit's focus is used
    response = upload(client, rows(), "Perth.txt", url, **metadata(latitude="-31.9", longitude="x"))
    analysis.refresh_from_db()
    assert response["Location"] == f"{analysis.url()}setup"
    assert (analysis.station_name, analysis.latitude, analysis.longitude) == (
        "Testville",
        -31.9,
        None,
    )
    assert analysis.step == Step.UPLOAD and not Job.objects.exists()
    html = client.get(response["Location"]).content.decode()
    assert 'id="file-card" tabindex="-1" data-focus-on-load' in html
    assert "Read: 2000–2002, 800 days" in html and "Perth.txt" in html
    assert "data-error-summary" not in html  # nothing was asked for yet
    assert "data-focus-on-load" not in client.get(response["Location"]).content.decode()


@pytest.mark.django_db
def test_read_the_file_without_a_file_on_the_setup_page_changes_nothing_else(client):
    analysis = loaded(client)
    setup = f"{analysis.url()}setup"
    response = client.post(setup, {**metadata(latitude="-20"), "intent": "read"})
    analysis.refresh_from_db()
    # The slug follows the name until the details are confirmed (#256).
    assert analysis.slug == "testville" and setup.endswith("/my-station/setup")
    assert response["Location"] == f"{analysis.url()}setup" and not Job.objects.exists()
    assert analysis.latitude == -20 and analysis.step == Step.UPLOAD


@pytest.mark.django_db
def test_details_errors_after_the_file_was_read_in_the_same_post(client):
    """A good file with bad details: the file is kept and the details' errors are listed
    and marked."""
    analysis = loaded(client, rows("1980-01-01", 400), "first.txt")
    data = metadata(base_start="1950", base_end="1960")
    response = upload(client, rows(), "Perth.txt", f"{analysis.url()}setup", intent="go", **data)
    analysis.refresh_from_db()
    html = response.content.decode()
    assert response.status_code == 200 and analysis.step == Step.UPLOAD
    assert f'action="{analysis.url()}setup"' in html
    assert "There is 1 problem with the form" in html and "has no data: the file covers" in html
    assert "Read: 2000–2002, 800 days" in html
    assert not Job.objects.exists()


@pytest.mark.django_db
def test_old_upload_and_load_addresses_redirect(client):
    for old in ("/station/", "/station/new", "/station/sample"):
        assert client.get(old)["Location"] == "/add/"
        assert client.post(old)["Location"] == "/add/"
    assert not Station.objects.exists()
    analysis = loaded(client)
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    assert client.get(f"{base}/load")["Location"] == f"{base}/setup"
    assert client.get(f"{base}/")["Location"] == f"{base}/setup"
    client.post(f"{base}/setup", metadata())
    assert client.get(f"{base}/load")["Location"] == f"{base}/quality#your-data"
    assert client.get(f"{base}/setup")["Location"] == f"{base}/quality#your-data"
    assert client.get(f"{base}/file").status_code == 404  # a form's action only, gone


@pytest.mark.django_db
def test_days_with_data_strip_marks_years_with_gaps():
    from climpact_web.stations.views import year_strip

    # Sydney misses a day or two in some years, never more than 15: no year is amber.
    sydney = year_strip(inspect_station_bytes(sample_bytes()).summary)
    assert len(sydney["bars"]) == 80 and sydney["width"] == 798 and sydney["gaps"] == 0
    assert sydney["label"].endswith("no year misses more than 15 days.")
    assert all(b["y"] + b["percent"] == 100 for b in sydney["bars"])
    # 2001 misses 20 days of maximum temperature; 2000 misses 15, which is no gap.
    lines = rows("2000-01-01", 1096).splitlines()
    for k in [*range(10, 25), *range(400, 420)]:
        y, m, d, p, _tx, tn = lines[k].split()
        lines[k] = f"{y} {m} {d} {p} -99.9 {tn}"
    strip = year_strip(inspect_station_bytes("\n".join(lines).encode()).summary)
    assert [b["year"] for b in strip["bars"] if b["gap"]] == [2001]
    assert strip["label"].endswith("1 of 3 years misses more than 15 days (2001).")


def test_strip_gap_is_climdex_annual_missing_limit():
    from climpact.missing import MAX_MISSING_DAYS
    from climpact_web.stations.views import MAX_MISSING_YEAR_DAYS

    assert MAX_MISSING_YEAR_DAYS == MAX_MISSING_DAYS["annual"]


@pytest.mark.django_db
def test_a_new_file_names_a_station_still_named_after_its_file(client):
    analysis = loaded(client, rows("1980-01-01", 400))
    url = f"{analysis.url()}setup"
    response = upload(client, rows(), "Perth Airport 1961-2020.txt", url)
    analysis.refresh_from_db()
    assert response["Location"] == f"{analysis.url()}setup"
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
    analysis = loaded(client)
    upload(client, rows(), "../my/sta:tion*.csv", f"{analysis.url()}setup")
    analysis.refresh_from_db()
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
    "lower_case_na": (  # only "NA" is missing (R's read.table refuses "na" too)
        "2000 1 1 0 20 10\n2000 1 2 0 na 11\n",
        "Line 2: “na” in the maximum temperature column is not a number. "
        "Write missing values as -99.9 (or NA, in capitals).",
        "2000 1 2 0 na 11",
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
    analysis = loaded(client)
    response = upload(client, contents, "bad.txt", f"{analysis.url()}setup")
    assert response.status_code == 200
    analysis.refresh_from_db()
    assert analysis.file_name == "my station.txt" and analysis.station_file.read_text() == rows()
    html = response.content.decode()
    if case == "empty":  # refused by the form field, before the file is read
        assert "data-error-summary" in html and message in html
        return
    assert "bad.txt was not loaded" in html and "data-error-summary" in html
    assert message in html.replace("&#x27;", "'")
    if line:
        assert f'<code class="file-problems__line">{line}</code>' in html
    assert "Traceback" not in html and "could not convert" not in html


@pytest.mark.parametrize(
    "case",
    ["short_row", "long_row", "text_value", "lower_case_na", "no_valid_dates", "last_before_first"],
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
    html = upload(client, text, "bad.txt", f"{loaded(client).url()}setup").content.decode()
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


def test_na_is_read_as_missing_as_r_does():
    """R's read.table (na.strings = "NA") reads NA as missing, in the core and here."""
    text = "2000 1 1 0 20 10\n2000 1 2 NA NA 11\n2000 1 3 0.2 21 NA\nNA 1 4 0 20 10\n"
    inspection = inspect_station_bytes(text.encode())
    assert inspection.ok, inspection.problems
    missing = {v["key"]: v["missing"] for v in inspection.summary["variables"]}
    assert missing == {"prcp": 1, "tmax": 1, "tmin": 1}
    assert inspection.summary["last_date"] == "2000-01-03"  # the NA year is dropped
    assert "(line 4: NA-1-4)" in inspection.warnings[0]


def test_a_variable_with_no_values_is_reported():
    text = "".join(f"2000 1 {d} -99.9 20 10\n" for d in range(1, 10))
    inspection = inspect_station_bytes(text.encode())
    assert inspection.warnings == ["The file has no precipitation values: every value is missing."]


@pytest.mark.django_db
def test_warnings_are_shown_on_the_load_page(client):
    analysis = loaded(client, "2000 1 1 0 20 10\n2001 2 29 0 20 10\n2000 1 9 0 20 10\n")
    html = client.get(f"{analysis.url()}setup").content.decode()
    assert "Something to check in the file" in html and "does not exist" in html


# ---- The sample --------------------------------------------------------------------------


def test_bundled_sample_is_the_r_sample():
    assert sample_bytes() == SYDNEY.read_bytes()


@pytest.mark.django_db
def test_the_sample_on_its_setup_page_needs_nothing_typed(client):
    analysis = made.station_to_set_up(client, sample=True)
    url = analysis.url("setup")
    assert client.get(analysis.url())["Location"] == url
    assert (analysis.station_name, analysis.latitude, analysis.longitude) == (
        "sydney_observatory_hill_1936-2015",
        -33.86,
        151.21,
    )
    assert analysis.metadata_complete and analysis.source == "sample"
    html = client.get(url).content.decode()
    assert "Read: 1936–2015, 29,220 days" in html and SAMPLE_NAME in html
    assert 'value="sydney_observatory_hill_1936-2015"' in html
    # straight on to the next step, with nothing to type
    response = client.post(url, metadata(**{
        "station_name": analysis.station_name, "latitude": "-33.86", "longitude": "151.21",
        "base_start": "1971", "base_end": "2000"}))  # fmt: skip
    assert response["Location"] == f"{analysis.url()}quality"


@pytest.mark.django_db
def test_setup_page_has_the_file_then_the_details_then_one_button(client):
    """#201 (and #173): the file read, then the station details, then one button below the
    fields it asks the user to confirm, with the note on the defaults. Nothing else sends
    the form but the file's own (hidden with JavaScript) "Read the file"."""
    analysis = made.station_to_set_up(client, sample=True)
    html = client.get(f"{analysis.url()}setup").content.decode()
    form = re.search(
        r'<form method="post" action="[^"]*/setup" enctype="multipart/form-data" '
        r'class="setup__form" id="new-station".*?</form>',
        html,
        re.S,
    ).group(0)
    buttons = re.findall(r'<button type="submit"[^>]*value="(\w+)"', form)
    assert buttons == ["read", "go"]
    assert form.index('id="file-title"') < form.index('id="details-title"')
    assert form.index('name="base_start"') < form.index("<span>Check and calculate</span>")
    assert "use the defaults. You can change them later in Inputs." in form
    assert 'aria-describedby="setup-defaults"' in form
    assert (
        "year-strip__bar" in form and 'role="img" aria-label="Days with data in each year' in form
    )
    data = {"station_name": analysis.station_name, "latitude": "-33.86", "longitude": "151.21",
            "base_start": "1971", "base_end": "2000"}  # fmt: skip
    assert client.post(f"{analysis.url()}setup", data)["Location"].endswith("/quality")


@pytest.mark.django_db
def test_sample_goes_to_add_stations_and_the_file_downloads(client):
    assert client.get("/station/sample")["Location"] == "/add/"
    assert client.post("/station/sample")["Location"] == "/add/"
    assert not Station.objects.exists()
    response = client.get("/station/sample.txt")
    assert response.content == SYDNEY.read_bytes()
    assert SAMPLE_NAME in response["Content-Disposition"]


# ---- The data summary ------------------------------------------------------------------


@pytest.mark.django_db
def test_your_data_summarises_the_file_on_quality(client):
    """The data summary is Quality's "Your data" (#198); the setup page has only the file
    card and the days-with-data strip (#201)."""
    url = made.station_to_set_up(client, sample=True).url("setup")
    setup = client.get(url).content.decode()
    assert 'class="data-chip"' not in setup
    client.post(url, {**metadata(), "station_name": "sydney",
                                       "base_start": "1971", "base_end": "2000"})  # fmt: skip
    analysis = Station.objects.get()
    html = client.get(f"{analysis.url()}quality").content.decode()
    # Sydney: 29220 days; 7 precipitation and 58 temperature values missing, in chips (#202)
    chips = re.sub(r"\s+", " ", " ".join(re.findall(r'<li class="data-chip.*?</li>', html, re.S)))
    assert "<b>80</b> years" in chips and "<b>29,220</b> days" in chips
    assert "Precipitation: <b>7 missing</b> (under 0.1%)" in chips
    assert chips.count("<b>58 missing</b> (0.2%)") == 2
    assert html.count('<svg viewBox="0 0 960 170" role="img"') == 2  # the static preview
    assert "Days with data in each year" in html and '<th scope="row">1936</th>' in html


@pytest.mark.django_db
def test_setup_page_states_the_retention_quietly(client, settings):
    """The retention notice once, as a quiet line, not an alert (#173, #201)."""
    settings.WORKSPACE_EXPIRY = True
    html = client.get(made.station_to_set_up(client, sample=True).url("setup")).content.decode()
    assert html.count("deleted") <= 2  # file and results, in one line
    assert "deleted" not in "".join(re.findall(r'<div class="alert.*?</div>', html, re.S))
    notice = re.search(
        r'<p class="text-sm text-text-muted[^"]*">[^<]*<svg[^>]*>'
        r"(?:(?!</p>).)*Your file, details and results are deleted on \d+ \w+ \d{4} unless you"
        r" change them\.",
        html,
        re.S,
    )
    assert notice


@pytest.mark.django_db
def test_without_expiry_the_retention_says_the_data_stay(client, settings):
    """Locally, with workspace expiry off (#231), no deletion date is given."""
    settings.WORKSPACE_EXPIRY = False
    html = client.get(made.station_to_set_up(client, sample=True).url("setup")).content.decode()
    assert "stay on this computer until you delete them" in html
    assert "deleted on" not in html


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
    response = client.get(f"{analysis.url()}series.csv")
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
    assert (Workspace().base_start, Workspace().base_end) == (1971, 2000)


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
        f"{analysis.url()}setup", metadata(latitude="99", station_name=".bad")
    ).content.decode()
    assert "There are 2 problems with the form" in html
    assert '<a href="#id_station_name">' in html and '<a href="#id_latitude">' in html
    assert 'aria-invalid="true"' in html
    analysis.refresh_from_db()
    assert analysis.step == Step.UPLOAD and analysis.latitude is None


@pytest.mark.django_db
def test_htmx_validates_one_group_as_it_changes(client):
    analysis = loaded(client)
    html = client.get(f"{analysis.url()}setup").content.decode()
    for group in ("station_name", "latitude", "longitude", "base_period"):
        assert f'id="group-{group}" hx-post="{analysis.url()}setup/validate"' in html
        assert f'hx-vals=\'{{"group": "{group}"}}\'' in html
    assert 'hx-trigger="change" hx-include="closest form"' in html

    url = f"{analysis.url()}setup/validate"
    fragment = client.post(url, {**metadata(latitude="123", longitude=""), "group": "latitude"})
    text = fragment.content.decode()
    assert text.lstrip().startswith('<div class="grid gap-2" id="group-latitude"')
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
    response = client.post(f"{analysis.url()}setup", metadata())
    assert response["Location"] == f"{analysis.url()}quality"
    analysis.refresh_from_db()
    assert analysis.step == Step.QC
    assert analysis.metadata == {"name": "Testville", "latitude": -33.9, "longitude": 151.2,
                                 "base_start": 2000, "base_end": 2001}  # fmt: skip
    page = client.get(response["Location"]).content.decode()
    # The workspace tabs (#179): Quality current, Results not yet; no Data tab, its summary
    # is Quality's "Your data", and the details are in the Inputs panel (#198).
    quality = r'href="/w/[^"]+/quality" data-tab="quality"[^>]*aria-current="page"'
    assert re.search(quality, page)
    assert 'data-tab="data"' not in page and 'id="your-data"' in page
    assert f'href="{analysis.url()}inputs/base-period?next=' in page
    assert re.search(r'<span class="tabs__tab" data-tab="results" data-state="locked">', page)


@pytest.mark.django_db
def test_quality_page_needs_step_one_first(client):
    analysis = loaded(client)
    assert client.get(f"{analysis.url()}quality")["Location"] == f"{analysis.url()}setup"
    assert client.post(f"{analysis.url()}recalculate").status_code == 302
    assert client.post(f"{analysis.url()}inputs/thresholds").status_code == 302
    assert not Job.objects.exists()


@pytest.mark.django_db
def test_changing_metadata_replaces_only_what_depends_on_it(client):
    """Confirming the details queues the checks and a speculative run of the indices
    (#178). Changing them (#179) keeps both jobs: the checks, which do not depend on the
    location, stay current; the run is cancelled and queued again for the new details."""
    analysis = loaded(client)
    client.post(f"{analysis.url()}setup", metadata())
    analysis.refresh_from_db()
    first_qc, first_run = analysis.qc_job, analysis.indices_job
    assert first_qc.kind == "qc" and first_run.kind == "station" and first_run.is_speculative
    assert first_qc.inputs["file"] == analysis.file_hash != ""
    assert first_run.inputs["metadata"] == analysis.metadata
    # the same metadata again: nothing to redo
    client.post(f"{analysis.url()}setup", metadata())
    analysis.refresh_from_db()
    assert (analysis.qc_job, analysis.indices_job) == (first_qc, first_run)
    assert Job.objects.count() == 2
    client.post(f"{analysis.url()}setup", metadata(latitude="-30"))
    analysis.refresh_from_db()
    assert analysis.step == Step.QC
    assert analysis.qc_job == first_qc  # the checks do not use the latitude
    run = analysis.indices_job
    assert run != first_run and run.params["metadata"]["latitude"] == -30
    assert run.inputs["metadata"]["latitude"] == -30 and run.is_speculative
    first_run.refresh_from_db()
    assert first_run.status == Status.CANCELLED  # never shown, never left running
    # A new name changes the checks' file names: they run again, replacing the old ones.
    client.post(f"{analysis.url()}setup", metadata(latitude="-30", station_name="New"))
    analysis.refresh_from_db()
    assert analysis.qc_job != first_qc and "replaces" not in analysis.qc_job.params
    first_qc.refresh_from_db()
    assert first_qc.status == Status.CANCELLED  # it had not run: nothing to keep
    # The jobs themselves are kept, with their own retention.
    assert Job.objects.count() == 5


@pytest.mark.django_db
def test_replacing_the_file_keeps_the_metadata(client):
    analysis = loaded(client, name="first.txt")
    client.post(f"{analysis.url()}setup", metadata(station_name="first"))
    response = upload(client, rows("1980-01-01", 400), "second.txt", f"{analysis.url()}setup")
    assert response["Location"] == f"{analysis.url()}setup"
    analysis.refresh_from_db()
    # the name followed the file name, as it was still the default; the rest is kept
    assert (analysis.station_name, analysis.latitude) == ("second", -33.9)
    # The work is kept (#179): the checks and results show as out of date until the new
    # details are confirmed.
    assert analysis.summary["first_date"] == "1980-01-01" and analysis.step == Step.QC
    assert analysis.qc_job is not None and analysis.qc_job.inputs["file"] != analysis.file_hash
    client.post(
        f"{analysis.url()}setup",
        metadata(station_name="My name", base_start="1980", base_end="1980"),
    )
    upload(client, rows(), "third.txt", f"{analysis.url()}setup")
    analysis.refresh_from_db()
    assert analysis.station_name == "My name"
    # a bad file leaves everything as it was
    html = upload(client, "x\n1 2\n", "bad.txt", f"{analysis.url()}setup").content.decode()
    assert "bad.txt was not loaded" in html and "Line 2 has 2 values" in html
    analysis.refresh_from_db()
    assert analysis.file_name == "third.txt"


@pytest.mark.django_db
def test_delete_now(client):
    analysis = loaded(client)
    folder = analysis.folder
    response = client.post(f"{analysis.url()}delete")
    assert response["Location"] == "/add/"
    assert not Station.objects.exists() and not folder.exists()


# ---- Ownership -------------------------------------------------------------------------


@pytest.mark.django_db
def test_other_sessions_get_404(client):
    analysis = loaded(client)
    other = Client()
    for url in ("load", "setup", "series.csv", "quality"):
        assert other.get(f"{analysis.url()}{url}").status_code == 404
    for url in ("load", "setup", "setup/validate", "delete", "recalculate", "inputs/thresholds"):
        assert other.post(f"{analysis.url()}{url}").status_code == 404
    assert client.get(f"/station/{uuid.uuid4()}/setup").status_code == 404
    assert Station.objects.exists()


# ---- Retention -------------------------------------------------------------------------


@pytest.mark.django_db
def test_old_workspaces_are_purged_with_their_files(client, settings):
    settings.WORKSPACE_EXPIRY = True
    old = loaded(client)
    recent = loaded(client)
    busy = loaded(client)
    busy.indices_job = Job.objects.create(kind="station", owner="x", status=Status.RUNNING)
    busy.save()
    long_ago = timezone.now() - dt.timedelta(days=8)
    Workspace.objects.filter(pk__in=[old.workspace_id, busy.workspace_id]).update(
        updated_at=long_ago
    )
    stray = stations_dir() / str(uuid.uuid4())
    stray.mkdir()
    import os

    os.utime(stray, (long_ago.timestamp(), long_ago.timestamp()))

    purged = purge_expired()
    assert purged.other == 1
    assert set(Station.objects.values_list("pk", flat=True)) == {recent.pk, busy.pk}
    assert not old.folder.exists() and recent.folder.exists() and not stray.exists()


@pytest.mark.django_db
def test_load_page_states_the_deletion_date(client, settings):
    settings.WORKSPACE_EXPIRY = True
    analysis = loaded(client)
    html = client.get(f"{analysis.url()}setup").content.decode()
    expected = f"{analysis.expires_at:%-d %B %Y}"
    assert f"deleted on {expected} unless you change them." in html

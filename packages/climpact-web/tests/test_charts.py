"""Interactive charts (#75): the chart data, the JSON views and their caching, the chart
frame's hooks, and the vendored uPlot."""

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest
from django.template.loader import render_to_string
from django.test import Client

import climpact_web
from climpact_web.charts import data
from climpact_web.charts.views import SAMPLE_OUTPUTS, sample_source
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.views import OWNER_KEY
from climpact_web.stations.models import Station
from climpact_web.stations.views import SAMPLE_NAME, sample_bytes

STATIC = Path(climpact_web.__file__).parent / "core" / "static" / "climpact_web"
UPLOT = STATIC / "vendor" / "uplot"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    return settings


@pytest.fixture
def sample_file(tmp_path) -> Path:
    path = tmp_path / SAMPLE_NAME
    path.write_bytes(sample_bytes())
    return path


def owned_client(owner="owner-a") -> Client:
    client = Client()
    session = client.session
    session[OWNER_KEY] = owner
    session.save()
    client.cookies["sessionid"] = session.session_key
    return client


# ---- vendored uPlot and the static files ----------------------------------------------


@pytest.mark.parametrize("name", ["uPlot.iife.min.js", "uPlot.min.css", "LICENSE"])
def test_vendored_uplot_matches_readme(name):
    readme = (UPLOT / "README.md").read_text()
    row = next(line for line in readme.splitlines() if line.startswith(f"| `{name}`"))
    recorded = re.search(r"`([0-9a-f]{64})`", row).group(1)
    assert hashlib.sha256((UPLOT / name).read_bytes()).hexdigest() == recorded
    assert "1.6.32" in readme and "MIT" in readme


def test_uplot_licence_is_mit():
    assert "The MIT License" in (UPLOT / "LICENSE").read_text()


def test_charts_js_has_no_dependencies_beyond_uplot():
    js = (STATIC / "js" / "charts.js").read_text()
    assert not re.search(r"\bimport\b|\brequire\(|XMLHttpRequest", js)
    # One request: the frame's own data URL. The only URL is the SVG namespace.
    assert js.count("fetch(") == 1 and 'getAttribute("data-chart-src")' in js
    assert re.findall(r"https?://[^\s\"']+", js) == ["http://www.w3.org/2000/svg"]


def test_chart_scripts_load_only_on_chart_pages(client):
    assert "uPlot" not in client.get("/").content.decode()
    assert "uPlot" not in client.get("/station/new").content.decode()


# ---- daily payload ---------------------------------------------------------------------


def test_daily_payload_is_columnar_with_gaps(sample_file):
    payload = data.daily_payload(sample_file, title="Sydney")
    assert payload["kind"] == "daily" and payload["start"] == "1936-01-01"
    assert payload["days"] == 29220  # 1936-01-01 to 2015-12-31
    keys = [s["key"] for s in payload["series"]]
    assert keys == ["tmax", "tmin", "prcp"]
    for series in payload["series"]:
        assert len(series["values"]) == payload["days"]
    tmax = payload["series"][0]["values"]
    assert sum(v is None for v in tmax) == 58  # missing days are null: gaps
    assert max(v for v in tmax if v is not None) == 45.8
    assert "29,220 days" in payload["summary"] and "45.8\u00a0°C" in payload["summary"]
    # ISO dates, as the tables and the files (#115), not "Jan. 1, 1936".
    assert payload["summary"].startswith("1936-01-01 to 2015-12-31, 29,220 days.")
    assert "45.8\u00a0°C on 2013-01-18" in payload["summary"] and "Jan." not in payload["summary"]


def test_daily_payload_matches_the_csv_download(client, sample_file):
    """The chart and its CSV link hold the same values."""
    import csv
    import io

    payload = data.daily_payload(sample_file)
    analysis = Station.objects.create(owner="owner-a", file_name=SAMPLE_NAME)
    analysis.folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(sample_file, analysis.station_file)
    text = owned_client().get(f"{analysis.url()}series.csv").content.decode()
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == payload["days"]
    for series in payload["series"]:
        csv_values = [float(r[series["key"]]) if r[series["key"]] else None for r in rows]
        assert csv_values == series["values"]


def test_qc_flags_follow_the_core_checks(sample_file):
    from climpact import qc
    from climpact.config import QCParams
    from climpact.io.station import merged_rows, read_station_file

    rows = merged_rows(read_station_file(sample_file))
    flags = set(data.qc_flags(rows))
    # The sample's one TN >= TX day and its TX jumps (qc/tmaxmin.csv, qc/tx_jumps.csv).
    assert {("1988-11-16", v, "tmaxmin") for v in ("tmax", "tmin", "dtr")} <= flags
    jumps = {d for d, v, c in flags if c == "tx_jumps"}
    assert jumps == {"1946-11-06", "1973-02-06", "2006-01-01", "2013-01-18"}
    assert {d for d, v, c in flags if c == "toolarge"} == {
        "1942-03-28",
        "1984-11-09",
        "1986-08-06",
        "1990-02-03",
    }
    assert all(v == "prcp" for d, v, c in flags if c == "toolarge")
    outliers = qc.outliers(rows, QCParams())
    sections = outliers["Section"].astype(str)
    # A DTR outlier is flagged on both temperatures and on DTR (#77).
    expected = sections.str.startswith("DTR").sum() * 3 + (~sections.str.startswith("DTR")).sum()
    listed = [f for f in data.qc_flags(rows) if f[2] == "outliers"]
    assert len(listed) == expected
    # Stricter thresholds flag more.
    strict = data.qc_flags(rows, QCParams(iqr_temp=1.5, prec_max=100))
    assert len(strict) > len(flags)


def test_daily_flags_point_at_the_days_series(sample_file):
    payload = data.daily_payload(sample_file)
    points = payload["flags"]["points"]
    assert points and all(c in payload["flags"]["checks"] for _, _, c in points)
    by_key = {s["key"]: s["values"] for s in payload["series"]}
    i = next(i for i, v, c in points if c == "tmaxmin")  # 1988-11-16
    import datetime as dt

    assert dt.date(1936, 1, 1) + dt.timedelta(days=i) == dt.date(1988, 11, 16)
    assert by_key["tmax"][i] == by_key["tmin"][i] == 12.6


def test_daily_payload_without_flags(sample_file):
    """#173: the Load step's chart shows no flags, and its summary says nothing about the
    quality checks, which come in the next step."""
    payload = data.daily_payload(sample_file, flags=False)
    assert payload["flags"]["points"] == []
    assert "quality checks" not in payload["summary"]
    assert "quality checks" in data.daily_payload(sample_file)["summary"]


# ---- index payload ---------------------------------------------------------------------


def trend_rows() -> dict:
    from climpact.io.climpact_csv import read_climpact_csv

    table = read_climpact_csv(SAMPLE_OUTPUTS / "sydney" / "trend" / "sydney_trend.csv").data
    return {(r["Index"], r["Frequency"]): r for _, r in table.iterrows()}


@pytest.mark.parametrize(
    ("name", "row", "step"),
    [("txx_ANN", ("txx", "annual"), "year"), ("txx_MON", ("txx", "monthly"), "month")],
)
def test_index_trend_is_the_trend_file(name, row, step):
    """The trend line and its bounds are the core's trend output, as in the static plots."""
    payload = data.index_payload(sample_source(), name)
    expected = trend_rows()[row]
    assert payload["step"] == step and not payload["bars"]
    assert payload["trend"]["slope"] == pytest.approx(expected["Slope"], rel=1e-12)
    assert payload["trend"]["lower"] == pytest.approx(expected["Lower bound"], rel=1e-12)
    assert payload["trend"]["upper"] == pytest.approx(expected["Upper bound"], rel=1e-12)
    assert payload["trend_text"].startswith("Sen's slope")


def test_index_payload_matches_the_static_plot():
    from climpact.config import IndexParams
    from climpact.io.climpact_csv import read_climpact_csv
    from climpact.plots import index_plots

    path = SAMPLE_OUTPUTS / "sydney" / "indices" / "sydney_txx_ANN.csv"
    table = read_climpact_csv(path).data
    plots = [p for _, g in index_plots({"indices/txx_ANN": table}, IndexParams()) for p in g]
    plot = next(p for p in plots if p.name == "txx_ANN")
    payload = data.index_payload(sample_source(), "txx_ANN")
    assert payload["x"] == [int(x) for x in plot.x]
    assert payload["y"] == [None if v != v else v for v in plot.values]
    assert payload["trend"]["intercept"] == plot.trend.intercept
    assert payload["dates"][0] == "1936-11-06"
    assert payload["title"] == plot.description and payload["units"] == "°C"
    # The number rules (#226): two decimals, a no-break space, U+2212 in the interval.
    assert "Trend: rising by 0.03\u00a0°C per decade" in payload["summary"]
    assert "(95% confidence interval \u22120.22 to 0.31)" in payload["summary"]
    assert "not significant" in payload["summary"]


def test_spi_is_bars_and_day_of_has_no_trend():
    spi = data.index_payload(sample_source(), "3month_spi_MON")
    assert spi["bars"] and spi["step"] == "month" and spi["trend"] is not None
    assert spi["x"][0] == pytest.approx(1936 + 0.5 / 12)
    day_of = data.index_payload(sample_source(), "day_of_txx_ANN")
    assert day_of["trend"] is None and day_of["axis"] == "Calendar day"
    assert data.index_payload(sample_source(), "fd_ANN") is None  # not in the sample


def test_series_list_in_r_order():
    names = [s["name"] for s in data.series_list(sample_source())]
    order = ["txx_ANN", "day_of_txx_ANN", "txx_MON", "prcptot_ANN", "3month_spi_MON"]
    assert [n for n in names if n in order] == order


def test_summary_writes_units_as_every_page_does():
    """#189: "20%" for a percentage, "20 days" for a count, the number alone without
    units, and no double space in a unitless trend; #226: a no-break space before the
    units, "pp" for percentage points, two decimals for a slope."""
    trend = {"slope": 0.063, "lower": 0.01, "upper": 0.1}

    def summary(units):
        payload = {"name": "x_ANN", "x": [2000, 2001], "y": [20.0, 4.29], "step": "year"}
        return data.index_summary({**payload, "units": units, "trend": trend})

    assert "Highest 20% in 2000, lowest 4.29% in 2001." in summary("%")
    assert "rising by 0.63\u00a0pp per decade" in summary("%")
    assert "Highest 20\u00a0days in 2000, lowest 4.29\u00a0days in 2001." in summary("days")
    assert "rising by 0.63\u00a0days per decade" in summary("days")
    assert "Highest 20 in 2000, lowest 4.29 in 2001." in summary("")
    assert "rising by 0.63 per decade" in summary("")
    for units in ("%", "days", ""):
        assert "  " not in summary(units) and " %" not in summary(units)
    flat = data.index_summary(
        {"name": "x", "x": [2000], "y": [1.0], "step": "year", "units": ""}
        | {"trend": {"slope": 0.0, "lower": -1.0, "upper": 1.0}}
    )
    assert "no change (0.00 per decade)" in flat


def test_with_units_filter():
    from django.template import Context, Template

    template = Template("{% load charts %}[{{ v|with_units:u }}]")
    assert template.render(Context({"v": "12.5", "u": "%"})) == "[12.5%]"
    assert template.render(Context({"v": "20", "u": "days"})) == "[20\u00a0days]"
    assert template.render(Context({"v": "+0.63", "u": ""})) == "[+0.63]"


def test_summary_numbers():
    assert data.number(0.0277777) == "0.03"
    assert data.number(-0.0) == "0"
    assert data.number(45.8) == "45.8"


# ---- views -----------------------------------------------------------------------------


def make_analysis(sample_file, owner="owner-a") -> Station:
    analysis = Station.objects.create(owner=owner, file_name=SAMPLE_NAME, station_name="sydney")
    analysis.folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(sample_file, analysis.station_file)
    return analysis


def test_station_daily_view_and_caching(sample_file):
    analysis = make_analysis(sample_file)
    client = owned_client()
    url = f"/charts/station/{analysis.pk}/daily.json"
    response = client.get(url)
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response["Cache-Control"] == "private, no-cache"
    assert response["Last-Modified"]
    payload = json.loads(response.content)
    assert payload["days"] == 29220 and payload["csv"] == f"{analysis.url()}series.csv"
    etag = response["ETag"]
    assert client.get(url, HTTP_IF_NONE_MATCH=etag).status_code == 304
    assert client.get(url, HTTP_IF_MODIFIED_SINCE=response["Last-Modified"]).status_code == 304
    zipped = client.get(url, HTTP_ACCEPT_ENCODING="gzip")
    assert zipped["Content-Encoding"] == "gzip"
    assert len(zipped.content) < len(response.content) / 3
    # A changed file changes the validators.
    analysis.station_file.write_text(analysis.station_file.read_text().replace("45.8", "45.9"))
    changed = client.get(url, HTTP_IF_NONE_MATCH=etag)
    assert changed.status_code == 200 and changed["ETag"] != etag
    # ?flags=0 (the Load step, #173) leaves the flags out, and is cached on its own.
    unflagged = client.get(url + "?flags=0")
    assert json.loads(unflagged.content)["flags"]["points"] == []
    assert json.loads(client.get(url).content)["flags"]["points"]


def test_station_daily_view_is_private(sample_file):
    analysis = make_analysis(sample_file)
    url = f"/charts/station/{analysis.pk}/daily.json"
    assert owned_client("someone-else").get(url).status_code == 404
    assert Client().get(url).status_code == 404
    assert owned_client().post(url).status_code == 405


def finished_station_job(owner="owner-a", status=Status.SUCCEEDED) -> Job:
    job = Job.objects.create(
        kind="station",
        owner=owner,
        status=status,
        params={"station_file": "station.txt", "params": {}},
        result={"station": "sydney"},
    )
    shutil.copytree(SAMPLE_OUTPUTS, job.output_dir)
    return job


def test_job_series_views():
    job = finished_station_job()
    client = owned_client()
    listing = client.get(f"/charts/jobs/{job.pk}/series.json")
    assert listing.status_code == 200
    series = {s["name"]: s for s in json.loads(listing.content)["series"]}
    txx = series["txx_ANN"]
    assert txx["url"] == f"/charts/jobs/{job.pk}/series/txx_ANN.json?station=sydney"
    assert txx["csv"] == f"/jobs/{job.pk}/files/sydney/indices/sydney_txx_ANN.csv"
    assert client.get(txx["csv"]).status_code == 200
    response = client.get(txx["url"])
    payload = json.loads(response.content)
    assert payload["name"] == "txx_ANN" and payload["csv"] == txx["csv"]
    assert client.get(txx["url"], HTTP_IF_NONE_MATCH=response["ETag"]).status_code == 304
    assert client.get(f"/charts/jobs/{job.pk}/series/day_of_txx_ANN.json").status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "series/fd_ANN.json",  # not written
        "series/..json",
        "series/txx_ANN.json?station=other",
    ],
)
def test_job_series_404(path):
    job = finished_station_job()
    assert owned_client().get(f"/charts/jobs/{job.pk}/{path}").status_code == 404


def test_job_series_needs_a_finished_job_of_the_session():
    running = finished_station_job(status=Status.RUNNING)
    assert owned_client().get(f"/charts/jobs/{running.pk}/series.json").status_code == 404
    job = finished_station_job()
    assert owned_client("other").get(f"/charts/jobs/{job.pk}/series.json").status_code == 404


def test_batch_job_series_by_station():
    metadata = (
        "station_file\tlatitude\tlongitude\twsdin\tcsdin\tTb_HDD\tTb_CDD\tTb_GDD\trxnday\t"
        "rnnmm\ttxtn\tSPEI\nsydney.txt\t-33\t151\t3\t3\t18\t18\t10\t3\t30\t2\t24\n"
    )
    job = Job.objects.create(
        kind="batch",
        owner="owner-a",
        status=Status.SUCCEEDED,
        params={"metadata_file": "metadata.txt"},
        result={"folder": "run", "stations": [{"name": "sydney", "ok": True}]},
    )
    job.input_dir.mkdir(parents=True)
    (job.input_dir / "metadata.txt").write_text(metadata)
    shutil.copytree(SAMPLE_OUTPUTS, job.output_dir / "run")
    client = owned_client()
    url = f"/charts/jobs/{job.pk}/series/txx_ANN.json?station=sydney"
    payload = json.loads(client.get(url).content)
    assert payload["csv"] == f"/jobs/{job.pk}/files/run/sydney/indices/sydney_txx_ANN.csv"
    assert client.get(url.replace("sydney", "nowhere")).status_code == 404


def test_pattern_library_examples(client, settings):
    settings.PATTERN_LIBRARY = False
    assert client.get("/charts/sample/daily.json").status_code == 404
    assert client.get("/charts/sample/series/txx_ANN.json").status_code == 404
    settings.PATTERN_LIBRARY = True
    assert json.loads(client.get("/charts/sample/daily.json").content)["days"] == 29220
    assert json.loads(client.get("/charts/sample/series/txx_ANN.json").content)["trend"]
    page = client.get("/patterns/").content.decode()
    for name in ("txx_ANN", "txx_MON", "3month_spi_MON"):
        assert f'data-chart-src="/charts/sample/series/{name}.json"' in page
    assert 'data-chart-src="/charts/sample/daily.json"' in page
    assert "uPlot.iife.min.js" in page and 'id="climpact-chart-text"' in page


# ---- the chart frame --------------------------------------------------------------------


def test_interactive_chart_frame_markup():
    html = render_to_string(
        "components/chart_frame.html",
        {"id": "c1", "title": "TXx", "data_url": "/charts/x.json", "image_src": "/p.png"},
    )
    assert 'data-chart-src="/charts/x.json"' in html
    assert 'aria-describedby="c1-summary"' in html  # the summary is announced
    assert 'tabindex="0" role="group"' in html and 'aria-describedby="c1-summary c1-keys"' in html
    assert 'role="toolbar"' in html and "data-chart-toolbar hidden" in html  # shown by JS
    for action in ("zoom-in", "zoom-out", "left", "right", "reset", "png", "svg"):
        assert f'data-chart-action="{action}"' in html
    assert 'role="status"' in html and "data-chart-table hidden" in html
    assert '<noscript><img class="chart__image" src="/p.png"' in html
    assert "data-chart-csv hidden" in html  # filled in from the data's csv


def test_static_chart_frame_unchanged():
    html = render_to_string(
        "components/chart_frame.html",
        {"id": "c2", "title": "TXx", "summary": "S", "csv_href": "/a.csv"},
    )
    assert "data-chart-src" not in html and "data-chart-toolbar" not in html
    assert 'href="/a.csv"' in html


def test_your_data_has_the_daily_chart(client):
    """Quality's "Your data" (#198; the setup page has only a strip of years, #201)."""
    setup = client.post("/station/sample")["Location"]
    analysis = Station.objects.get()
    details = {"station_name": "sydney", "latitude": "-33.86", "longitude": "151.21",
               "base_start": "1971", "base_end": "2000"}  # fmt: skip
    html = client.post(setup, details, follow=True).content.decode()
    # Without the quality checks' flags: they belong to the next step (#173).
    assert f'data-chart-src="/charts/station/{analysis.pk}/daily.json?flags=0"' in html
    assert f'href="{analysis.url()}series.csv"' in html
    assert "uPlot.iife.min.js" in html and "js/charts.js" in html
    assert "<noscript>" in html and "series-preview" in html  # the static overview
    # The page's own `summary` (the file summary) does not leak into the frame: the
    # chart's summary comes from its data.
    assert 'id="daily-chart-summary" data-chart-summary></p>' in html

"""The low-bandwidth budget (#82): what each page costs to download, enforced in CI.

Every page type is rendered by the real views, with the static files collected as a
deployment collects them (hashed names, minified CSS, gzip and Brotli copies), and
everything the browser fetches before the page can render is added up: the HTML (gzipped
by ``CompressionMiddleware``) and every stylesheet, script, icon sprite and favicon it
links (the ``.gz`` copy WhiteNoise serves). Content htmx loads afterwards and chart data
are not counted. The budgets and the measured sizes are in TECHNICAL.md, "Size budget";
the table of sizes prints at the end of the test run.

To add a page: add a function to PAGES returning its URL (it may create what the page
needs first). To add a static file: give it a budget in ASSET_BUDGETS (a test fails until
it has one). Chart code (#75) is allowed only on pages marked ``charts=True``.
"""

import gzip
import re
from dataclasses import dataclass
from pathlib import Path

import netCDF4
import numpy as np
import pytest
from django.core.management import call_command
from django.test import override_settings

import climpact_web
from climpact_web.core.storage import minify_css

KB = 1024
FIRST_PAGE_BUDGET = 100 * KB  # the landing page: HTML and everything it links, gzipped
PAGE_BUDGET = 300 * KB  # any other page, chart code included (chart data is not)
HTML_RAW_BUDGET = 2048 * KB  # any page's HTML before compression: what the browser parses

# Gzipped size of each static file as served (stylesheets minified). Every stylesheet,
# script, SVG and JSON file in the package needs an entry.
ASSET_BUDGETS = {
    # One stylesheet on every page (#118): the tokens, base styles, every component and
    # the utilities the templates use, built by Tailwind (it replaced main.css, the
    # dark theme and eight page stylesheets; uPlot's small stylesheet is inside it).
    # 13.5 KB before the section header and the workspace header (#197), 13 KB before #196,
    # 12.5 KB before the help drawer (#177)
    "css/climpact.css": 14 * KB,
    "js/qc.js": 2 * KB,  # the quality checks: worklist and tables linked to the charts (#77, #174)
    "js/results.js": 1.5 * KB,  # the results dashboard's filters (#78), collapsed groups (#113)
    "js/sector.js": 0.75 * KB,  # step 5: the y label from the file name (#90)
    "js/ui.js": 4.5 * KB,  # 4 KB until #137 moved the progress polls' visibility here
    "js/drawer.js": 1 * KB,  # the help drawer, on every page (#177)
    "js/workspace.js": 0.5 * KB,  # the station workspace's sticky header (#197)
    "js/turnstile.js": 2.5 * KB,  # holds a form until Turnstile's token comes (#163)
    "js/theme.js": 0.5 * KB,  # the chosen theme before first paint, blocking in <head> (#137)
    "js/tour.js": 3 * KB,  # the landing page only
    "js/gridded.js": 1 * KB,
    "vendor/htmx/htmx.min.js": 18 * KB,  # vendored, as released
    "icons/icons.svg": 2.5 * KB,
    "icons/favicon.svg": 0.5 * KB,
    "chart-palette.json": 1.5 * KB,  # not linked by pages; for code that cannot read CSS
    # The interactive charts (#75), on chart pages only.
    "js/charts.js": 14 * KB,
    "vendor/uplot/uPlot.iife.min.js": 24 * KB,
    "vendor/uplot/uPlot.min.css": 1 * KB,
}
# Static files that only chart pages may link (#75).
CHART_ASSETS = ("climpact_web/js/charts", "climpact_web/vendor/uplot/")

STATIC = Path(climpact_web.__file__).parent / "core" / "static" / "climpact_web"
STATIC_LINK = re.compile(r'(?:href|src)="/static/([^"#?]+)')


# ---- The pages ---------------------------------------------------------------------------


@dataclass
class Page:
    url: object  # a function of the test client returning the page's URL
    charts: bool = False  # a page that may load the chart code (#75)
    status: int = 200


def station_sample(client) -> str:
    return client.post("/station/sample")["Location"]


def station_qc(client) -> str:
    load = station_sample(client)
    data = {"station_name": "sydney_observatory_hill_1936-2015", "latitude": "-33.86",
            "longitude": "151.21", "base_start": "1971", "base_end": "2000"}  # fmt: skip
    return client.post(load, data)["Location"]


def station_qc_results(client) -> str:
    """The quality-check results of the Sydney sample (#77): the checks run, every section,
    the charts and the distribution plots."""
    from climpact_web.jobs.worker import claim, run_job

    url = station_qc(client)
    run_job(claim("budget"), None)
    return url


def station_calculating(client) -> str:
    """Results while the run queued with the checks goes on, after "Use this data": the
    progress and the closed "Adjust and recalculate" form (#178)."""
    from climpact_web.stations.models import StationAnalysis, Step

    url = station_qc(client)
    StationAnalysis.objects.update(step=Step.INDICES)
    return url.replace("/quality", "/results")


def station_results(client) -> str:
    """The dashboard of a finished run with every index: R's reference output for the
    Sydney sample (114 index tables, 80 cards with sparklines)."""
    import shutil

    from climpact_web.jobs.models import Job, Status
    from climpact_web.stations.models import StationAnalysis

    url = station_calculating(client)
    analysis = StationAnalysis.objects.get()
    station = "sydney_observatory_hill_1936-2015"
    job = Job.objects.create(kind="station", owner=analysis.owner, status=Status.SUCCEEDED,
                             params={"params": {}, "plots": True, "zip": True},
                             result={"station": station, "skipped": []})  # fmt: skip
    reference = Path(__file__).resolve().parents[3] / "reference" / "output" / "lat0" / station
    shutil.copytree(reference, job.output_dir / station)
    analysis.indices_job = job
    analysis.save()
    return url


def station_index(client) -> str:
    return station_results(client) + "/txx"


def station_sector(client) -> str:
    """Step 5's results (#90): R's sample wheat file against the Sydney run, the 42 bars and
    the four scatter plots with their tables."""
    from climpact_web.jobs.models import Job
    from climpact_web.jobs.worker import claim, run_job

    url = station_results(client).replace("/results", "/sector")
    Job.objects.filter(kind="qc").delete()
    client.post(url, {"sample": "1", "detrend": "on"})
    run_job(claim("budget"), None)
    return url


def station_downloads(client) -> str:
    """The downloads page of the run with every index (#79): each table's link and size."""
    return station_results(client).replace("/results", "/downloads")


def batch_check(client) -> str:
    return client.post("/batch/sample")["Location"]


def batch_results(client) -> str:
    check = batch_check(client)
    data = {"base_start": "1971", "base_end": "2000", "workers": "1"}
    return client.post(f"{check}run", data)["Location"]


def job_detail(client) -> str:
    from climpact_web.jobs.models import Job

    batch_results(client)
    return f"/jobs/{Job.objects.get().pk}/"


def gridded_setup(client) -> str:
    return client.post("/gridded/sample")["Location"]


def gridded_results_large_grid(client) -> str:
    """The results page of a finished gridded run on a 100 x 100 grid: the largest map
    drawn (maps.MAX_MAP_CELLS) and its table, with the values all different."""
    from climpact_web.gridded.models import GriddedRun
    from climpact_web.jobs.models import Job, Status

    run = GriddedRun.objects.get(pk=gridded_setup(client).split("/")[2])
    name = "txx_ANN_climpact_historical_NA_1991-2010.nc"
    job = Job.objects.create(kind="gridded-indices", owner=run.owner, status=Status.SUCCEEDED,
                             step=1, total=1, result={"files": [name]})  # fmt: skip
    job.output_dir.mkdir(parents=True)
    n = 100
    with netCDF4.Dataset(job.output_dir / name, "w") as nc:
        nc.createDimension("time", 20)
        nc.createDimension("lat", n)
        nc.createDimension("lon", n)
        t = nc.createVariable("time", "f8", ("time",))
        t.units, t.calendar = "days since 1991-01-01", "standard"
        t[:] = np.arange(20) * 365 + 182
        nc.createVariable("lat", "f8", ("lat",))[:] = np.linspace(-45, -10, n)
        nc.createVariable("lon", "f8", ("lon",))[:] = np.linspace(110, 155, n)
        v = nc.createVariable("txx", "f4", ("time", "lat", "lon"))
        v.units, v.long_name = "degC", "Annual maximum of daily maximum temperature"
        v[:] = 20 + 20 * np.random.default_rng(0).random((20, n, n))
    run.indices_job = job
    run.save()
    return f"/gridded/{run.pk}/results"


PAGES = {
    "landing": Page(lambda client: "/"),
    "station upload": Page(lambda client: "/station/"),
    "station sample loaded": Page(station_sample, charts=True),  # the daily charts (#75)
    "station quality": Page(station_qc),  # the checks queued
    "station quality results": Page(station_qc_results, charts=True),  # daily charts (#77)
    "station calculating": Page(station_calculating),  # with the settings form (#178)
    "station results, 80 indices": Page(station_results),  # sparklines, no chart code
    "station index": Page(station_index, charts=True),  # the index's chart (#78)
    "station sector results": Page(station_sector),  # inline SVG charts, no chart code (#90)
    "station downloads": Page(station_downloads),  # every file with its size (#79)
    "batch start": Page(lambda client: "/batch/"),
    "batch check": Page(batch_check),
    "batch results": Page(batch_results),
    "jobs": Page(lambda client: "/jobs/"),
    "job": Page(job_detail),
    "gridded start": Page(lambda client: "/gridded/"),
    "gridded set-up": Page(gridded_setup),
    "gridded results, 100x100 grid": Page(gridded_results_large_grid, charts=True),  # cell series
    "help": Page(lambda client: "/help/"),
    "help guide": Page(lambda client: "/help/quality-control/"),
    "help indices": Page(lambda client: "/help/indices/"),
    "help topics": Page(lambda client: "/help/topics/"),
    "help search": Page(lambda client: "/help/search/?q=base+period"),
    "not found": Page(lambda client: "/no-such-page/", status=404),
}
# Measured sizes, printed at the end of the run (conftest.py).
# The name of the user property each page budget test records its sizes in, for the table
# conftest.py prints. A property travels on the test report, so the table is printed under
# pytest-xdist too, where the tests run in worker processes and the summary in the main one.
SIZES_PROPERTY = "page_sizes"


# ---- Measuring ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def collected(tmp_path_factory):
    """The static files as ``collectstatic`` writes them for a deployment."""
    root = tmp_path_factory.mktemp("static")
    with override_settings(
        STATIC_ROOT=root,
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "climpact_web.core.storage.StaticFilesStorage"},
        },
    ):
        call_command("collectstatic", interactive=False, verbosity=0)
    return root


@pytest.fixture
def deployed(settings, collected, tmp_path):
    """Pages render links to the collected, hashed files."""
    settings.STATIC_ROOT = collected
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "climpact_web.core.storage.StaticFilesStorage"},
    }
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    return collected


def served_sizes(root: Path, path: str) -> tuple[int, int, int]:
    """(raw, gzip, Brotli) bytes WhiteNoise sends for a collected file: the compressed
    copy when there is one, else the file itself."""
    file = root / path
    raw = file.stat().st_size
    compressed = []
    for suffix in (".gz", ".br"):
        copy = file.with_name(file.name + suffix)
        compressed.append(copy.stat().st_size if copy.exists() else raw)
    return raw, *compressed


def measure(client, root: Path, url: str, status: int) -> dict:
    response = client.get(url, HTTP_ACCEPT_ENCODING="gzip, br")
    assert response.status_code == status, url
    assert response["Content-Encoding"] == "gzip"  # pages are compressed (#82)
    html_gz = len(response.content)
    html = gzip.decompress(response.content).decode()
    assets = {}
    for path in dict.fromkeys(STATIC_LINK.findall(html)):
        assert (root / path).is_file(), f"{url} links {path}, which was not collected"
        assets[path] = served_sizes(root, path)
    return {
        "html_raw": len(html.encode()),
        "html_gz": html_gz,
        "assets": assets,
        "raw": len(html.encode()) + sum(a[0] for a in assets.values()),
        "gz": html_gz + sum(a[1] for a in assets.values()),
        "br": html_gz + sum(a[2] for a in assets.values()),
    }


# ---- The budgets -------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("name", list(PAGES))
def test_page_within_budget(client, deployed, name, record_property):
    page = PAGES[name]
    url = page.url(client)
    sizes = measure(client, deployed, url, page.status)
    record_property(
        SIZES_PROPERTY,
        {
            "page": name,
            **{key: sizes[key] for key in ("html_raw", "html_gz", "raw", "gz", "br")},
            "budgets": {
                "landing": FIRST_PAGE_BUDGET,
                "page": PAGE_BUDGET,
                "html_raw": HTML_RAW_BUDGET,
            },
        },
    )
    budget = FIRST_PAGE_BUDGET if name == "landing" else PAGE_BUDGET
    assert sizes["gz"] <= budget, (
        f"{name} ({url}) downloads {sizes['gz'] / KB:.1f} KB gzipped, over its budget of "
        f"{budget / KB:.0f} KB: {sizes['assets']}"
    )
    assert sizes["html_raw"] <= HTML_RAW_BUDGET, (
        f"{name} ({url}) has {sizes['html_raw'] / KB:.0f} KB of HTML, over "
        f"{HTML_RAW_BUDGET / KB:.0f} KB"
    )
    charts = [path for path in sizes["assets"] if path.startswith(CHART_ASSETS)]
    assert page.charts or not charts, f"{name} loads chart code but is not a chart page: {charts}"


def test_every_static_file_has_a_budget():
    files = {
        p.relative_to(STATIC).as_posix()
        for p in STATIC.rglob("*")
        if p.suffix in {".css", ".js", ".svg", ".json"}
    }
    missing = sorted(files - set(ASSET_BUDGETS))
    assert not missing, f"give these static files a budget in ASSET_BUDGETS: {missing}"


@pytest.mark.parametrize("path", list(ASSET_BUDGETS))
def test_static_file_within_budget(path):
    file = STATIC / path
    if not file.exists():
        pytest.skip(f"{path} is not in the package yet")
    data = file.read_bytes()
    if file.suffix == ".css":
        data = minify_css(data.decode()).encode()
    size = len(gzip.compress(data, 9))
    budget = ASSET_BUDGETS[path]
    assert size <= budget, f"{path}: {size} bytes gzipped, over its budget of {budget:.0f}"


def test_chart_code_only_on_chart_pages():
    """Only the pages marked as chart pages may load uPlot and the chart script; the rule
    is checked page by page in test_page_within_budget."""
    assert [name for name, page in PAGES.items() if page.charts] == [
        "station sample loaded",
        "station quality results",
        "station index",
        "gridded results, 100x100 grid",
    ]
    assert "landing" in PAGES and not PAGES["landing"].charts


# ---- The pieces ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "css, expected",
    [
        ("a {\n  color: red;\n}\n", "a{color: red}"),
        ("/* a comment */\n.x  ,  .y { margin : 0 ; }", ".x,.y{margin : 0}"),
        ('.c::before { content: " /* kept */ "; }', '.c::before{content: " /* kept */ "}'),
        (".a :focus { outline: 0 }", ".a :focus{outline: 0}"),  # the descendant space stays
        ("/* the step's label */ a { b: c }", "a{b: c}"),  # a quote in a comment
        ("a { width: calc(100% - 2rem) }", "a{width: calc(100% - 2rem)}"),
        ("@media (min-width: 40rem) {\n  a { b: c; }\n}", "@media (min-width: 40rem){a{b: c}}"),
    ],
)
def test_minify_css(css, expected):
    assert minify_css(css) == expected


def test_minified_stylesheets_keep_every_rule():
    """Minifying removes only comments and whitespace: the same selectors and
    declarations, in the same order."""

    def words(css: str) -> list[str]:
        css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
        return re.findall(r"[^\s{};,]+", css)

    for file in sorted(STATIC.glob("css/*.css")):
        css = file.read_text()
        assert words(minify_css(css)) == words(css), file.name


@pytest.mark.django_db
def test_static_files_are_compressed_and_cached_for_a_year(client, deployed):
    """WhiteNoise sends the Brotli copy of a hashed file with a one-year, immutable cache,
    and the plain name with a short one."""
    from django.test import Client

    client = Client()  # a new client: WhiteNoise reads the collected files when created
    html = client.get("/").content.decode()
    css = r'href="/static/(climpact_web/css/climpact\.[0-9a-f]{12}\.css)"'
    main = re.search(css, html).group(1)
    response = client.get(f"/static/{main}", HTTP_ACCEPT_ENCODING="gzip, br")
    assert response["Content-Encoding"] == "br"
    assert response["Cache-Control"] == "max-age=315360000, public, immutable"
    response = client.get(f"/static/{main}", HTTP_ACCEPT_ENCODING="gzip")
    assert response["Content-Encoding"] == "gzip"
    response = client.get("/static/climpact_web/css/climpact.css")
    assert "immutable" not in response["Cache-Control"]


@pytest.mark.django_db
def test_pages_are_gzipped_when_asked_for(client):
    assert client.get("/", HTTP_ACCEPT_ENCODING="gzip")["Content-Encoding"] == "gzip"
    assert not client.get("/").has_header("Content-Encoding")


def test_downloads_are_not_gzipped_again(tmp_path):
    """Text answers are compressed; streamed files (zips, netCDF, PNG) are left alone."""
    from django.http import FileResponse, HttpResponse
    from django.test import RequestFactory

    from climpact_web.middleware import CompressionMiddleware

    request = RequestFactory().get("/", HTTP_ACCEPT_ENCODING="gzip")
    (tmp_path / "out.zip").write_bytes(b"PK" + b"0" * 5000)
    answers = {
        "text/html; charset=utf-8": HttpResponse("<p>x</p>" * 100),
        "text/csv": HttpResponse("a,b\n" * 100, content_type="text/csv"),
        "application/json": HttpResponse("[1]" * 100, content_type="application/json"),
        "zip": FileResponse(open(tmp_path / "out.zip", "rb"), as_attachment=True),
        "png": HttpResponse(b"0" * 5000, content_type="image/png"),
    }
    for kind, answer in answers.items():
        compressed = CompressionMiddleware(lambda r, a=answer: a)(request)
        assert compressed.has_header("Content-Encoding") == (kind not in {"zip", "png"}), kind
        if hasattr(compressed, "file_to_stream"):
            compressed.file_to_stream.close()

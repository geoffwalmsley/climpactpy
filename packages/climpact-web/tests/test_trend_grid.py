"""Trends across stations (#238, the Workspace board): the trend grid (stations by
indices, each cell Sen's slope per decade on the trend scale), the selected column's
interval plot, Compare an index and the grid's CSV."""

import csv
import io
import re

import pytest
from test_add_stations import review_url, stage
from test_batch import created, media, metadata, run_worker, station  # noqa: F401
from test_batch_workspace import finished_batch, queued_batch
from test_indices_results import finished_analysis
from test_workspace import edit
from test_workspace_files import long_batch
from test_workspace_overview import empty_file

from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.worker import claim, run_job
from climpact_web.stations import trend_grid
from climpact_web.stations.models import RESERVED_SLUGS, Station

pytestmark = pytest.mark.django_db


def section(html: str) -> str:
    return html.split('id="trends"')[1].split("</section>")[0]


def header(html: str) -> list[str]:
    head = section(html).split("<thead>")[1].split("</thead>")[0]
    return re.findall(r'data-trend-col="([^"]+)"', head)


def test_the_overview_and_compare_show_the_trend_grid(client):
    run = long_batch(client, "a", "b", bad=["c"])
    space = run.workspace
    html = client.get(f"/w/{space.pk}/").content.decode()
    trends = section(html)
    assert "Trends across stations" in trends
    # The board's columns, those the stations have, in its order.
    columns = header(html)
    wanted = [c for c in trend_grid.DEFAULT_CODES if c in columns]
    assert columns == wanted and columns[:2] == ["TXx", "TNn"] and len(columns) >= 8
    # A row a station, in the overview's order; the failed one hatched, said in words.
    body = trends.split("<tbody>")[1].split("</tbody>")[0]
    rows = body.split("<tr")[1:]
    assert [re.search(r'title="([^"( ]+)', r).group(1) for r in rows] == ["a", "b", "c"]
    assert "trend-grid__empty" in rows[2] and "(no results)" in rows[2]
    assert rows[2].count("trend-cell--none") == len(columns)
    # Every cell writes its slope, signed with U+2212, and says it in words.
    cells = re.findall(r'class="num trend-cell trend-cell--([a-z12-]+)"', rows[0])
    assert len(cells) == len(columns)
    assert set(cells) <= {
        "increase-2",
        "increase-1",
        "decrease-1",
        "decrease-2",
        "not-significant",
        "invalid",
    }
    assert "95% interval" in rows[0] and "/decade" in rows[0]
    assert "-0." not in rows[0].split("sr-only")[0]
    # A cell is a link to the station's index page.
    station_a = space.stations.get(station_name="a")
    assert f'href="{station_a.url("result", "txx")}"' in rows[0]
    # The first column is plotted: each station with results, a link to its index page.
    assert 'data-selected data-trend-col="TXx"' in trends
    plot = trends.split('data-trend-plot="TXx"')[1].split("</aside>")[0].split("data-trend-plot")[0]
    assert "hidden" not in plot.split(">")[0]
    assert f'href="{station_a.url("result", "txx")}"' in plot
    assert "Not shown: c: no results" in plot
    assert "°C per decade" in plot and "CSV, all stations" in plot
    # The axis: symmetric about zero, round ends.
    ticks = re.findall(r'class="interval-plot__tick"[^>]*>([^<]+)<', plot)
    assert ticks[1] == "0" and ticks[0] == "−" + ticks[2][1:]
    # Every other column's plot is in the page, hidden, for js/trends.js.
    assert 'data-trend-plot="TNn" hidden' in trends
    assert "js/trends.js" in html

    # ?index= selects another column.
    html = client.get(f"/w/{space.pk}/?index=SU").content.decode()
    assert 'data-selected data-trend-col="SU"' in section(html)
    assert 'data-trend-plot="SU" hidden' not in section(html)

    # Compare an index: the tab is a link, and its page has the same grid.
    tabs = html.split('aria-label="Workspace sections"')[1].split("</nav>")[0]
    assert f'href="/w/{space.pk}/compare/" data-tab="compare">Compare an index</a>' in tabs
    page = client.get(f"/w/{space.pk}/compare/").content.decode()
    assert 'data-tab="compare" aria-current="page"' in page
    assert f'<h1 class="context-bar__name">{space.display_name}</h1>' in page
    assert header(page) == columns
    assert "Stations table" not in page


def test_choose_indices_is_remembered_for_the_workspace(client):
    run = long_batch(client, "a", "b")
    space = run.workspace
    url = f"/w/{space.pk}/"
    html = client.get(f"{url}?cols=SU&cols=TXx&cols=nonsense").content.decode()
    # The defaults' order first, unknown codes dropped.
    assert header(html) == ["TXx", "SU"]
    assert header(client.get(url).content.decode()) == ["TXx", "SU"]
    assert header(client.get(f"/w/{space.pk}/compare/").content.decode()) == ["TXx", "SU"]
    form = section(html).split('class="trend-choose__form"')[1].split("</form>")[0]
    assert 'value="TXx" checked' in form and 'value="TNn">' in form
    assert form.count('name="cols"') > 20
    back = client.get(f"{url}?cols=default").content.decode()
    assert header(back)[:2] == ["TXx", "TNn"]


def test_the_grid_csv_matches_the_station_trend_files(client):
    run = long_batch(client, "a", "b")
    space = run.workspace
    folder = run.job.output_dir / run.job.result["folder"]
    response = client.get(f"/w/{space.pk}/compare/trends.csv?cols=TXx&cols=SU&cols=TNn")
    assert response.status_code == 200
    assert response["Content-Disposition"].endswith('_trend_grid.csv"')
    rows = list(csv.DictReader(io.StringIO(response.content.decode())))
    # A column of the grid is a block of rows, the stations in order within it.
    assert [(r["index"], r["station"]) for r in rows] == [
        (i, s) for i in ("TXx", "SU", "TNn") for s in ("a", "b")
    ]
    codes = {"txx": "TXx", "su": "SU", "tnn": "TNn"}
    for name in ("a", "b"):
        lines = (folder / name / "trend" / f"{name}_trend.csv").read_text().splitlines()
        start = lines.index("Index,Frequency,StartYear,EndYear,Lower bound,Slope,Upper bound")
        checked = 0
        for line in lines[start + 1 :]:
            index, frequency, _s, _e, lower, slope, upper = line.split(",")
            if frequency != "annual" or index not in codes or slope == "NA":
                continue
            row = next(r for r in rows if r["station"] == name and r["index"] == codes[index])
            assert float(row["slope"]) == pytest.approx(10 * float(slope), abs=1e-9)
            assert float(row["lower"]) == pytest.approx(10 * float(lower), abs=1e-9)
            assert float(row["upper"]) == pytest.approx(10 * float(upper), abs=1e-9)
            checked += 1
        assert checked == 3
    # The plot's "CSV, all stations": one index.
    one = client.get(f"/w/{space.pk}/compare/trends.csv?cols=TXx")
    assert one["Content-Disposition"].endswith('_TXx_trend.csv"')
    assert {r["index"] for r in csv.DictReader(io.StringIO(one.content.decode()))} == {"TXx"}


def test_the_trends_wait_for_the_stations(client):
    run = queued_batch(client, "a", "b")
    space = run.workspace
    html = client.get(f"/w/{space.pk}/").content.decode()
    assert "The trends appear once every station has been calculated." in section(html)
    assert "trend-grid" not in section(html)


def rows_of(html: str) -> dict[str, str]:
    """The grid's rows by station name."""
    body = section(html).split("<tbody>")[1].split("</tbody>")[0]
    return {re.search(r'title="([^"( ]+)', r).group(1): r for r in body.split("<tr")[1:]}


def recalculating(client):
    """Stations a and b, then a new base period: both recalculate, a's run fails."""
    run = long_batch(client, "a", "b")
    space = run.workspace
    client.get(f"/w/{space.pk}/")  # the overview makes the stations of the batch
    a, b = space.stations.order_by("station_name")
    edit(client, a, "base-period", {"base_start": "2002", "base_end": "2003"})
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.indices_job.status == b.indices_job.status == Status.QUEUED
    return space, a, b


def finish_all():
    while (job := claim("test-worker")) is not None:
        run_job(job)


def test_out_of_date_trends_say_so_while_recalculating_and_after_a_failure(client):
    """#279: a station whose recalculation failed keeps its earlier results, out of date.
    The trend grid, its plot and its CSV say so, as the overview, its Indices and Files do."""
    space, a, b = recalculating(client)
    url = f"/w/{space.pk}/"
    # Still running: the trends wait, so no old trend is shown as if it were current.
    assert "The trends appear once every station has been calculated." in section(
        client.get(url).content.decode()
    )
    response = client.get(f"/w/{space.pk}/compare/trends.csv?cols=TXx")
    found = list(csv.DictReader(io.StringIO(response.content.decode())))
    assert all(r["out_of_date"] == "yes" for r in found)

    # a's recalculation fails; b's finishes with the new base period.
    Job.objects.filter(pk=a.indices_job.pk).update(status=Status.FAILED, error="Out of memory.")
    finish_all()
    html = client.get(url).content.decode()
    # The overview says Failed, the grid keeps a's earlier trends, tagged out of date.
    stations_table = html.split('aria-label="Stations table"')[1].split("</table>")[0]
    assert "Failed: Out of memory." in stations_table
    rows = rows_of(html)
    assert "trend-grid__stale" in rows["a"] and "out of date</span>" in rows["a"]
    assert "These trends are from before the last change." in rows["a"]
    assert "trend-cell--none" not in rows["a"]
    assert re.search(r"TXx [^<]+, significant, out of date|TXx [^<]+, out of date", rows["a"])
    assert "out of date" not in rows["b"] and "trend-grid__stale" not in rows["b"]
    # The interval plot tags a too.
    plot = section(html).split('data-trend-plot="TXx"')[1].split("data-trend-plot")[0]
    who = re.findall(r'class="interval-plot__line">(.*?)class="interval-plot__value"', plot)
    assert "out of date" in next(w for w in who if ">a</a>" in w)
    assert "out of date" not in next(w for w in who if ">b</a>" in w)
    # Its CSV: a column says which rows are out of date.
    response = client.get(f"/w/{space.pk}/compare/trends.csv?cols=TXx&cols=SU")
    found = list(csv.DictReader(io.StringIO(response.content.decode())))
    assert {r["station"]: r["out_of_date"] for r in found} == {"a": "yes", "b": "no"}
    # Its Indices and Files say the same.
    indices = client.get(a.url("results")).content.decode()
    assert "The recalculation failed" in indices
    assert "Download (out of date)" in client.get(f"/w/{space.pk}/files/").content.decode()


def test_a_failed_stations_out_of_date_trends_can_be_hatched_instead(client, monkeypatch):
    """The maintainer's choice (#279): with SHOW_FAILED_OUT_OF_DATE off, a failed station's
    out-of-date trends are hidden, its row hatched "· failed" as the Calculate board draws
    a failed row."""
    monkeypatch.setattr(trend_grid, "SHOW_FAILED_OUT_OF_DATE", False)
    space, a, _b = recalculating(client)
    Job.objects.filter(pk=a.indices_job.pk).update(status=Status.FAILED, error="Out of memory.")
    finish_all()
    html = client.get(f"/w/{space.pk}/").content.decode()
    rows = rows_of(html)
    assert "trend-grid__empty" in rows["a"] and "failed</span>" in rows["a"]
    assert "(no results)" not in rows["a"] and "out of date" not in rows["a"]
    assert set(re.findall(r"trend-cell--([a-z12-]+)", rows["a"])) == {"none"}
    plot = section(html).split('data-trend-plot="TXx"')[1].split("data-trend-plot")[0]
    assert "Not shown: a: failed" in plot


def test_a_cancelled_recalculation_reads_out_of_date_on_the_overview(client):
    """When a station's replacement is cancelled, the results it shows stay out of date: its
    row says so instead of Done, as its grid row does."""
    space, a, _b = recalculating(client)
    client.post(f"/jobs/{a.indices_job.pk}/cancel")
    finish_all()
    a.refresh_from_db()
    html = client.get(f"/w/{space.pk}/").content.decode()
    row = html.split(f'data-station="{a.slug}"')[1].split("</tr>")[0]
    assert ">Out of date</span>" in row
    assert "trend-grid__stale" in rows_of(html)["a"]


def test_a_station_with_no_indices_is_hatched_and_tagged(client):
    """#315: a station whose run made no index table (its TX, TN and PR all missing; #298)
    is hatched as a station without results and tagged "· no indices", as its row on the
    overview says, not drawn as a row of "–"; its plot says so; its CSV has no rows."""
    run = finished_batch(client, "a", "b")
    space = run.workspace
    staged = stage(client, url=f"/w/{space.pk}/add/", c__txt=empty_file())
    data = {"intent": "add", "file-0": "c.txt", "name-0": "Empty Hill", "lat-0": "-30"}
    assert client.post(review_url(staged), {**data, "lon-0": "150"}).status_code == 302
    finish_all()
    assert Station.objects.get(workspace=space, station_name="Empty Hill").indices_job.result[
        "skipped"
    ]
    for url in (f"/w/{space.pk}/", f"/w/{space.pk}/compare/"):
        html = client.get(url).content.decode()
        rows = rows_of(html)
        empty = rows["Empty"]
        assert "trend-grid__empty" in empty and "no indices</span>" in empty
        assert "(no results)" not in empty and "–" not in empty
        assert set(re.findall(r"trend-cell--([a-z12-]+)", empty)) == {"none"}
        assert "TXx: no indices" in empty
        assert "trend-grid__empty" not in rows["a"] and "no indices" not in rows["a"]
        plot = section(html).split('data-trend-plot="TXx"')[1].split("data-trend-plot")[0]
        assert re.search(r"Not shown: [^<]*Empty Hill: no indices", plot)
        assert ">Empty Hill</a>" not in plot
    response = client.get(f"/w/{space.pk}/compare/trends.csv?cols=TXx&cols=SU")
    found = list(csv.DictReader(io.StringIO(response.content.decode())))
    assert {r["station"] for r in found} == {"a", "b"}


def test_compare_in_a_workspace_of_one_station_opens_its_indices(client):
    analysis, _job = finished_analysis(client)
    response = client.get(f"/w/{analysis.workspace_id}/compare/")
    assert response["Location"] == analysis.url("results")


def test_compare_is_not_a_station_slug():
    assert "compare" in RESERVED_SLUGS


# ---- the cells -----------------------------------------------------------------------------


class _Entry:
    def __init__(self, name, source=True):
        self.name, self.source, self.why = name, object() if source else None, ""
        self.out_of_date = self.failed = False

        class _S:
            def url(self, *args):
                return "/" + "/".join(args)

        self.station = _S()


class _Card:
    def __init__(self, slope, lower, upper, valid=True):
        self.key = "txx"
        self.trend = (
            {
                "valid": True,
                "slope": slope,
                "lower": lower,
                "upper": upper,
                "significant": lower > 0 or upper < 0,
                "slope_text": f"{slope}",
                "per_decade_text": f"{slope} °C/decade",
                "interval_text": f"{lower} to {upper}",
            }
            if valid
            else {"valid": False}
        )

    @property
    def significant(self):
        return bool(self.trend.get("significant"))


CHOICE = trend_grid.Choice("TXx", "txx", "Hottest day", "°C", "", "heat", "Heat", "heat")


def test_two_steps_scaled_per_index_and_the_other_states():
    stations = [
        trend_grid._Station(_Entry("big"), {"TXx": _Card(0.4, 0.2, 0.6)}),
        trend_grid._Station(_Entry("small"), {"TXx": _Card(0.1, 0.05, 0.15)}),
        trend_grid._Station(_Entry("down"), {"TXx": _Card(-0.3, -0.5, -0.1)}),
        trend_grid._Station(_Entry("flat"), {"TXx": _Card(0.9, -0.2, 1.5)}),
        trend_grid._Station(_Entry("short"), {"TXx": _Card(0, 0, 0, valid=False)}),
        trend_grid._Station(_Entry("none", source=False), {}),
    ]
    # The scale is the largest significant slope: the not significant 0.9 does not count.
    scale = trend_grid._scale(stations, "TXx")
    assert scale == 0.4
    states = [trend_grid._cell(s, CHOICE, scale).state for s in stations]
    assert states == [
        "increase-2",
        "increase-1",
        "decrease-2",
        "not-significant",
        "invalid",
        "none",
    ]
    plot = trend_grid.interval_plot(stations, CHOICE)
    assert [b.state for b in plot.bars] == ["increase", "increase", "decrease", "not-significant"]
    assert plot.left_out == ["short: too few values for a trend", "none: no results"]
    # The axis reaches past every interval (1.5) to a round value.
    assert [t["text"] for t in plot.ticks] == ["−2", "0", "+2"]
    assert plot.bars[0].x == f"{180 + 0.4 / 2 * 172:.1f}"
    assert "3 of 4 stations" in plot.summary


def test_out_of_date_cells_and_dots_say_so():
    stations = [
        trend_grid._Station(_Entry("old"), {"TXx": _Card(0.4, 0.2, 0.6)}, out_of_date=True),
        trend_grid._Station(_Entry("new"), {"TXx": _Card(0.1, 0.05, 0.15)}),
        trend_grid._Station(_Entry("gone"), {}, failed=True),
    ]
    old, new, gone = (trend_grid._cell(s, CHOICE, 0.4) for s in stations)
    assert old.state == "increase-2" and old.label.endswith(", significant, out of date")
    assert new.state == "increase-1" and not new.label.endswith("out of date")
    assert gone.state == "none" and gone.label == "TXx: failed"
    assert [s.has_results for s in stations] == [True, True, False]
    plot = trend_grid.interval_plot(stations, CHOICE)
    assert [b.out_of_date for b in plot.bars] == [True, False]
    assert plot.bars[0].label.startswith("old: ") and plot.bars[0].label.endswith("out of date")
    assert plot.left_out == ["gone: failed"]


def test_a_station_with_no_indices_has_no_cells_and_no_dot():
    stations = [
        trend_grid._Station(_Entry("full"), {"TXx": _Card(0.4, 0.2, 0.6)}),
        trend_grid._Station(_Entry("empty"), {}, no_indices=True),
    ]
    full, empty = (trend_grid._cell(s, CHOICE, 0.4) for s in stations)
    assert empty.state == "none" and empty.text == "" and empty.label == "TXx: no indices"
    assert [s.has_results for s in stations] == [True, False]
    plot = trend_grid.interval_plot(stations, CHOICE)
    assert [b.name for b in plot.bars] == ["full"] and plot.left_out == ["empty: no indices"]

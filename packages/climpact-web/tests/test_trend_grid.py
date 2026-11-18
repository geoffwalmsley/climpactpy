"""Trends across stations (#238, the Workspace board): the trend grid (stations by
indices, each cell Sen's slope per decade on the trend scale), the selected column's
interval plot, Compare an index and the grid's CSV."""

import csv
import io
import re

import pytest
from test_batch import created, media, metadata, run_worker, station  # noqa: F401
from test_batch_workspace import queued_batch
from test_indices_results import finished_analysis
from test_workspace_files import long_batch

from climpact_web.stations import trend_grid
from climpact_web.stations.models import RESERVED_SLUGS

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

"""Overlay the series (#276): one index's series at every station of a workspace, on a page
of its own under Compare an index (``/w/<id>/compare/<code>/overlay``), from the interval
plot's "Overlay the series": a chart with a line a station in its categorical slot, the
legend, the text summary, the values table and the CSV (the workspace's Indices file cut
to the index)."""

import csv
import io
import json
import re

import pytest
from test_add_stations import review_url, stage
from test_batch import created, media, metadata, run_worker, station  # noqa: F401
from test_batch_workspace import finished_batch, queued_batch
from test_indices_results import finished_analysis
from test_trend_grid import finish_all, recalculating, section
from test_workspace_files import long_batch
from test_workspace_overview import empty_file

from climpact_web.jobs.models import Job, Status
from climpact_web.stations import overlay, trend_grid
from climpact_web.stations.models import Station

pytestmark = pytest.mark.django_db


def page(client, space, code="TXx", query="") -> str:
    response = client.get(f"/w/{space.pk}/compare/{code}/overlay{query}")
    assert response.status_code == 200
    return response.content.decode()


def chart_data(html: str) -> dict:
    script = r'<script id="overlay-chart-data" type="application/json">(.*?)</script>'
    found = re.search(script, html)
    return json.loads(found.group(1))


def legend(html: str) -> list[str]:
    block = html.split('class="chart__legend overlay-legend"')[1].split("</ul>")[0]
    return re.findall(r'class="overlay-legend__name" title="([^"]+)"', block)


def test_the_interval_plot_overlays_the_series_on_a_page_of_its_own(client):
    run = long_batch(client, "a", "b", bad=["c"])
    space = run.workspace
    # The interval plot's links, the board's order: Overlay the series, then the CSV.
    trends = section(client.get(f"/w/{space.pk}/compare/").content.decode())
    plot = trends.split('data-trend-plot="TXx"')[1].split("data-trend-plot")[0]
    url = f"/w/{space.pk}/compare/TXx/overlay"
    assert f'<a href="{url}">Overlay the series</a><a href=' in plot
    assert 'data-trend-plot="SU" hidden' in trends
    assert f'href="/w/{space.pk}/compare/SU/overlay"' in trends

    html = page(client, space)
    # Under Compare an index, with a way back to it at the index.
    assert 'data-tab="compare" aria-current="page"' in html
    assert f'href="/w/{space.pk}/compare/?index=TXx#trends"' in html
    assert f'<h1 class="context-bar__name">{space.display_name}</h1>' in html
    # The index codes first, its units and its step.
    assert "TXx · °C · annual values" in html
    assert '<code class="index-code">TXx</code> <span class="index-name__name">' in html
    # A line a station with results, in the overview's order, its slot in the legend.
    assert legend(html) == ["a", "b"]
    assert "swatch-chart-1" in html and "swatch-chart-2" in html and "swatch-chart-3" not in html
    svg = html.split('<svg class="index-plot"')[1].split("</svg>")[0]
    assert svg.count('class="overlay-plot__line"') == 2
    assert "overlay-plot__station--1" in svg and "overlay-plot__station--2" in svg
    # Axes: the y axis titled with the code and units, the years under it.
    assert "TXx °C</text>" in svg
    ticks = re.findall(r'class="index-plot__tick" x="[^"]+" y="320"[^>]*>(\d{4})<', svg)
    assert ticks and ticks[0] == "2000"
    # The station without results is named, as the interval plot names it.
    assert "Not shown: c: no results" in html
    # The text summary, which is also the chart's text alternative.
    summary = re.search(r'id="overlay-chart-summary">([^<]+)<', html).group(1)
    assert summary.startswith("TXx Hottest day, annual values at 2 stations, 2000–2011.")
    assert "Highest " in summary and "°C (" in summary and "have a significant trend." in summary
    assert f'role="img" aria-label="{summary}"' in html
    # The interactive chart's data: the same lines, in their slots.
    data = chart_data(html)
    assert data["kind"] == "overlay" and data["step"] == "year" and data["axis"] == "TXx °C"
    assert [(s["short"], s["token"]) for s in data["series"]] == [
        ("a", "--chart-1"),
        ("b", "--chart-2"),
    ]
    assert len(data["x"]) == len(data["series"][0]["values"]) and data["x"][0] == 2000
    assert "charts.js" in html
    # The table view: a row a year, most recent first, a column a station.
    table = html.split('class="table table--data overlay-table"')[1].split("</table>")[0]
    years = re.findall(r'<th scope="row" class="code">(\d{4})</th>', table)
    assert years == sorted(years, reverse=True) and len(years) == len(data["x"])
    assert table.count('<th scope="col" class="num">') == 2
    # The CSV: the workspace's Indices file cut to the index.
    assert f'href="/w/{space.pk}/compare/TXx/indices.csv" download' in html
    response = client.get(f"/w/{space.pk}/compare/TXx/indices.csv")
    assert response["Content-Disposition"].endswith('_TXx_indices.csv"')
    rows = list(csv.DictReader(io.StringIO(response.content.decode())))
    assert list(rows[0]) == ["station", "index", "year", "month", "value"]
    assert {r["index"] for r in rows} == {"TXx"} and {r["station"] for r in rows} == {"a", "b"}
    everything = client.get(f"/w/{space.pk}/files/indices.csv")
    whole = list(csv.DictReader(io.StringIO(b"".join(everything.streaming_content).decode())))
    assert rows == [r for r in whole if r["index"] == "TXx"]

    # An index no station has is not a page.
    assert client.get(f"/w/{space.pk}/compare/nonsense/overlay").status_code == 404


def test_more_than_eight_stations_draw_eight_and_the_user_chooses(client):
    names = [f"s{k}" for k in range(1, 11)]
    run = finished_batch(client, *names)
    space = run.workspace
    html = page(client, space)
    # The eight categorical slots, never cycled: the first eight stations drawn.
    assert legend(html) == names[:8]
    assert "swatch-chart-8" in html and "swatch-chart-9" not in html
    assert [s["token"] for s in chart_data(html)["series"]] == [f"--chart-{k}" for k in range(1, 9)]
    assert "The chart draws 8 of the 10; the table has them all." in html
    # The table has every station.
    table = html.split('class="table table--data overlay-table"')[1].split("</thead>")[0]
    assert table.count('<th scope="col" class="num">') == 10
    # Choose the stations drawn: a GET form, the drawn ones ticked.
    form = html.split('<details class="trend-choose"')[1].split("</details>")[0]
    assert "8 of 10" in form and "eight stations at most" in form
    assert form.count('name="stations"') == 10 and form.count(" checked") == 8
    assert "More than eight were chosen" not in form and form.split(">")[0] == ""  # closed
    slugs = {s.station_name: s.slug for s in Station.objects.filter(workspace=space)}
    chosen = page(client, space, query=f"?stations={slugs['s10']}&stations={slugs['s2']}")
    # In the overview's order, the slots from the first.
    assert legend(chosen) == ["s2", "s10"]
    assert [s["token"] for s in chart_data(chosen)["series"]] == ["--chart-1", "--chart-2"]
    # More than eight chosen: the first eight, and the page says so.
    query = "?" + "&".join(f"stations={slugs[n]}" for n in reversed(names))
    many = page(client, space, query=query)
    assert legend(many) == names[:8]
    assert "More than eight were chosen: the first eight are drawn." in many


def test_out_of_date_stations_are_drawn_and_tagged(client):
    """#279: a station whose recalculation failed keeps its earlier results, as the trend
    grid keeps its trends: drawn, tagged "· out of date" in the legend and the table."""
    space, a, _b = recalculating(client)
    # While a station is calculated, the series wait, as the trends do.
    html = page(client, space)
    assert "The series appear once every station has been calculated." in html
    assert "overlay-plot__line" not in html
    Job.objects.filter(pk=a.indices_job.pk).update(status=Status.FAILED, error="Out of memory.")
    finish_all()
    html = page(client, space)
    block = html.split('class="chart__legend overlay-legend"')[1].split("</ul>")[0]
    items = block.split("<li>")[1:]
    assert "out of date" in items[0] and 'title="a"' in items[0]
    assert "out of date" not in items[1]
    assert "The values of a are from before the last change." in html
    series = chart_data(html)["series"]
    assert series[0]["label"] == "a · out of date" and series[1]["label"] == "b"
    head = html.split('class="table table--data overlay-table"')[1].split("</thead>")[0]
    assert head.count("out of date") == 1


def test_a_station_with_no_indices_is_named_not_drawn(client):
    """#298, #315: a station whose run made no index table is left out and named, as the
    interval plot names it; its CSV has no rows."""
    run = finished_batch(client, "a", "b")
    space = run.workspace
    staged = stage(client, url=f"/w/{space.pk}/add/", c__txt=empty_file())
    data = {"intent": "add", "file-0": "c.txt", "name-0": "Empty Hill", "lat-0": "-30"}
    assert client.post(review_url(staged), {**data, "lon-0": "150"}).status_code == 302
    finish_all()
    html = page(client, space)
    assert legend(html) == ["a", "b"]
    assert "Not shown: Empty Hill: no indices" in html
    response = client.get(f"/w/{space.pk}/compare/TXx/indices.csv")
    rows = list(csv.DictReader(io.StringIO(response.content.decode())))
    assert {r["station"] for r in rows} == {"a", "b"}


def test_the_overlay_waits_and_a_workspace_of_one_opens_its_indices(client):
    run = queued_batch(client, "a", "b")
    html = page(client, run.workspace)
    assert "The series appear once every station has been calculated." in html
    assert client.get(f"/w/{run.workspace.pk}/compare/TXx/indices.csv").status_code == 404
    analysis, _job = finished_analysis(client)
    response = client.get(f"/w/{analysis.workspace_id}/compare/TXx/overlay")
    assert response["Location"] == analysis.url("results")


# ---- the module ----------------------------------------------------------------------------


class _Plot:
    def __init__(self, x, values, step="year"):
        self.x, self.values, self.step = x, values, step


class _Card:
    key, main, units = "txx", "txx_ANN", "°C"

    def __init__(self, significant=True):
        self.trend = {"valid": True, "significant": significant}


class _Entry:
    def __init__(self, name, source=True):
        self.name, self.source = name, object() if source else None

        class _S:
            slug = name

            def url(self, *args):
                return "/" + "/".join(args)

        self.station = _S()


def _station(name, x, values, **kw):
    plots = {"txx_ANN": _Plot(x, values)} if x else {}
    cards = {"TXx": _Card()} if x else {}
    return trend_grid._Station(_Entry(name), cards, plots=plots, **kw)


CHOICE = trend_grid.Choice("TXx", "txx", "Hottest day", "°C", "", "heat", "Heat", "heat")
NAN = float("nan")


def test_the_years_are_shared_and_gaps_stay_gaps():
    stations = [
        _station("early", [2000, 2001, 2002], [30.0, NAN, 32.5]),
        _station("late", [2002, 2003], [31.0, 33.0]),
        _station("blank", [2000, 2001], [NAN, NAN]),
        trend_grid._Station(_Entry("gone", source=False), {}),
        trend_grid._Station(_Entry("empty"), {}, no_indices=True),
        _station("old", [2001], [35.0], out_of_date=True),
    ]
    found = overlay.overlay(stations, CHOICE, None)
    assert found.x == [2000.0, 2001.0, 2002.0, 2003.0]
    assert [line.name for line in found.lines] == ["early", "late", "old"]
    assert found.lines[0].values == [30.0, None, 32.5, None]
    assert found.lines[1].values == [None, None, 31.0, 33.0]
    assert found.left_out == [
        "blank: every value missing",
        "gone: no results",
        "empty: no indices",
    ]
    assert [line.slot for line in found.lines] == [1, 2, 3]
    # A value with no neighbour is a dot (a path of one point draws nothing).
    assert len(found.lines[0].dots) == 2 and len(found.lines[2].dots) == 1
    assert found.lines[1].path.count("L") == 1
    # The summary: the series, its years, its extremes, the trends, the old values.
    assert found.summary.startswith("TXx Hottest day, annual values at 3 stations, 2000–2003.")
    assert "Highest 35\u00a0°C (old, 2001); lowest 30\u00a0°C (early, 2000)." in found.summary
    assert "3 of 3 stations have a significant trend." in found.summary
    assert "The values of old are from before the last change." in found.summary
    # The table: most recent first, empty for a missing value.
    assert found.rows[0] == {"when": "2003", "values": ["", "33", ""]}
    # The minus sign of the number rules on the axis.
    cold = overlay.overlay([_station("c", [2000, 2001], [-5.0, 2.0])], CHOICE, None)
    assert any(t["text"].startswith("−") for t in cold.chart["y_ticks"])
    assert cold.chart["zero"] is not None


def test_slots_are_never_cycled():
    stations = [_station(f"s{k}", [2000, 2001], [k, k + 1.0]) for k in range(12)]
    found = overlay.overlay(stations, CHOICE, None)
    assert found.too_many and len(found.drawn) == 8 and not found.chosen_too_many
    assert [line.slot for line in found.lines] == [1, 2, 3, 4, 5, 6, 7, 8, 0, 0, 0, 0]
    assert [s["token"] for s in overlay.payload(found)["series"]][-1] == "--chart-8"
    picked = overlay.overlay(stations, CHOICE, ["s11", "s3", "unknown"])
    assert [(line.name, line.slot) for line in picked.drawn] == [("s3", 1), ("s11", 2)]
    assert not picked.chosen_too_many
    # Nothing known chosen: the first eight.
    assert len(overlay.overlay(stations, CHOICE, ["unknown"]).drawn) == 8

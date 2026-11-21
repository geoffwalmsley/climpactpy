"""The gridded map's Base mean, Anomaly and Trend views and the grid mean (#296, the
GridMap board), from the run's trends.nc (#290): the diverging scales (eight bins
symmetric about zero, reversed for the cooler-or-drier indices), a cell's trend on the
map against trends.nc and against climpact.trends, the dots on Trend, the mean over the
grid in the cell pane, the downloads following the view, and a run without trends.nc;
a monthly file's four views and grid mean of the month from trends.nc's monthly
variables (#348), against climpact.trends on the month's series; and, for a run whose
trends.nc has none, Base mean, Anomaly and grid mean computed from its values, against
climpact.gridded.trends on the month's series."""

import csv
import io

import netCDF4
import numpy as np
import pytest
from test_gridded_map import finished_run, read_png, write_index

from climpact.gridded import trends as core
from climpact.gridded.trends import base_means, cell_weights, grid_means, write_grid_trends
from climpact.trends import sen_trend
from climpact_web.core import numbers, tokens
from climpact_web.gridded import map_views, maps

pytestmark = pytest.mark.django_db

YEARS, NY, NX = 12, 4, 5  # 2001-2012; trends need at least ten values
BASE = (2001, 2010)


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    settings.JOB_RETENTION_DAYS = 7
    map_views._cache.clear()
    map_views._edges.clear()
    map_views._names.clear()
    maps._cache.clear()
    maps._edges.clear()
    maps._too_large.clear()
    return settings


def series_values(seed: int = 0) -> np.ndarray:
    """``(YEARS, NY, NX)``: each cell its own slope per year (some zero) and noise, the
    corner cell missing."""
    rng = np.random.default_rng(seed)
    slopes = np.linspace(-0.6, 0.6, NY * NX).reshape(NY, NX)
    slopes[1, :] = 0.0
    years = np.arange(YEARS)[:, None, None]
    values = 20 + slopes * years + rng.normal(0, 0.8, (YEARS, NY, NX))
    values[:, 0, 0] = np.nan
    return values.astype(np.float32)


def annual(name: str, units: str = "degrees_C", seed: int = 0):
    def write(path):
        values = series_values(seed)
        if units == "days":
            values = np.abs(values)
        write_index(path, name, years=YEARS, ny=NY, nx=NX, values=values, units=units)
        with netCDF4.Dataset(path, "a") as nc:
            nc.index_calculation_frequency = "yr"

    return write


def spi(path):
    """A monthly SPI file with its three scales, as the core writes them."""
    steps = YEARS * 12
    rng = np.random.default_rng(3)
    with netCDF4.Dataset(path, "w") as nc:
        nc.index_calculation_frequency = "mon"
        for dim, n in (("scale", 3), ("time", steps), ("lat", NY), ("lon", NX)):
            nc.createDimension(dim, n)
        nc.createVariable("scale", "i4", ("scale",))[:] = [1, 2, 3]
        t = nc.createVariable("time", "f8", ("time",))
        t.units, t.calendar = "days since 2001-01-01", "standard"
        t[:] = np.arange(steps) * 30.4 + 15
        nc.createVariable("lat", "f8", ("lat",))[:] = np.linspace(-40, -10, NY)
        nc.createVariable("lon", "f8", ("lon",))[:] = np.linspace(110, 155, NX)
        v = nc.createVariable("spi", "f4", ("scale", "time", "lat", "lon"),
                              fill_value=np.float32(1e20))  # fmt: skip
        v.units, v.long_name = "unitless", "spi"
        v[:] = rng.normal(0, 1, (3, steps, NY, NX)).astype(np.float32)


def monthly_values(seed: int = 5) -> np.ndarray:
    """``(YEARS * 12, NY, NX)``: a seasonal cycle, a trend per cell and noise; the corner
    cell missing and a few values of other cells missing."""
    rng = np.random.default_rng(seed)
    steps = YEARS * 12
    season = 8 * np.cos(2 * np.pi * np.arange(steps) / 12)[:, None, None]
    slopes = np.linspace(-0.05, 0.05, NY * NX).reshape(NY, NX)
    values = 25 + season + slopes * np.arange(steps)[:, None, None]
    values = values + rng.normal(0, 1.2, (steps, NY, NX))
    values[:, 0, 0] = np.nan
    values[rng.random(values.shape) < 0.05] = np.nan
    return values.astype(np.float32)


def monthly(name: str = "txx", seed: int = 5, lat_name: str = "lat"):
    def write(path):
        write_index(path, name, years=YEARS, ny=NY, nx=NX, monthly=True,
                    values=monthly_values(seed))  # fmt: skip
        with netCDF4.Dataset(path, "a") as nc:
            nc.index_calculation_frequency = "mon"
            if lat_name != "lat":  # a grid whose Y is not latitude (a projection's y)
                nc.renameDimension("lat", lat_name)
                nc.renameVariable("lat", lat_name)

    return write


def month_series(path, name: str, month: int) -> tuple[np.ndarray, list[int]]:
    """The month's values in every year, ``(years, cells)``, read as the core reads an
    index file (float64, NaN missing), and the years."""
    with netCDF4.Dataset(path) as nc:
        dates = netCDF4.num2date(nc["time"][:], nc["time"].units, nc["time"].calendar)
        steps = [t for t, d in enumerate(dates) if d.month == month]
        var = nc[name]
        var.set_auto_mask(True)
        values = np.ma.filled(np.ma.asarray(var[steps]).astype(float), np.nan)
    return values.reshape(len(steps), -1), [int(dates[t].year) for t in steps]


def run_with_trends(client, files: dict, trends: bool = True, monthly: dict | None = None,
                    month_trends: bool = True):  # fmt: skip
    """A finished run of ``files`` (annual) and ``monthly`` files, and its trends.nc;
    without ``month_trends``, a trends.nc of the annual files alone, as written before
    #348 (the annual variables are the same)."""
    names = {**files, **(monthly or {})}
    if trends:
        names["trends.nc"] = lambda path: None
    run = finished_run(client, names)
    job = run.indices_job
    if trends:
        (job.output_dir / "trends.nc").unlink(missing_ok=True)
        paths = [job.output_dir / n for n in names if n != "trends.nc"]
        if not month_trends:
            paths = [job.output_dir / n for n in files]
        write_grid_trends(paths, job.output_dir / "trends.nc", *BASE)
    run.options = {**run.options, "base_start": BASE[0], "base_end": BASE[1]}
    run.save()
    return run


def page(client, run, **query) -> str:
    response = client.get(f"/gridded/{run.pk}/", query)
    assert response.status_code == 200
    return response.content.decode()


# ---- The scales -------------------------------------------------------------------------------


def test_symmetric_edges():
    assert map_views.symmetric_edges(0.9) == [-1.0, -0.75, -0.5, -0.25, 0, 0.25, 0.5, 0.75, 1.0]
    assert map_views.symmetric_edges(3.2) == [-4, -3, -2, -1, 0, 1, 2, 3, 4]
    edges = map_views.symmetric_edges(37.0)
    assert edges[4] == 0 and edges[-1] >= 37 and edges == [-e for e in reversed(edges)]
    assert map_views.symmetric_edges(0.0) == [-4, -3, -2, -1, 0, 1, 2, 3, 4]


@pytest.mark.parametrize(
    "kind, view, scale",
    [
        ("temp", "year", "temp"),
        ("temp", "base", "temp"),
        ("temp", "anomaly", "div-temp"),
        ("warm", "trend", "div-temp"),
        ("cool", "trend", "div-temp-r"),  # FD, ID, CSDI, TX10p, TN10p: more is cooler
        ("cool", "base", "cool"),
        ("wet", "anomaly", "div-wet"),
        ("dry", "trend", "div-wet-r"),  # CDD: more is drier
        ("dry", "anomaly", "div-wet-r"),
        ("spi", "year", "div-wet"),  # SPI and SPEI: low is dry
        ("spi", "trend", "div-wet"),
    ],
)
def test_the_scale_follows_the_view_and_the_kind(kind, view, scale):
    assert map_views.scale_of(kind, view) == scale


def test_diverging_palettes_are_the_tokens():
    palette = tokens.chart_palette()
    for theme in ("light", "dark"):
        div = palette[theme]["map_diverging"]
        assert map_views.palette("div-temp", theme) == div["temp"]
        assert map_views.palette("div-temp-r", theme) == div["temp"][::-1]
        assert map_views.palette("div-wet-r", theme) == div["wet"][::-1]
        assert map_views.palette("warm", theme) == palette[theme]["map_sequential"]["warm"]


def test_fd_and_cdd_trends_use_the_reversed_scale(client):
    """An increase in frost days (FD) or dry days (CDD) is drawn as cooler or drier: the
    trend map's palette is the diverging scale reversed, so its first (most negative)
    bin is the warm or wet end."""
    run = run_with_trends(client, {
        "fd_ANN_m_e_r_2001-2012.nc": annual("fd", "days"),
        "cdd_ANN_m_e_r_2001-2012.nc": annual("cdd", "days", seed=1),
        "txx_ANN_m_e_r_2001-2012.nc": annual("txx"),
    })  # fmt: skip
    light = tokens.chart_palette()["light"]["map_diverging"]
    for index, family, scale in (("fd", "temp", "div-temp-r"), ("cdd", "wet", "div-wet-r"),
                                 ("txx", "temp", "div-temp")):  # fmt: skip
        html = page(client, run, index=index, view="trend")
        assert f"gmap-legend ramp-{scale}" in html, index
        _pixels, colours, _alpha = read_png(
            client.get(f"/gridded/{run.pk}/map.png", {"index": index, "view": "trend"}).content
        )
        expected = light[family][::-1] if scale.endswith("-r") else light[family]
        assert ["#{:02x}{:02x}{:02x}".format(*c) for c in colours[:8]] == expected, index


# ---- A cell's trend on the map ------------------------------------------------------------------


def test_a_cell_trend_on_the_map_is_trends_nc_and_climpact_trends(client):
    """The Trend view's value of a cell (the map's values, its CSV and the pane) is
    trends.nc's slope, which is climpact.trends.sen_trend of the cell's series per
    decade; the pane's base mean is trends.nc's too."""
    run = run_with_trends(client, {"txx_ANN_m_e_r_2001-2012.nc": annual("txx")})
    out = run.indices_job.output_dir
    with netCDF4.Dataset(out / "trends.nc") as nc:
        slope = np.ma.filled(nc["txx_slope"][:], np.nan)
        lower = np.ma.filled(nc["txx_lower"][:], np.nan)
        upper = np.ma.filled(nc["txx_upper"][:], np.nan)
        base = np.ma.filled(nc["txx_base_mean"][:], np.nan)
    values = series_values().astype(float)
    y, x = 2, 3
    lo, sl, hi = sen_trend(values[:, y, x])
    assert slope[y, x] == pytest.approx(sl * 10, rel=1e-12)
    assert (lower[y, x], upper[y, x]) == pytest.approx((lo * 10, hi * 10), rel=1e-12)

    # The map's values (float32, north first; the file's rows are south first).
    response = client.get(f"/gridded/{run.pk}/map.f32", {"index": "txx", "view": "trend"})
    grids = np.frombuffer(response.content, "<f4").reshape(2, NY, NX)
    assert grids[0][NY - 1 - y, x] == pytest.approx(slope[y, x], rel=1e-6)
    significant = (lower > 0) | (upper < 0)
    assert np.array_equal(grids[1][::-1] == 1, significant)
    assert 0 < significant.sum() < np.isfinite(slope).sum()  # the data has both kinds

    # The map's CSV: the slope and its interval.
    text = client.get(f"/gridded/{run.pk}/map.csv", {"index": "txx", "view": "trend"})
    assert 'filename="txx_trend_2001-2012.csv"' in text["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(text.content.decode())))
    assert rows[0] == ["latitude", "longitude", "txx_slope", "txx_lower", "txx_upper"]
    row = rows[1 + y * NX + x]
    assert float(row[2]) == pytest.approx(slope[y, x], abs=1e-6)

    # The pane: the slope, its interval and the base mean.
    html = page(client, run, index="txx", view="trend", cell=f"{y},{x}")
    assert numbers.per_decade(slope[y, x], "°C") in html
    assert numbers.interval(lower[y, x], upper[y, x], "°C") in html
    assert numbers.with_unit(numbers.number(base[y, x]), "degrees_C") in html


def test_the_trend_view_dots_the_significant_cells(client):
    """Trend: the legend counts the cells whose interval excludes zero, and the PNG draws
    each cell k pixels a side with a dot in the middle of each such cell, in the colour
    that stands out from its bin."""
    for ny, nx, cell in ((4, 5, 144.0), (47, 55, 13.1), (700, 900, 0.8)):
        k = map_views.dot_factor(ny, nx, cell)
        mask = map_views.dot_mask(k, cell)
        assert ny * nx * k * k <= 4_000_000 * 1.6 and mask[k // 2, k // 2]
        assert mask.sum() <= k * k / 4  # the cell's bin stays in view around its dot
    run = run_with_trends(client, {"txx_ANN_m_e_r_2001-2012.nc": annual("txx")})
    trends = map_views.read_trends(run.indices_job.output_dir / "trends.nc", "txx")
    significant = trends.significant
    html = page(client, run, index="txx", view="trend")
    count, total = int(significant.sum()), int(np.isfinite(trends.slope).sum())
    assert f"Dot: the 95% interval excludes zero ({count} of {total} cells)" in html
    assert "Sen&#x27;s slope per decade, 2001–2012." in html
    assert "txx, trend 2001–2012 (°C/decade)".replace("txx", "TXx") in html
    pixels, colours, alpha = read_png(
        client.get(f"/gridded/{run.pk}/map.png", {"index": "txx", "view": "trend"}).content
    )
    k = pixels.shape[0] // NY  # pixels a side per cell: a small dot in a large cell
    assert k >= 2 and pixels.shape == (NY * k, NX * k) and len(colours) == 8 + 2 + 1
    centres = pixels[k // 2 :: k, k // 2 :: k][::-1]  # the file's order: south first
    assert np.array_equal(np.isin(centres, (8, 9)), significant & np.isfinite(trends.slope))
    corners = pixels[::k, ::k]
    assert (corners < 8).sum() == total  # the other pixels: the bins
    assert pixels[-1, 0] == 10 and alpha[10] == 0  # (0, 0) has no value: transparent


def test_base_mean_and_anomaly_views(client):
    run = run_with_trends(client, {"txx_ANN_m_e_r_2001-2012.nc": annual("txx")})
    trends = map_views.read_trends(run.indices_job.output_dir / "trends.nc", "txx")
    html = page(client, run, index="txx", view="base")
    assert "Mean of 2001–2010." in html and "gmap-legend ramp-temp" in html
    assert "gmap-stepper" not in html  # one map for the base period: no stepper
    response = client.get(f"/gridded/{run.pk}/map.f32", {"index": "txx", "view": "base"})
    assert np.allclose(np.frombuffer(response.content, "<f4").reshape(NY, NX)[::-1],
                       trends.base_mean, equal_nan=True)  # fmt: skip

    html = page(client, run, index="txx", view="anomaly", year=2012)
    assert "2012 minus the 2001–2010 mean." in html and "ramp-div-temp" in html
    assert "gmap-stepper" in html
    response = client.get(f"/gridded/{run.pk}/map.f32", {"index": "txx", "view": "anomaly",
                                                       "year": 2012})  # fmt: skip
    anomaly = series_values()[-1].astype(float) - trends.base_mean
    got = np.frombuffer(response.content, "<f4").reshape(NY, NX)[::-1]
    assert np.allclose(got, anomaly, equal_nan=True, atol=1e-5)
    # The breaks are symmetric about zero and the same for every year.
    legend = [page(client, run, index="txx", view="anomaly", year=y) for y in (2003, 2012)]
    ticks = [h.split('aria-label="Bin breaks">')[1].split("</ol>")[0] for h in legend]
    assert ticks[0] == ticks[1] and "<li>0" in ticks[0]
    query = {"index": "txx", "view": "anomaly", "year": 2012}
    name = client.get(f"/gridded/{run.pk}/map.csv", query)["Content-Disposition"]
    assert 'filename="txx_anomaly_2012.csv"' in name


# ---- The grid mean ------------------------------------------------------------------------------


def test_the_mean_over_the_grid_in_the_pane(client):
    run = run_with_trends(client, {"txx_ANN_m_e_r_2001-2012.nc": annual("txx")})
    trends = map_views.read_trends(run.indices_job.output_dir / "trends.nc", "txx")
    html = page(client, run, index="txx")
    assert "data-gmap-series>Mean over the grid</a>" in html
    html = page(client, run, index="txx", series="grid")
    assert "Mean over 19 cells" in html  # 20 cells, one with no value
    assert "Weighted by the cosine of latitude; cells with no value left out." in html
    lo, sl, hi = sen_trend(trends.grid_mean)
    assert numbers.per_decade(sl * 10, "°C") in html
    # Go to shows a cell again.
    goto = html.split("data-gmap-goto>")[1].split("</form>")[0]
    assert 'name="series"' not in goto and 'name="goto"' in goto
    response = client.get(f"/gridded/{run.pk}/series.csv", {"index": "txx", "series": "grid"})
    assert 'filename="txx_grid_mean.csv"' in response["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0] == ["year", "txx_grid_mean"] and len(rows) == YEARS + 1
    weights = np.cos(np.deg2rad(np.linspace(-40, -10, NY)))[:, None] * np.ones((1, NX))
    v = series_values()[-1].astype(float)
    ok = np.isfinite(v)
    assert float(rows[-1][1]) == pytest.approx((v * weights)[ok].sum() / weights[ok].sum(),
                                               abs=1e-5)  # fmt: skip


# ---- SPI and SPEI, monthly files, runs without trends.nc ---------------------------------------


def test_spi_views_are_of_the_12_month_scale_in_december(client):
    run = run_with_trends(client, {}, monthly={"spi_MON_m_e_r_2001-2012.nc": spi})
    html = page(client, run, index="spi", freq="MON", scale="3", month=5)
    assert "ramp-div-wet" in html  # Year: SPI's classes on the wet diverging scale
    assert "<li>0.0</li>" in html and "gmap-legend__ticks" in html
    trend_link = html.split('aria-label="View">')[1].split("</div>")[0]
    assert "view=trend" in trend_link and "scale=12" in trend_link and "month=12" in trend_link
    html = page(client, run, index="spi", freq="MON", scale="3", month=5, view="anomaly")
    assert '<span class="gmap-stepper__label" aria-live="polite">Dec 2012</span>' in html
    assert "12 months</a>" in html and 'aria-disabled="true"' in html  # 3 and 6 months off
    html = page(client, run, index="spi", freq="MON", view="trend")
    assert "ramp-div-wet" in html and "ramp-div-wet-r" not in html


def test_a_run_without_trends_keeps_year(client):
    old = run_with_trends(client, {"txx_ANN_m_e_r_2001-2012.nc": annual("txx")}, trends=False)
    html = page(client, old, index="txx", view="trend", series="grid")
    assert "This run has no trends file (trends.nc)" in html
    assert "The value in 2012." in html and "Selected cell</a>" in html
    assert client.get(f"/gridded/{old.pk}/map.csv", {"index": "txx", "view": "trend"}).content \
        .decode().splitlines()[0] == "latitude,longitude,txx"  # fmt: skip

    job = old.indices_job
    job.params = {"trends": False}
    job.save()
    html = page(client, old, index="txx")
    assert "This run was calculated without its trends" in html


# ---- Monthly files (#348) ---------------------------------------------------------------------

MONTHLY = {"txx_MON_m_e_r_2001-2012.nc": monthly()}
ANNUAL = {"txx_ANN_m_e_r_2001-2012.nc": annual("txx")}


@pytest.mark.parametrize("stripe", [None, 7])  # one stripe of rows; rows of 7 cells (1 row)
def test_a_months_base_mean_and_grid_mean_are_the_cores(client, monkeypatch, stripe):
    """A monthly file's month: each cell's base mean is climpact.gridded.trends.base_means
    of the month's series, and the grid mean its grid_means with the cells' cos-latitude
    weights, the month's values read as the core reads them; in stripes of rows as
    write_grid_trends, when the grid is wider than one."""
    if stripe:
        monkeypatch.setattr(core, "MAX_CELLS", stripe)
    run = run_with_trends(client, ANNUAL, monthly=MONTHLY, month_trends=False)
    path = run.indices_job.output_dir / "txx_MON_m_e_r_2001-2012.nc"
    layer = maps.open_layer(path, path.name)
    for month in (1, 5, 12):
        found = map_views.month_trends(path, layer, month, BASE)
        values, years = month_series(path, "txx", month)
        assert found.years == years == list(range(2001, 2001 + YEARS))
        expected = base_means(values.T, years, *BASE).reshape(NY, NX)
        assert np.array_equal(found.base_mean, expected, equal_nan=True)
        weights = cell_weights(np.broadcast_to(np.linspace(-40, -10, NY)[:, None], (NY, NX)))
        expected = grid_means(values, weights.reshape(-1))
        if stripe:  # summed stripe by stripe, as the core does
            assert np.allclose(found.grid_mean, expected, rtol=1e-14, atol=0)
        else:
            assert np.array_equal(found.grid_mean, expected)
        assert found.slope is None and found.month == month and found.base == BASE


def test_a_months_trend_on_the_map_is_trends_nc_and_climpact_trends(client, monkeypatch):
    """A monthly file's Trend of the chosen month: the map's values, dots, CSV and the
    pane's slope are trends.nc's month (``txx_MON_slope``), which is
    climpact.trends.sen_trend of each cell's series of the month per decade, in float32;
    Base mean and the grid mean are trends.nc's month too."""
    run = run_with_trends(client, ANNUAL, monthly=MONTHLY)
    out = run.indices_job.output_dir
    values, years = month_series(out / "txx_MON_m_e_r_2001-2012.nc", "txx", 5)
    ref = np.array([sen_trend(c) for c in values.T]).reshape(NY, NX, 3) * 10
    found = map_views.read_month_trends(out / "trends.nc", "txx", 5)
    assert np.array_equal(found.slope, np.float32(ref[..., 1]).astype(float), equal_nan=True)
    assert np.array_equal(found.lower, np.float32(ref[..., 0]).astype(float), equal_nan=True)
    assert found.month == 5 and found.years == years and found.period == (2001, 2012)
    assert map_views.read_month_trends(out / "trends.nc", "tnn", 5) is None

    query = {"index": "txx", "freq": "MON", "month": 5, "year": 2012}
    html = page(client, run, **query)
    views = html.split('aria-label="View">')[1].split("</div>")[0]
    assert "view=trend" in views and 'aria-disabled="true"' not in views
    assert "gmap-controls__note" not in html  # nothing unavailable
    html = page(client, run, **query, view="trend")
    assert "Sen&#x27;s slope per decade of May, 2001–2012." in html
    assert "TXx, trend May 2001–2012 (°C/decade)" in html and "ramp-div-temp" in html
    assert "gmap-stepper" not in html  # one map for the month: no stepper, as Base mean
    significant = (found.lower > 0) | (found.upper < 0)
    count, total = int(significant.sum()), int(np.isfinite(found.slope).sum())
    assert f"Dot: the 95% interval excludes zero ({count} of {total} cells)" in html
    assert 0 < count < total
    got = client.get(f"/gridded/{run.pk}/map.f32", {**query, "view": "trend"}).content
    grids = np.frombuffer(got, "<f4").reshape(2, NY, NX)
    assert np.array_equal(grids[0][::-1], np.float32(ref[..., 1]), equal_nan=True)
    assert np.array_equal(grids[1][::-1] == 1, significant)
    response = client.get(f"/gridded/{run.pk}/map.csv", {**query, "view": "trend"})
    assert 'filename="txx_05_trend_2001-2012.csv"' in response["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0] == ["latitude", "longitude", "txx_slope", "txx_lower", "txx_upper"]
    assert float(rows[1 + 2 * NX + 3][2]) == pytest.approx(ref[2, 3, 1], abs=1e-5)
    download = client.get(f"/gridded/{run.pk}/map.png", {**query, "view": "trend",
                                                         "download": "1"})  # fmt: skip
    assert 'filename="txx_05_trend_2001-2012.png"' in download["Content-Disposition"]
    with monkeypatch.context() as m:  # no step of the index file read without a cell
        m.setattr(maps, "grid_values", lambda *a, **k: pytest.fail("read a step"))
        for view in ("trend", "base"):
            response = client.get(f"/gridded/{run.pk}/map.png", {**query, "view": view})
            assert response.status_code == 200, view

    # The pane: the cell's slope and interval, and its base mean, from trends.nc's month.
    html = page(client, run, **query, view="trend", cell="2,3")
    assert numbers.per_decade(found.slope[2, 3], "°C") in html
    assert numbers.interval(found.lower[2, 3], found.upper[2, 3], "°C") in html
    assert numbers.with_unit(numbers.number(found.base_mean[2, 3]), "degrees_C") in html
    base = base_means(values.T, years, *BASE).reshape(NY, NX)
    assert np.allclose(found.base_mean, base, rtol=1e-6, equal_nan=True)
    # The grid mean of May: trends.nc's, which is grid_means of the month's series.
    response = client.get(f"/gridded/{run.pk}/series.csv", {**query, "series": "grid"})
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    weights = cell_weights(np.broadcast_to(np.linspace(-40, -10, NY)[:, None], (NY, NX)))
    expected = grid_means(values, weights.reshape(-1))
    assert [float(r[1]) for r in rows[1:]] == pytest.approx(expected, rel=1e-6)


def test_a_monthly_file_of_a_run_without_monthly_trends(client):
    """A run whose trends.nc has no monthly trends (calculated before #348): Trend is
    unavailable, with the reason; Base mean, Anomaly and the grid mean are computed."""
    run = run_with_trends(client, ANNUAL, monthly=MONTHLY, month_trends=False)
    html = page(client, run, index="txx", freq="MON", month=5, year=2012)
    views = html.split('aria-label="View">')[1].split("</div>")[0]
    assert "view=base" in views and "view=anomaly" in views and "view=trend" not in views
    reason = ("The run&#x27;s trends file has no monthly trends: it was calculated before "
              "Climpact wrote them. Start it again on Set-up to add them.")  # fmt: skip
    assert f'aria-disabled="true" title="{reason}"' in views
    assert reason in html.split("gmap-controls__note")[1]
    assert "data-gmap-series>Mean over the grid</a>" in html
    html = page(client, run, index="txx", freq="MON", month=5, year=2012, view="trend")
    assert "The value in May 2012." in html  # an address asking for Trend shows Year
    job = run.indices_job
    job.params = {**(job.params or {}), "trends": False}
    job.result = {**job.result, "files": [f for f in job.result["files"] if f != "trends.nc"]}
    job.save()
    html = page(client, run, index="txx", freq="MON", month=5, year=2012)
    assert "This run was calculated without its trends, so it has no trend." in html


def test_a_monthly_files_base_mean_anomaly_and_grid_mean_on_the_page(client):
    run = run_with_trends(client, ANNUAL, monthly=MONTHLY, month_trends=False)
    path = run.indices_job.output_dir / "txx_MON_m_e_r_2001-2012.nc"
    values, years = month_series(path, "txx", 5)
    base = base_means(values.T, years, *BASE).reshape(NY, NX)

    html = page(client, run, index="txx", freq="MON", month=5, year=2012)
    assert "data-gmap-series>Mean over the grid</a>" in html

    html = page(client, run, index="txx", freq="MON", month=5, year=2012, view="base")
    assert "Mean of May in 2001–2010." in html and "gmap-legend ramp-temp" in html
    assert "TXx, base mean May 2001–2010 (°C)" in html
    query = {"index": "txx", "freq": "MON", "month": 5, "year": 2012}
    got = client.get(f"/gridded/{run.pk}/map.f32", {**query, "view": "base"}).content
    assert np.array_equal(np.frombuffer(got, "<f4").reshape(NY, NX)[::-1],
                          base.astype(np.float32), equal_nan=True)  # fmt: skip
    name = client.get(f"/gridded/{run.pk}/map.csv", {**query, "view": "base"})
    assert 'filename="txx_05_base_mean_2001-2010.csv"' in name["Content-Disposition"]

    html = page(client, run, index="txx", freq="MON", month=5, year=2012, view="anomaly")
    assert "May 2012 minus the 2001–2010 mean." in html and "ramp-div-temp" in html
    assert '<span class="gmap-stepper__label" aria-live="polite">May 2012</span>' in html
    got = client.get(f"/gridded/{run.pk}/map.f32", {**query, "view": "anomaly"}).content
    anomaly = values[-1].reshape(NY, NX) - base
    assert np.allclose(np.frombuffer(got, "<f4").reshape(NY, NX)[::-1], anomaly,
                       equal_nan=True, atol=1e-5)  # fmt: skip
    # The breaks are symmetric about zero and the same for every year of the month.
    legend = [page(client, run, index="txx", freq="MON", month=5, year=y, view="anomaly")
              for y in (2003, 2012)]  # fmt: skip
    ticks = [h.split('aria-label="Bin breaks">')[1].split("</ol>")[0] for h in legend]
    assert ticks[0] == ticks[1] and "<li>0" in ticks[0]

    # The pane: the cell's base mean is the map's; the grid mean of May.
    html = page(client, run, index="txx", freq="MON", month=5, year=2012, cell="2,3")
    assert numbers.with_unit(numbers.number(base[2, 3]), "degrees_C") in html
    html = page(client, run, index="txx", freq="MON", month=5, year=2012, series="grid")
    assert "Mean over 19 cells" in html  # 20 cells, one with no value
    response = client.get(f"/gridded/{run.pk}/series.csv", {**query, "series": "grid"})
    assert 'filename="txx_05_grid_mean.csv"' in response["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0] == ["year", "txx_grid_mean"] and [r[0] for r in rows[1:]] == [
        str(y) for y in years]  # fmt: skip
    weights = cell_weights(np.broadcast_to(np.linspace(-40, -10, NY)[:, None], (NY, NX)))
    expected = grid_means(values, weights.reshape(-1))
    assert [float(r[1]) for r in rows[1:]] == pytest.approx(expected, abs=1e-6)

    # Trend: an address asking for it shows Year.
    html = page(client, run, index="txx", freq="MON", month=5, year=2012, view="trend")
    assert "The value in May 2012." in html


def test_a_monthly_file_without_trends_nc_or_latitude(client):
    """A monthly file's views need no trends.nc; the job's base period is theirs; a grid
    whose Y is not latitude has no grid mean, and says why."""
    run = run_with_trends(client, {}, trends=False, monthly=MONTHLY)
    job = run.indices_job
    job.params = {"base_start": 2003, "base_end": 2008}
    job.save()
    html = page(client, run, index="txx", freq="MON", month=3, view="base")
    assert "Mean of March in 2003–2008." in html
    assert "This run has no trends file (trends.nc)" in html

    projected = {"txx_MON_m_e_r_2001-2012.nc": monthly(lat_name="y")}
    run = run_with_trends(client, {}, trends=False, monthly=projected)
    html = page(client, run, index="txx", freq="MON", month=3, view="anomaly", series="grid")
    assert "a month has no mean over the grid" in html
    assert "data-gmap-series>Mean over the grid</a>" not in html  # Selected cell instead
    assert "minus the 2001–2010 mean." in html


def test_a_large_monthly_variable_is_read_a_month_at_a_time(client, monkeypatch):
    """A variable too large to keep whole: its month is read once (every year's step in
    one read) and kept, and the views are the same."""
    run = run_with_trends(client, ANNUAL, monthly=MONTHLY, month_trends=False)
    query = {"index": "txx", "freq": "MON", "month": 5, "year": 2012}
    small = {v: client.get(f"/gridded/{run.pk}/map.f32", {**query, "view": v}).content
             for v in ("year", "base", "anomaly")}  # fmt: skip
    for kept in (maps._cache, maps._edges, map_views._cache, map_views._edges):
        kept.clear()
    monkeypatch.setattr(maps, "CACHE_BYTES", NY * NX * 4 * YEARS * 2)  # a month, not all
    path = run.indices_job.output_dir / "txx_MON_m_e_r_2001-2012.nc"
    layer = maps.open_layer(path, path.name)
    assert maps.variable_values(path, layer) is None
    reads = []
    real = maps.netcdf.dataset

    def counted(p):
        reads.append(p)
        return real(p)

    monkeypatch.setattr(maps.netcdf, "dataset", counted)
    for view, expected in small.items():
        got = client.get(f"/gridded/{run.pk}/map.f32", {**query, "view": view}).content
        assert got == expected, view
    # Per request one read of the header (the layer); May's values read once.
    assert len([p for p in reads if p == path]) == len(small) + 1


# ---- Several threads (#295's CI failure) --------------------------------------------------------


def test_every_netcdf_read_of_the_views_holds_the_lock(client, monkeypatch):
    from climpact_web.gridded import netcdf

    run = run_with_trends(client, {"txx_ANN_m_e_r_2001-2012.nc": annual("txx")},
                          monthly={"spi_MON_m_e_r_2001-2012.nc": spi, **MONTHLY})  # fmt: skip
    monkeypatch.setattr(maps, "CACHE_BYTES", NY * NX * 4 * YEARS * 2)  # read a month at a time
    opened = []
    real = netCDF4.Dataset

    def watched(*args, **kwargs):
        opened.append(netcdf.LOCK._is_owned())
        return real(*args, **kwargs)

    monkeypatch.setattr(netCDF4, "Dataset", watched)
    for url in ("?view=trend", "?view=base", "?view=anomaly&series=grid", "map.png?view=trend",
                "map.f32?view=anomaly", "map.csv?view=base", "series.csv?series=grid",
                "map.png?view=trend&download=1", "?index=spi&freq=MON&view=trend",
                "?index=txx&freq=MON&month=5&view=base",
                "?index=txx&freq=MON&month=5&view=trend&cell=2,3",
                "map.png?index=txx&freq=MON&month=5&view=trend",
                "map.csv?index=txx&freq=MON&month=4&view=trend",
                "map.f32?index=txx&freq=MON&month=5&view=anomaly",
                "series.csv?index=txx&freq=MON&month=5&series=grid"):  # fmt: skip
        assert client.get(f"/gridded/{run.pk}/{url}").status_code == 200, url
    assert any(opened) and all(opened)

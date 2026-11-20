"""A gridded run's Map (#295, the GridMap board): the bins and colour scales, the PNG with
one pixel per cell, the map's frame (north up, west left, the cells' aspect), the bundled
outline (coastline and places), every cell drawn on large grids within a second, the cell
pane (Go to, the form without JavaScript, the stations of the browser's workspaces in the
cell)."""

import math
import struct
import time
import zlib

import netCDF4
import numpy as np
import pytest
from django.test import Client

from climpact_web.gridded import map_image, map_page, maps, outline
from climpact_web.gridded.models import GriddedRun
from climpact_web.jobs.models import Job, Status

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    settings.JOB_RETENTION_DAYS = 7
    return settings


def read_png(data: bytes) -> tuple[np.ndarray, list[tuple[int, int, int]], bytes]:
    """An indexed PNG's pixels (palette indices), palette and transparency."""
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    pos, chunks = 8, {}
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        chunks[kind] = chunks.get(kind, b"") + data[pos + 8 : pos + 8 + length]
        pos += 12 + length
    width, height, depth, colour = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    assert (depth, colour) == (8, 3)
    raw = np.frombuffer(zlib.decompress(chunks[b"IDAT"]), np.uint8).reshape(height, width + 1)
    assert not raw[:, 0].any()  # no filter on any row
    plte = chunks[b"PLTE"]
    palette = [tuple(plte[i : i + 3]) for i in range(0, len(plte), 3)]
    return raw[:, 1:], palette, chunks[b"tRNS"]


def write_index(path, name="txx", years=3, lat=(-40.0, -10.0), lon=(110.0, 155.0), ny=4,
                nx=5, values=None, monthly=False, units="degrees_C"):  # fmt: skip
    steps = years * (12 if monthly else 1)
    with netCDF4.Dataset(path, "w") as nc:
        nc.createDimension("time", steps)
        nc.createDimension("lat", ny)
        nc.createDimension("lon", nx)
        t = nc.createVariable("time", "f8", ("time",))
        t.units, t.calendar = "days since 2001-01-01", "standard"
        t[:] = (np.arange(steps) * (30.4 if monthly else 365.25)) + 15
        nc.createVariable("lat", "f8", ("lat",))[:] = np.linspace(*lat, ny)
        nc.createVariable("lon", "f8", ("lon",))[:] = np.linspace(*lon, nx)
        # Chunked as the core writes them: each cell's whole series in one chunk.
        chunks = (steps, min(ny, 100), min(nx, 100))
        v = nc.createVariable(name, "f4", ("time", "lat", "lon"), fill_value=np.float32(1e20),
                              zlib=True, chunksizes=chunks)  # fmt: skip
        v.units, v.long_name = units, name
        if values is None:
            values = np.arange(steps * ny * nx, dtype=np.float32).reshape(steps, ny, nx)
        v[:] = values


def finished_run(client, files: dict) -> GriddedRun:
    """A run of this browser whose indices job wrote ``files`` (name -> writer)."""
    response = client.post("/gridded/sample")
    run = GriddedRun.objects.get(pk=response["Location"].split("/")[2])
    job = Job.objects.create(kind="gridded-indices", owner=run.owner, status=Status.SUCCEEDED,
                             step=1, total=1, result={"files": list(files)})  # fmt: skip
    job.output_dir.mkdir(parents=True)
    for name, write in files.items():
        write(job.output_dir / name)
    run.indices_job = job
    run.options = {**run.options, "base_start": 2001, "base_end": 2002}
    run.save()
    return run


# ---- The bins and the scales ------------------------------------------------------------------


def test_nice_edges_and_bins():
    assert maps.nice_edges(0.3, 7.6) == [0, 1, 2, 3, 4, 5, 6, 7, 8]
    assert maps.nice_edges(18.2, 45.1) == [15, 20, 25, 30, 35, 40, 45, 50, 55]
    edges = maps.nice_edges(23.6, 44)
    assert edges[0] <= 23.6 and edges[-1] >= 44 and len(edges) == 9
    assert len(set(np.diff(edges).round(9))) == 1  # one step
    bins = maps.classify(np.array([[-5.0, 0.5], [np.nan, 99.0]]), [0, 1, 2, 3, 4, 5, 6, 7, 8])
    assert bins.tolist() == [[0, 0], [255, 7]]  # beyond the ends: the end bins
    assert maps.classify(np.array([-2.5, -1.2, 0.0, 1.7, 2.4]), list(maps.SPI_EDGES)).tolist() == [
        0, 2, 3, 5, 6,
    ]  # fmt: skip


def test_legend_ticks_keep_the_step():
    assert maps.legend_ticks([27.5, 30, 32.5]) == ["27.5", "30.0", "32.5"]
    assert maps.legend_ticks([0, 10, 20]) == ["0", "10", "20"]
    assert maps.legend_ticks([-0.5, 0, 0.5]) == ["−0.5", "0.0", "0.5"]


@pytest.mark.parametrize(
    "short, units, theme, kind",
    [
        ("txx", "degrees_C", "heat", "temp"),
        ("hwm_tx90", "degC", "heat", "temp"),  # heatwave files write degC
        ("tnn", "degrees_C", "cold", "temp"),
        ("su", "days", "heat", "warm"),
        ("fd", "days", "cold", "cool"),
        ("prcptot", "mm", "rain", "wet"),
        ("cdd", "days", "drought", "dry"),
        ("spi", "unitless", "drought", "spi"),
        ("gsl", "days", "other", "warm"),
        ("hddheatn", "degree-days", "other", "cool"),
    ],
)
def test_the_scale_follows_the_kind_of_index(short, units, theme, kind):
    assert maps.kind_of(short, units, theme) == kind


def test_palettes_are_the_tokens():
    from climpact_web.core import tokens

    palette = tokens.chart_palette()
    for theme in ("light", "dark"):
        assert maps.palette("warm", theme) == palette[theme]["map_sequential"]["warm"]
        assert len(maps.palette("temp", theme)) == 8
        # SPI: the diverging scale reversed, dry (low) red and wet blue.
        assert maps.palette("spi", theme) == palette[theme]["diverging"][::-1]


def test_raster_png_has_a_pixel_per_cell():
    bins = np.array([[0, 1, 255], [7, 2, 3]], np.uint8)
    colours = maps.palette("temp")
    pixels, plte, alpha = read_png(map_image.raster_png(bins, colours))
    assert pixels.shape == (2, 3)
    assert pixels[0, 2] == len(colours) and alpha[len(colours)] == 0  # no value: transparent
    assert alpha[: len(colours)] == b"\xff" * len(colours)
    assert plte[pixels[1, 0]] == tuple(bytes.fromhex(colours[7][1:]))


# ---- The frame and the outline ----------------------------------------------------------------


def layer(lat, lon, y_dim="lat", x_dim="lon") -> maps.Layer:
    return maps.Layer(file="f.nc", variable="txx", variables=[], long_name="", units="",
                      times=["2001"], scales=[], lat=list(lat), lon=list(lon), y_dim=y_dim,
                      x_dim=x_dim, years=[2001])  # fmt: skip


def test_frame_draws_north_up_west_left_with_the_cosine():
    f = maps.frame(layer([-40.0, -30.0, -20.0], [150.0, 145.0, 140.0, 135.0]))
    assert f.rows == [2, 1, 0] and f.cols == [3, 2, 1, 0]
    rect = f.cell_rect(2, 3)
    assert (rect["x"], rect["y"], rect["w"]) == (maps.LEFT, maps.TOP, 180.0)
    assert rect["h"] == pytest.approx(f.cell_h, abs=0.01)
    # 4 x 5° by 3 x 10°, at a mean latitude of 30° S.
    aspect = 30 / (20 * math.cos(math.radians(30)))
    assert f.plot_h == pytest.approx(maps.PLOT_W * aspect, abs=0.01)
    assert [t["text"] for t in f.y_ticks] == [f"{v}°\xa0S" for v in (45, 40, 35, 30, 25, 20, 15)]
    values = np.arange(12.0).reshape(3, 4)
    assert maps.display_order(values, f)[0, 0] == values[2, 3]


def test_frame_axes_and_outline_for_a_global_grid_in_0_to_360():
    f = maps.frame(layer(np.linspace(-88.75, 88.75, 72), np.arange(0, 360, 2.5)))
    assert [t["text"] for t in f.x_ticks] == ["0°\xa0E", "90°\xa0E", "180°\xa0W", "90°\xa0W"]
    assert f.coast.startswith("M") and len(f.coast) < 200_000
    assert 3 <= len(f.places) <= 5


def test_a_rotated_grid_has_no_outline():
    f = maps.frame(layer(range(10), range(12), "rlat", "rlon"))
    assert not f.geographic and f.coast == "" and f.places == []


def test_outline_coastline_and_places():
    sydney = outline.Box(west=150.0, east=152.0, south=-35.0, north=-33.0)
    lines = outline.coastline(sydney)
    assert lines and all(len(line) >= 2 for line in lines)
    points = np.concatenate(lines)
    assert ((points[:, 0] > 149.9) & (points[:, 0] < 152.1)).mean() > 0.9
    names = [p.name for p in outline.places(outline.Box(140.5, 154.0, -40.0, -28.0))]
    assert names[0] == "Sydney" and "Melbourne" in names and len(names) <= 5
    # The same coast found a turn east, in a grid of 0-360° longitudes.
    shifted = outline.coastline(outline.Box(west=-210.0, east=-208.0, south=-35.0, north=-33.0))
    assert len(shifted) == len(lines)


def test_nearest_cell_and_go_to():
    grid = layer([-30.0, -31.0, -32.0], [350.0, 351.0, 352.0])
    assert maps.nearest_cell(grid, -31.2, 351.4) == (1, 1)
    assert maps.nearest_cell(grid, -31.2, -8.6) == (1, 1)  # 351.4° E is 8.6° W
    assert maps.nearest_cell(grid, -40.0, 351.0) is None
    assert map_page.parse_goto("−33.86, 151.21") == (-33.86, 151.21)
    assert map_page.parse_goto("33.86 S 151.21 E") == (-33.86, 151.21)
    assert map_page.parse_goto("33,86; 151,21") == (33.86, 151.21)
    assert map_page.parse_goto("Sydney") is None and map_page.parse_goto("95, 10") is None


# ---- The page --------------------------------------------------------------------------------


def test_go_to_and_the_form_without_javascript(client):
    run = finished_run(client, {"txx_ANN_m_e_r_2001-2003.nc": write_index})
    url = f"/gridded/{run.pk}/"
    html = client.get(url, {"cell_y": 1, "cell_x": 3}).content.decode()
    assert 'name="cell_y"' in html and '<option value="1" selected>' in html
    assert '<option value="3" selected>' in html
    assert "Cell 2, 4 of 4 × 5" in html
    html = client.get(url, {"goto": "-20, 141"}).content.decode()
    assert "Cell 3, 4 of 4 × 5" in html  # 20° S 143.75° E
    html = client.get(url, {"goto": "-60, 141"}).content.decode()
    assert "That point is outside the grid." in html and 'aria-invalid="true"' in html
    html = client.get(url, {"q": "hot"}).content.decode()
    assert "gmap-rail__item" in html and 'value="hot"' in html


def test_the_station_box_only_for_a_station_in_the_cell(client):
    from climpact_web.stations.models import Station

    run = finished_run(client, {"txx_ANN_m_e_r_2001-2003.nc": write_index})
    Station.objects.create(owner=run.owner, station_name="Alice Springs", file_name="a.txt",
                           latitude=-20.1, longitude=132.4)  # fmt: skip
    Station.objects.create(owner="someone else", station_name="Not mine", file_name="b.txt",
                           latitude=-20.1, longitude=132.4)  # fmt: skip
    # The cell at 20° S 132.5° E (the file's row 2 and column 2) holds the station.
    html = client.get(f"/gridded/{run.pk}/", {"cell": "2,2"}).content.decode()
    assert "<strong>Alice Springs</strong>" in html and "Not mine" not in html
    assert 'Open its <span class="font-mono">TXx</span>' in html
    assert "/indices/txx" in html
    html = client.get(f"/gridded/{run.pk}/", {"cell": "0,0"}).content.decode()
    assert "A station in your workspaces" not in html


def test_monthly_and_heatwave_entries(client):
    def heatwaves(path):
        write_index(path, "hwn_tx90", units="heatwaves")
        with netCDF4.Dataset(path, "a") as nc:
            v = nc.createVariable("hwf_tx90", "f4", ("time", "lat", "lon"))
            v.units, v.long_name = "days", "Heatwave frequency, see user guide for definition."
            v[:] = 3.0

    run = finished_run(client, {
        "txx_ANN_m_e_r_2001-2003.nc": write_index,
        "txx_MON_m_e_r_2001-2003.nc": lambda p: write_index(p, monthly=True),
        "hw_ANN_m_e_r_2001-2003.nc": heatwaves,
    })  # fmt: skip
    html = client.get(f"/gridded/{run.pk}/").content.decode()
    assert '<span class="gmap-rail__code">TX90-HWF</span>' in html
    assert '<span class="gmap-rail__code">TX90-HWN</span>' in html and ">ANN MON<" in html
    html = client.get(f"/gridded/{run.pk}/", {"index": "txx", "freq": "MON"}).content.decode()
    assert '<span class="gmap-stepper__label" aria-live="polite">Dec 2003</span>' in html
    assert "</span>, December, 2001–2003" in html
    html = client.get(f"/gridded/{run.pk}/", {"index": "hwf_tx90"}).content.decode()
    assert "Heatwave frequency." in html and "ramp-warm" in html
    assert 'segmented__item--off" aria-disabled="true"' in html  # no monthly file


@pytest.mark.parametrize("ny, nx", [(145, 192), (700, 900)])
def test_every_cell_drawn_within_a_second(client, ny, nx):
    """A global 145 x 192 grid and a 700 x 900 one: the page, its PNG (one pixel a cell,
    every cell) and the values each within a second, the first visit included."""
    rng = np.random.default_rng(0)
    values = (20 + 20 * rng.random((5, ny, nx))).astype(np.float32)
    values[:, 0, 0] = np.nan

    def write(path):
        write_index(path, years=5, lat=(-60.0, 60.0), lon=(0.0, 358.0), ny=ny, nx=nx,
                    values=values)  # fmt: skip

    run = finished_run(client, {f"txx_ANN_m_e_r_{ny}_2001-2005.nc": write})
    for url in ("", "map.png?index=txx", "map.f32?index=txx"):
        start = time.perf_counter()
        response = client.get(f"/gridded/{run.pk}/{url}")
        assert response.status_code == 200
        assert time.perf_counter() - start < 1.0, url
        if url.startswith("map.png"):
            pixels, _plte, _alpha = read_png(response.content)
            assert pixels.shape == (ny, nx)
            assert pixels[-1, 0] == len(maps.palette("temp"))  # row 0 of the file is south
            assert (pixels != 8).sum() == ny * nx - 1
        if url.startswith("map.f32"):
            assert len(response.content) == ny * nx * 4


def test_other_sessions_get_404_for_the_map(client):
    run = finished_run(client, {"txx_ANN_m_e_r_2001-2003.nc": write_index})
    other = Client()
    for url in ("", "map.png", "map.f32", "map.csv", "series.csv"):
        assert other.get(f"/gridded/{run.pk}/{url}").status_code == 404, url


def test_a_day_of_year_file_and_a_year_with_no_value(client):
    def tx95t(path):
        write_index(path, "tx95t")
        with netCDF4.Dataset(path, "a") as nc:  # days of the year, as the core writes them
            nc["time"][:] = [1, 2, 3]

    def empty_last_year(path):
        values = np.arange(60, dtype=np.float32).reshape(3, 4, 5)
        values[2] = np.nan
        write_index(path, "su", values=values, units="days")

    run = finished_run(client, {
        "tx95t_DAY_m_e_r_2001-2003.nc": tx95t,
        "su_ANN_m_e_r_2001-2003.nc": empty_last_year,
    })  # fmt: skip
    html = client.get(f"/gridded/{run.pk}/", {"index": "tx95t", "freq": "DAY"}).content.decode()
    assert "The threshold on day 3." in html and "</span>, by day of the year" in html
    html = client.get(f"/gridded/{run.pk}/", {"index": "su"}).content.decode()
    assert '<span class="gmap-stepper__label" aria-live="polite">2002</span>' in html
    html = client.get(f"/gridded/{run.pk}/", {"index": "su", "year": 2003}).content.decode()
    assert "No cell has a value in 2003." in html and "ramp-warm" in html


# ---- Several threads at once (#295's CI failure) ------------------------------------------------


def test_every_netcdf_read_of_the_map_holds_the_lock(client, monkeypatch):
    """HDF5 in the netCDF4 wheels is not thread-safe, and the server answers on several
    threads: every file the Map's requests open is opened holding the one lock."""
    from climpact_web.gridded import netcdf

    run = finished_run(client, {
        "txx_ANN_m_e_r_2001-2003.nc": write_index,
        "su_ANN_m_e_r_2001-2003.nc": lambda p: write_index(p, "su", units="days"),
    })  # fmt: skip
    maps._cache.clear()
    opened = []
    real = netCDF4.Dataset

    def watched(*args, **kwargs):
        opened.append(netcdf.LOCK._is_owned())
        return real(*args, **kwargs)

    monkeypatch.setattr(netCDF4, "Dataset", watched)
    for url in ("", "?index=su", "map.png?index=su", "map.f32", "map.csv", "series.csv",
                "map.png?download=1", "files/"):  # fmt: skip
        assert client.get(f"/gridded/{run.pk}/{url}").status_code == 200, url
    assert len(opened) >= 8 and all(opened)


def test_map_reads_in_parallel(tmp_path):
    """What the Map's requests read (a layer, a year's values, a cell's series, the
    breaks, the run's cell count, a file's description), from eight threads at once with
    cold caches, as the server's threads ask for the page, its PNGs, values and CSVs
    together: every read succeeds and gives the file's values. (Without the lock this
    failed about one run in eight with "NetCDF: Not a valid ID".)"""
    from concurrent.futures import ThreadPoolExecutor

    from climpact_web.gridded import inspection, runs

    paths = []
    for name in ("txx", "tnn", "txm"):
        path = tmp_path / f"{name}_ANN_m_e_r_2001-2003.nc"
        write_index(path, name, ny=40, nx=50)
        paths.append(path)
    expected = np.arange(3 * 40 * 50, dtype=np.float32).reshape(3, 40, 50)

    def read(i: int) -> bool:
        path = paths[i % 3]
        layer = maps.open_layer(path, path.name)
        values = maps.grid_values(path, layer, i % 3)
        series = maps.cell_series(path, layer, i % 40, i % 50)
        edges = maps.edges_for(path, layer, "temp")
        cells = runs.count_cells(path)
        info = inspection.inspect_file(path)
        variables = map_page._variables(path)
        return (
            np.array_equal(values, expected[i % 3])
            and np.array_equal(series, expected[:, i % 40, i % 50])
            and edges is not None and cells == 2000 and info.ny == 40
            and variables[0][0] == layer.variable
        )  # fmt: skip

    for _ in range(5):
        maps._cache.clear()
        maps._edges.clear()
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert all(pool.map(read, range(48)))

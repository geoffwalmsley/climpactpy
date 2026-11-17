"""Chart data views (#75): JSON for the interactive charts, cached by the browser.

Each response carries an ``ETag`` and ``Last-Modified`` computed from the files it is
built from (their modification times and sizes), the language and the schema version, with
``Cache-Control: private, no-cache``: the browser keeps the data and asks again with
``If-None-Match``, and an unchanged file answers ``304 Not Modified`` without reading
anything. Built payloads are also kept in a small in-process cache keyed by the ETag. The
responses are gzipped when the browser accepts it (the daily series of 80 years is about
420 KB, 100 KB gzipped).

Access is as for the pages: an analysis or job of another session is 404.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse
from django.urls import reverse
from django.utils.cache import get_conditional_response
from django.utils.http import http_date
from django.utils.translation import get_language
from django.views.decorators.gzip import gzip_page
from django.views.decorators.http import require_safe

import climpact_web
from climpact_web.charts import data
from climpact_web.jobs.models import Status
from climpact_web.jobs.views import get_job
from climpact_web.stations.views import get_station

SERIES_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SAMPLE_OUTPUTS = Path(__file__).resolve().parent / "sample_outputs"
_CACHE_SIZE = 24
_cache: OrderedDict[str, bytes] = OrderedDict()
_lock = threading.Lock()


def _cached(etag: str, build: Callable[[], dict]) -> bytes:
    with _lock:
        if etag in _cache:
            _cache.move_to_end(etag)
            return _cache[etag]
    body = json.dumps(build(), separators=(",", ":"), ensure_ascii=False).encode()
    with _lock:
        _cache[etag] = body
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return body


def json_response(request, key: tuple, files: list[Path], build: Callable[[], dict | None]):
    """The JSON of ``build()``, with validators from ``files`` and ``key``; 404 when a
    file is missing or ``build`` returns None."""
    stats = []
    for path in files:
        try:
            st = path.stat()
        except OSError:
            raise Http404 from None
        stats.append((str(path), st.st_mtime_ns, st.st_size))
    parts = (key, stats, get_language(), data.SCHEMA_VERSION, climpact_web.__version__)
    etag = '"' + hashlib.sha256(repr(parts).encode()).hexdigest()[:32] + '"'
    last_modified = int(max(s[1] for s in stats) // 1_000_000_000) if stats else None
    response = get_conditional_response(request, etag=etag, last_modified=last_modified)
    if response is None:
        payload = {}

        def build_or_404():
            result = build()
            if result is None:
                raise Http404
            payload.update(result)
            return result

        response = HttpResponse(_cached(etag, build_or_404), content_type="application/json")
    response["ETag"] = etag
    if last_modified is not None:
        response["Last-Modified"] = http_date(last_modified)
    response["Cache-Control"] = "private, no-cache"
    return response


# ---- daily series of a station analysis ----------------------------------------------


def analysis_qc_params(analysis):
    """The QC thresholds the flags are found with: those of the analysis's latest quality
    check (#77), so the chart flags what its tables list, else the thresholds entered (R's
    defaults until changed)."""
    from climpact_web.jobs.runners import qc_params

    job = analysis.qc_job
    return qc_params(job.params.get("qc") if job is not None else analysis.workspace.qc_params)


@gzip_page
@require_safe
def station_daily(request, analysis_id):
    """The daily series of a station analysis, with the values the QC checks flag;
    ``?variable=`` (``tmax``, ``tmin``, ``dtr``, ``prcp``) gives one variable alone, and
    ``?flags=0`` leaves the flags out (the Load step, before the quality checks: #173)."""
    analysis = get_station(request, analysis_id)
    variable = request.GET.get("variable") or None
    if variable is not None and variable not in data.DAILY_VARIABLES:
        raise Http404
    flags = request.GET.get("flags") != "0"
    params = analysis_qc_params(analysis)
    title = analysis.station_name or analysis.file_name

    def build():
        payload = data.daily_payload(
            analysis.station_file, params, title=title, variable=variable, flags=flags
        )
        payload["csv"] = analysis.url("series")
        if variable:
            payload["name"] = f"{title}_{variable}"
        return payload

    key = ("daily", str(analysis.pk), repr(params), title, variable, flags)
    return json_response(request, key, [analysis.station_file], build)


# ---- index series of a finished job --------------------------------------------------


def job_stations(job) -> dict[str, tuple[Path, object]]:
    """Each station of a finished job with index tables: its name -> (the folder holding
    ``<station>/``, its IndexParams)."""
    from climpact.batch import read_batch_metadata
    from climpact_web.jobs.runners import custom_index, index_params

    result, output = job.result or {}, job.output_dir
    if job.kind == "station" and result.get("station"):
        return {result["station"]: (output, index_params(job.params.get("params")))}
    if job.kind == "batch":
        folder = output / result.get("folder", "")
        ok = {s["name"] for s in result.get("stations", []) if s.get("ok")}
        custom = custom_index(job.params.get("custom"))
        try:
            listed = read_batch_metadata(job.input_dir / job.params["metadata_file"])
        except (KeyError, OSError, ValueError):
            return {}
        from dataclasses import replace

        return {s.name: (folder, replace(s.params, custom=custom)) for s in listed if s.name in ok}
    return {}


def index_source(request, job_id) -> tuple[object, data.IndexSource]:
    job = get_job(request, job_id)
    if job.status != Status.SUCCEEDED:
        raise Http404
    stations = job_stations(job)
    name = request.GET.get("station") or (next(iter(stations)) if len(stations) == 1 else "")
    if name not in stations:
        raise Http404
    folder, params = stations[name]
    return job, data.IndexSource(folder, name, params)


def _file_url(job, source: data.IndexSource, series: str) -> str:
    path = source.table_path(data.table_name(series))
    relative = path.relative_to(job.output_dir)
    return reverse("jobs:file", args=[job.pk, relative.as_posix()])


@gzip_page
@require_safe
def job_series_list(request, job_id):
    """Every plotted index series of a station in a finished job, in R's order, each with
    the URL of its data and of its CSV file."""
    job, source = index_source(request, job_id)
    station = f"?station={source.station}"

    def build():
        series = data.series_list(source)
        for item in series:
            item["url"] = reverse("charts:job_series", args=[job.pk, item["name"]]) + station
            item["csv"] = _file_url(job, source, item["name"])
        return {"kind": "series-list", "version": data.SCHEMA_VERSION, "series": series}

    files = [source.indices_dir, *sorted(source.indices_dir.glob("*.csv"))]
    key = ("list", str(job.pk), source.station, repr(source.params))
    return json_response(request, key, files, build)


@gzip_page
@require_safe
def job_series(request, job_id, name):
    """One index series of a station in a finished job, with its trend."""
    if not SERIES_NAME.match(name):
        raise Http404
    job, source = index_source(request, job_id)

    def build():
        payload = data.index_payload(source, name)
        if payload is not None:
            payload["csv"] = _file_url(job, source, name)
        return payload

    key = ("index", str(job.pk), source.station, name, repr(source.params))
    return json_response(request, key, [source.table_path(data.table_name(name))], build)


# ---- examples for the pattern library ------------------------------------------------


def _require_pattern_library():
    if not settings.PATTERN_LIBRARY:
        raise Http404


@gzip_page
@require_safe
def sample_daily(request):
    """The pattern library's daily chart: the bundled Sydney sample."""
    from climpact_web.stations.views import SAMPLE_DIR, SAMPLE_NAME, sample_bytes

    _require_pattern_library()
    gz = SAMPLE_DIR / f"{SAMPLE_NAME}.gz"
    target = Path(settings.MEDIA_ROOT) / "charts-sample" / SAMPLE_NAME
    if not target.is_file() or target.stat().st_mtime < gz.stat().st_mtime:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(sample_bytes())

    def build():
        payload = data.daily_payload(target, title="Sydney Observatory Hill")
        payload["csv"] = reverse("stations:sample_file")
        return payload

    return json_response(request, ("sample-daily",), [gz], build)


def sample_source():
    from climpact.config import IndexParams

    return data.IndexSource(SAMPLE_OUTPUTS, "sydney", IndexParams())


@gzip_page
@require_safe
def sample_series(request, name):
    """The pattern library's index charts: a few tables of the Sydney sample's run."""
    _require_pattern_library()
    if not SERIES_NAME.match(name):
        raise Http404
    source = sample_source()
    path = source.table_path(data.table_name(name))
    return json_response(
        request, ("sample", name), [path], lambda: data.index_payload(source, name)
    )

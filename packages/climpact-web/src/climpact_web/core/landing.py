"""What the landing page shows (#242, the Landing board): a preview of real output and the
facts.

The preview is the Sydney sample's own output (``charts/sample_outputs/sydney``, the files
Climpact writes for it, text-identical to Climpact for R's): TXx Hottest day drawn as the
Indices' detail pane draws a series (:func:`climpact_web.stations.index_detail.chart`:
axes, the base period as a band, Sen's slope dashed), and four more indices as rows of
the Indices table (slope per decade, its 95% interval, significant or not), all from the
core's trend fit, as a station's own pages show them.

The facts are the R parity suite's (``.parity-summary.txt`` of the test run; TECHNICAL.md,
"Parity testing"). Change them here when the reference runs change:
``tests/test_landing.py`` checks the counts against ``reference/stations.csv`` when the
repository is there.
"""

from __future__ import annotations

from functools import lru_cache

from django.utils.translation import get_language

from climpact_web.core import numbers

# The reference runs of the parity suite (reference/stations.csv): 14 stations, from
# Yakutsk to Darwin, and two test cases, the Sydney file at latitude 0 (``lat0``) and a
# synthetic file made to fail the quality checks (``qc_stress``).
REFERENCE_STATIONS = 14
REFERENCE_TEST_CASES = 2
REFERENCE_RUNS = REFERENCE_STATIONS + REFERENCE_TEST_CASES
# Every CSV file written for those runs (indices, trends, thresholds, quality checks) is
# text-identical to Climpact for R's: 1,791 of 1,791 in the parity summary of #242.
REFERENCE_FILES = 1791
R_VERSION = "3.4.3"
# Indices calculated for a station with the default settings, each with a trend: the
# Indices' "of 80".
INDEX_COUNT = 80

PREVIEW_STATION = "Sydney Observatory Hill"
PREVIEW_FOLDER = "sydney"
PREVIEW_YEARS = (1936, 2015)
PREVIEW_BASE = (1971, 2000)
PREVIEW_CHART = "txx_ANN"
PREVIEW_ROWS = ("su_ANN", "tr_ANN", "tn10p_ANN", "prcptot_ANN")


# How it works: the miniatures' values, the reference runs' own (illustrations, hidden
# from screen readers). Add stations: three reference files and their coordinates.
MINI_FILES = (
    ("sydney_observatory_hill.txt", "−33.86", "151.21"),
    ("perth_airport.txt", "−31.93", "115.98"),
    ("darwin.txt", "−12.42", "130.89"),
)
# Quality: the qc_stress file's verdict and three of its findings (date, variable).
MINI_QC_DATES = (("1967-02-02", "TN"), ("1963-12-04", "PR"), ("1980-01-20", ""))
# The trend grid: Sen's slope per decade, and whether its 95% interval excludes zero.
MINI_GRID_CODES = ("TXx", "TN90p", "SU", "TR")
MINI_GRID = (
    ("Sydney", (("+0.03", False), ("+1.31", True), ("+5.15", True), ("+4.65", True))),
    ("Perth", (("+0.15", False), ("+0.79", True), ("+6.00", True), ("+0.77", False))),
    ("Darwin", (("+0.12", False), ("+0.40", False), ("0.00", False), ("−0.80", False))),
)


def miniatures() -> dict:
    return {
        "files": MINI_FILES,
        "qc_dates": MINI_QC_DATES,
        "grid_codes": MINI_GRID_CODES,
        "grid": MINI_GRID,
        "folders": "indices/ · trend/ · plots/ · report.pdf",
    }


def _card(plot):
    from climpact_web.stations import results

    card = results._new_card(results.card_key(plot.name), 0)
    card.units = results._units(plot)
    card.trend = results.trend_summary(plot)
    return card


def _row(plot) -> dict:
    card = _card(plot)
    trend = card.trend or {}
    return {
        "code": card.code,
        "name": card.title,
        "slope": trend.get("slope_text", "–"),
        "units": numbers.trend_units(card.units),
        "pp": numbers.trend_units(card.units) != numbers.unit_label(card.units),
        "interval": trend.get("interval_text", ""),
        "significant": bool(trend.get("significant")),
    }


@lru_cache(maxsize=8)
def _preview(language: str | None) -> dict | None:
    from climpact.config import IndexParams
    from climpact_web.charts import data
    from climpact_web.charts.views import SAMPLE_OUTPUTS
    from climpact_web.stations import index_detail

    source = data.IndexSource(SAMPLE_OUTPUTS, PREVIEW_FOLDER, IndexParams())
    plots = {}
    for name in (PREVIEW_CHART, *PREVIEW_ROWS):
        found = data.index_plots(source, only=name)
        if not found:
            return None
        plots[name] = found[0]
    main = plots[PREVIEW_CHART]
    card = _card(main)
    trend = card.trend or {}
    return {
        "station": PREVIEW_STATION,
        "years": f"{PREVIEW_YEARS[0]}–{PREVIEW_YEARS[1]}",
        "code": card.code,
        "name": card.title,
        "slope": trend.get("per_decade_text", ""),
        "interval": trend.get("interval_text", ""),
        "significant": bool(trend.get("significant")),
        "chart": index_detail.chart(main, PREVIEW_BASE),
        "summary": index_detail.summary(card, main),
        "rows": [_row(plots[name]) for name in PREVIEW_ROWS],
    }


def preview() -> dict | None:
    """The hero's preview, or None when the sample's output is not there."""
    return _preview(get_language())


def facts() -> dict:
    return {
        "indices": INDEX_COUNT,
        "runs": REFERENCE_RUNS,
        "stations": REFERENCE_STATIONS,
        "test_cases": REFERENCE_TEST_CASES,
        "files": numbers.grouped(REFERENCE_FILES),
        "r_version": R_VERSION,
    }

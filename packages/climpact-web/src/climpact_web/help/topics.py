"""Contextual help topics (#81): short explanations shown in place, keyed by a stable id.

Screens show a topic with ``{% load help %}{% help_topic "station.base_period" %}`` (or
``help="..."`` on ``components/field.html``). A topic has a title, one or two plain
sentences, and the guide section that says more. The ids are the contract with the
screens: the ones the later screens use are listed in TECHNICAL.md ("Help"), and a test
checks that every id used in a template exists and every guide link resolves.

Id families:

- ``station.*``: single-station step 1 fields; ``batch.*``: batch page fields;
- ``qc.*``: one per quality-control check or plot (``qc.<file name>``, as
  ``climpact.products.qc.QC_REPORTS``); ``qcparam.*``: the QC thresholds (``QCParams``
  field names);
- ``param.*``: index parameters (``IndexParams`` field names, plus ``param.custom`` and
  ``param.plot_title``);
- ``index.<short name>``: one per index of the core's ``climate.indices.csv``, generated
  (``index_topic_for_output`` maps an output name such as ``rx3day_ANN`` to its topic);
- ``trend.*``, ``results.*``, ``sector.*``, ``gridded.*``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from climpact_web.help.indices import UNITS, catalogue, index_for_output


@dataclass(frozen=True)
class Topic:
    id: str
    title: str | Promise
    text: str | Promise
    guide: str | None = None  # guide slug
    anchor: str = ""  # heading id in that guide
    kind: str = ""  # the id's family, for the topic list
    # What the in-place link says, when the title would repeat or contradict the heading
    # it sits under (#115): a question, as "Why the latitude matters". The title stays the
    # topic's name in the list of topics.
    question: str | Promise = ""

    @property
    def url(self) -> str:
        """The guide section with more, or the topic's entry in the list of topics."""
        if self.guide:
            url = reverse("help:guide", args=[self.guide])
            return f"{url}#{self.anchor}" if self.anchor else url
        return f"{reverse('help:topics')}#{self.anchor_id}"

    @property
    def anchor_id(self) -> str:
        return "topic-" + self.id.replace(".", "-").replace("_", "-").lower()


def T(id, title, text, guide=None, anchor="", question=""):  # noqa: N802 (a table of constructors)
    return Topic(id, title, text, guide, anchor, kind=id.split(".", 1)[0], question=question)


KINDS = {
    "station": _("Station details"),
    "batch": _("Batch processing"),
    "qc": _("Quality checks"),
    "qcparam": _("Quality check settings"),
    "param": _("Index settings"),
    "index": _("Indices"),
    "trend": _("Trends"),
    "results": _("Results files"),
    "sector": _("Sector data"),
    "gridded": _("Gridded data"),
}

HAND_WRITTEN = (
    # ---- Single station, step 1 -------------------------------------------------------
    T(
        "station.file",
        _("The station file"),
        _(
            "A text file with one row per day and six columns: year, month, day, "
            "precipitation (mm), maximum and minimum temperature (°C). Write missing "
            "values as -99.9."
        ),
        "station-file",
    ),
    T(
        "station.name",
        _("What the name is used for"),
        _(
            "Used in the names of the result files and on the plots. Letters, digits, "
            "spaces and . ( ) - _ only."
        ),
        "station-file",
        "station-details",
    ),
    T(
        "station.latitude",
        _("Why the latitude matters"),
        _(
            "The latitude decides the hemisphere, and so the season used for the growing "
            "season length and the Tx90 and Tn90 heatwaves. Latitude 0 counts as the "
            "Southern Hemisphere, as in Climpact for R."
        ),
        "station-file",
        "station-details",
    ),
    T(
        "station.longitude",
        _("Does the longitude matter?"),
        _("Recorded with the results. It does not change any index. Negative west of Greenwich."),
        "station-file",
        "station-details",
    ),
    T(
        "station.base_period",
        _("What is the base period?"),
        _(
            "The years the percentile thresholds are calculated from, for indices such as "
            "TX90p, WSDI and R95p. Choose 30 years with good data if you can: 1961-1990 "
            "for climate change studies, 1991-2020 for monitoring."
        ),
        "base-period",
    ),
    # ---- Batch ------------------------------------------------------------------------
    T(
        "batch.metadata_file",
        _("The batch metadata file"),
        _(
            "One line per station with its file name, latitude, longitude and index "
            "settings, in 12 columns. Start from the sample metadata file."
        ),
        "batch",
        "the-metadata-file",
    ),
    T(
        "batch.station_files",
        _("Station files for a batch"),
        _(
            "Each file named in the metadata file, in the six-column station format. "
            "Names must match exactly, including capitals and the extension."
        ),
        "batch",
        "station-files",
    ),
    T(
        "batch.base_period",
        _("One base period for every station"),
        _(
            "All stations in a batch use the same base period, so choose years that every "
            "station has data for. A station with less than a year of data in it gets no "
            "percentile indices."
        ),
        "base-period",
        "batches",
    ),
    T(
        "batch.workers",
        _("Stations at the same time"),
        _(
            "How many stations are calculated in parallel, one per processor core. Leave "
            "a core free if you want to keep using the computer."
        ),
        "batch",
        "options",
    ),
    T(
        "batch.plots",
        _("Plots in a batch"),
        _(
            "Drawing a plot for every index takes about two thirds of the time. The index "
            "tables and trend file are written either way."
        ),
        "batch",
        "options",
    ),
    # ---- Quality checks ---------------------------------------------------------------
    T(
        "qc.outliers",
        _("Outliers"),
        _(
            "Values far from the usual range for their calendar month: more than 3 "
            "interquartile ranges beyond the box for temperatures, and 5 for precipitation "
            "(days with rain only)."
        ),
        "quality-control",
        "outliers",
        question=_("What counts as an outlier?"),
    ),
    T(
        "qc.tmaxmin",
        _("Minimum at or above maximum"),
        _(
            "Days where the minimum temperature is equal to or higher than the maximum. "
            "Usually a typing error or swapped columns."
        ),
        "quality-control",
        "maximum-below-minimum",
        question=_("Why would the minimum reach the maximum?"),
    ),
    T(
        "qc.toolarge",
        _("Values too large"),
        _(
            "Precipitation above 200 mm or below 0, and temperatures above 50 °C or below "
            "-50 °C. They may be real, but check them."
        ),
        "quality-control",
        "values-too-large",
        question=_("What counts as too large?"),
    ),
    T(
        "qc.duplicates",
        _("Repeated dates"),
        _(
            "Dates that appear more than once in the file. The indices use the last row "
            "of a repeated date; remove the others."
        ),
        "quality-control",
        "repeated-dates",
        question=_("Which of the repeated rows is used?"),
    ),
    T(
        "qc.tx_jumps",
        _("Jumps in maximum temperature"),
        _("Days where the maximum temperature changed by 20 °C or more from the day before."),
        "quality-control",
        "jumps",
        question=_("What counts as a jump?"),
    ),
    T(
        "qc.tn_jumps",
        _("Jumps in minimum temperature"),
        _("Days where the minimum temperature changed by 20 °C or more from the day before."),
        "quality-control",
        "jumps",
        question=_("What counts as a jump?"),
    ),
    T(
        "qc.tx_flatline",
        _("Repeated maximum temperatures"),
        _(
            "The same maximum temperature on many days in a row (more than 5 by default), "
            "which often means a value was copied forward."
        ),
        "quality-control",
        "repeated-values",
        question=_("How many repeats are flagged?"),
    ),
    T(
        "qc.tn_flatline",
        _("Repeated minimum temperatures"),
        _(
            "The same minimum temperature on many days in a row (more than 5 by default), "
            "which often means a value was copied forward."
        ),
        "quality-control",
        "repeated-values",
        question=_("How many repeats are flagged?"),
    ),
    T(
        "qc.nastatistics",
        _("Missing days per year"),
        _(
            "The number of missing days in each year for each variable. A year with more "
            "than 15 missing days, or a month with more than 3, gets no index value."
        ),
        "quality-control",
        "missing-days",
        question=_("When does a year get no index value?"),
    ),
    T(
        "qc.rounding",
        _("Decimal values"),
        _(
            "How often each decimal (.0 to .9) occurs. Too many .0 or .5 values point to "
            "rounding by observers, which affects counts of days above a threshold."
        ),
        "quality-control",
        "decimal-values",
    ),
    T(
        "qc.precip_histogram",
        _("Precipitation histogram"),
        _(
            "How often each amount of daily precipitation of 1 mm or more occurs. Gaps or "
            "spikes can show a change of instrument or reporting."
        ),
        "quality-control",
        "daily-series-and-histograms",
    ),
    T(
        "qc.daily_series",
        _("Daily series"),
        _(
            "The daily values of each variable over the whole record, with missing days "
            "marked, to spot gaps and suspect values by eye."
        ),
        "quality-control",
        "daily-series-and-histograms",
        question=_("What should I look for in the daily series?"),
    ),
    T(
        "qc.homogeneity",
        _("Homogeneity"),
        _(
            "The checks do not test homogeneity: shifts caused by a station move or a new "
            "instrument. Check and adjust for those with other tools before calculating "
            "indices."
        ),
        "quality-control",
        "what-the-checks-do-not-find",
    ),
    # ---- QC settings (QCParams) -------------------------------------------------------
    T(
        "qcparam.iqr_temp",
        _("Outlier range for temperature"),
        _(
            "How many interquartile ranges beyond the box a temperature must be to count "
            "as an outlier. Default 3; a smaller number flags more values."
        ),
        "quality-control",
        "outliers",
    ),
    T(
        "qcparam.iqr_prec",
        _("Outlier range for precipitation"),
        _(
            "How many interquartile ranges beyond the box a day's precipitation must be to "
            "count as an outlier. Default 5."
        ),
        "quality-control",
        "outliers",
    ),
    T(
        "qcparam.prec_max",
        _("Largest daily precipitation"),
        _("Daily precipitation above this amount (mm) is flagged for checking. Default 200."),
        "quality-control",
        "values-too-large",
    ),
    T(
        "qcparam.temp_max",
        _("Largest temperature"),
        _(
            "Temperatures above this value, or below its negative (°C), are flagged for "
            "checking. Default 50."
        ),
        "quality-control",
        "values-too-large",
    ),
    T(
        "qcparam.flatline_days",
        _("Days without change"),
        _(
            "A temperature that stays exactly the same for more than this many days in a "
            "row is flagged. Default 5."
        ),
        "quality-control",
        "repeated-values",
    ),
    T(
        "qcparam.jump",
        _("Temperature change"),
        _(
            "A change from one day to the next of this many degrees (°C) or more is "
            "flagged. Default 20."
        ),
        "quality-control",
        "jumps",
    ),
    # ---- Index settings (IndexParams) -------------------------------------------------
    T(
        "param.plot_title",
        _("Plot title"),
        _("Printed at the top of every plot. The station name is used if you leave it empty."),
        "indices",
        "settings",
    ),
    T(
        "param.wsdi_days",
        _("Days for WSDId"),
        _(
            "How many days in a row the maximum temperature must be above its 90th "
            "percentile to count towards WSDId. WSDI itself always uses 6. From 1 to 10; default 1."
        ),
        "indices",
        "settings",
    ),
    T(
        "param.csdi_days",
        _("Days for CSDId"),
        _(
            "How many days in a row the minimum temperature must be below its 10th "
            "percentile to count towards CSDId. CSDI itself always uses 6. From 1 to 10; default 1."
        ),
        "indices",
        "settings",
    ),
    T(
        "param.rx_days",
        _("Days for Rxdday"),
        _(
            "The length of the wettest spell Rxdday reports: the largest total over this "
            "many days in a row. Rx1day and Rx5day are always calculated too. Default 3."
        ),
        "indices",
        "settings",
    ),
    T(
        "param.txtn_days",
        _("Days for TXdTNd and TXbdTNbd"),
        _(
            "How many days in a row both the maximum and minimum temperature must be above "
            "their 95th percentile (TXdTNd) or below their 5th (TXbdTNbd). Default 2."
        ),
        "indices",
        "settings",
    ),
    T(
        "param.hdd_base",
        _("Base temperature for heating degree days"),
        _(
            "HDDheat adds up how far the daily mean temperature falls below this value "
            "(°C). Default 18."
        ),
        "indices",
        "settings",
    ),
    T(
        "param.cdd_base",
        _("Base temperature for cooling degree days"),
        _(
            "CDDcold adds up how far the daily mean temperature rises above this value "
            "(°C). Default 18."
        ),
        "indices",
        "settings",
    ),
    T(
        "param.gdd_base",
        _("Base temperature for growing degree days"),
        _(
            "GDDgrow adds up how far the daily mean temperature rises above this value "
            "(°C), the temperature a crop needs to grow. Default 10."
        ),
        "indices",
        "settings",
    ),
    T(
        "param.rnnmm",
        _("Rain amount for Rnnmm"),
        _(
            "Rnnmm counts the days with at least this much precipitation (mm). R10mm and "
            "R20mm are always calculated too. Default 30."
        ),
        "indices",
        "settings",
    ),
    T(
        "param.spei_months",
        _("Extra SPI and SPEI time scale"),
        _(
            "SPI and SPEI are always calculated over 3, 6 and 12 months. This adds one more "
            "time scale, in months. Default 24."
        ),
        "indices",
        "settings",
    ),
    T(
        "param.custom",
        _("Your own index"),
        _(
            "Counts the days a variable (TX, TN, TM, DTR or precipitation) is above or "
            "below a value you choose, for each year and month. TX ≥ 40 is written as "
            "TXge40."
        ),
        "indices",
        "your-own-index",
    ),
    # ---- Trends -----------------------------------------------------------------------
    T(
        "trend.sen_slope",
        _("Sen's slope"),
        _(
            "The trend is the median of the slopes between every pair of years. Unlike a "
            "least-squares line it is hardly affected by a few extreme years. Units are "
            "the index's units per year."
        ),
        "trends",
        "sens-slope",
    ),
    T(
        "trend.confidence",
        _("Lower and upper bounds"),
        _(
            "The 95% confidence interval of the slope. If both bounds have the same sign, "
            "the trend is significant at the 5% level."
        ),
        "trends",
        "confidence-bounds-and-significance",
    ),
    T(
        "trend.significance",
        _("Is the trend significant?"),
        _(
            "The trend file has no p-value. Read significance from the bounds: when the "
            "interval from lower to upper bound does not include zero, the trend is "
            "significant at the 5% level."
        ),
        "trends",
        "confidence-bounds-and-significance",
    ),
    T(
        "trend.minimum_data",
        _("When there is no trend"),
        _(
            "A trend needs at least 10 values and at least 70% of the series present. "
            "Otherwise the bounds and slope are left empty (NA)."
        ),
        "trends",
        "when-no-trend-is-given",
    ),
    T(
        "trend.seasons",
        _("Seasonal trends"),
        _(
            "For monthly indices the trend file also gives trends for December-February, "
            "March-May, June-August and September-November."
        ),
        "trends",
        "the-trend-file",
    ),
    # ---- Results ----------------------------------------------------------------------
    T(
        "results.missing_value",
        _("Missing values in the results"),
        _(
            "Years and months without enough data are written as -99.9 in the index "
            "files. Remove them before calculating with the values in a spreadsheet."
        ),
        "indices",
        "missing-data",
    ),
    T(
        "results.standardised",
        _("Standardised values"),
        _(
            "Each value minus the mean of all years, divided by their standard deviation, "
            "so indices with different units can be compared."
        ),
        "indices",
        "the-index-files",
    ),
    T(
        "results.thresholds",
        _("Threshold file"),
        _(
            "The percentile thresholds for each day of the year, calculated from the base "
            "period. For interest; the indices have already used them."
        ),
        "base-period",
        "the-threshold-file",
    ),
    T(
        "results.files",
        _("What is in the download"),
        _(
            "Folders for the quality checks (qc), index tables (indices), plots, "
            "thresholds (thres), trends (trend) and sector correlation (corr). The PDF "
            "report is a separate download."
        ),
        "indices",
        "the-index-files",
    ),
    # ---- Sector data ------------------------------------------------------------------
    T(
        "sector.file",
        _("The sector data file"),
        _(
            "A CSV file of yearly values, such as crop yields: a first row of column names, "
            "then a year and a value on each row. Write missing values as -99.9."
        ),
        "sector",
        "the-sector-file",
    ),
    T(
        "sector.title",
        _("Plot title"),
        _("Printed on each correlation plot. The station name is used if you leave it empty."),
        "sector",
        "settings",
    ),
    T(
        "sector.y_label",
        _("Label for the y axis"),
        _(
            "The name and units of your sector data, for example Wheat yield (t/ha). "
            "Taken from the file name if you leave it empty."
        ),
        "sector",
        "settings",
    ),
    T(
        "sector.detrend",
        _("Detrend the sector data"),
        _(
            "Removes the long-term trend from the sector data before comparing. Without it, "
            "a steady rise in yields from better farming can look like a link with warming."
        ),
        "sector",
        "detrending",
    ),
    T(
        "sector.correlation",
        _("Correlation with the indices"),
        _(
            "The correlation coefficient (from -1 to 1) between the sector data and each "
            "index, over the years both have. It shows association, not cause."
        ),
        "sector",
        "reading-the-results",
    ),
    T(
        "sector.regression",
        _("Regression on temperature"),
        _(
            "Scatter plots of the sector data against yearly mean maximum, minimum and "
            "mean temperature and days above 30 °C, with a fitted line and R²."
        ),
        "sector",
        "reading-the-results",
    ),
    # ---- Gridded data -----------------------------------------------------------------
    T(
        "gridded.files",
        _("Gridded input files"),
        _(
            "One to three CF netCDF files with daily maximum and minimum temperature and "
            "precipitation on a shared time axis. Each variable must be in one file."
        ),
        "gridded",
        "input-files",
    ),
    T(
        "gridded.variables",
        _("Variable names"),
        _(
            "The names of the maximum temperature, minimum temperature and precipitation "
            "variables in your files, for example tasmax, tasmin and pr."
        ),
        "gridded",
        "input-files",
    ),
    T(
        "gridded.base_period",
        _("Base period for a grid"),
        _(
            "The years the percentile thresholds are calculated from in every cell. It must "
            "lie within the files, unless you give a thresholds file."
        ),
        "gridded",
        "thresholds-from-another-period",
    ),
    T(
        "gridded.thresholds_file",
        _("Thresholds file"),
        _(
            "Percentile thresholds calculated earlier from another set of files, for "
            "example a historical run, so that a future run uses the same thresholds."
        ),
        "gridded",
        "thresholds-from-another-period",
    ),
    T(
        "gridded.indices",
        _("Indices to calculate"),
        _("Choose fewer indices to finish sooner. Every index is calculated by default."),
        "gridded",
        "running-a-grid",
    ),
    T(
        "gridded.output",
        _("Output file names"),
        _(
            "One netCDF file per index and time scale, named in the CMIP5 style, for "
            "example r20mm_ANN_climpactpy_historical_NA_1991-2010.nc."
        ),
        "gridded",
        "output-files",
    ),
    T(
        "gridded.institution",
        _("Institution"),
        _("Your institution's name and id, written into the output files' attributes."),
        "gridded",
        "output-files",
    ),
    T(
        "gridded.workers",
        _("Processor threads"),
        _("How many processor threads calculate cells at once. More is faster, up to your cores."),
        "gridded",
        "running-a-grid",
    ),
    T(
        "gridded.max_values",
        _("Values read at once"),
        _(
            "How many million values are read into memory at a time. Lower it if the "
            "computer runs out of memory. Default 5, or less for a small grid, so that "
            "progress shows in small steps."
        ),
        "gridded",
        "running-a-grid",
    ),
)


def _index_topics() -> list[Topic]:
    topics = []
    for info in catalogue():
        units = UNITS.get(info.units, info.units)
        topics.append(
            Topic(
                id=info.topic_id,
                title=f"{info.name}: {gettext(info.long_name)}",
                text=_IndexText(info.definition, units),
                guide="indices",
                anchor=info.anchor,
                kind="index",
            )
        )
    return topics


class _IndexText:
    """An index definition translated when shown (the definitions are core data, listed
    for translators in ``index_messages.py``), with its units."""

    def __init__(self, definition: str, units):
        self.definition = definition
        self.units = units

    def __str__(self) -> str:
        return gettext("%(definition)s. Units: %(units)s.") % {
            "definition": gettext(self.definition),
            "units": self.units,
        }

    def __html__(self) -> str:
        from django.utils.html import escape

        return escape(str(self))


def topics() -> dict[str, Topic]:
    """Every topic by id. Index titles are translated when the dict is built, so it is
    built per call (cheap: under 200 topics)."""
    out = {t.id: t for t in HAND_WRITTEN}
    for topic in _index_topics():
        out[topic.id] = topic
    return out


@cache
def topic_ids() -> frozenset[str]:
    return frozenset(t.id for t in HAND_WRITTEN) | {i.topic_id for i in catalogue()}


class UnknownTopic(KeyError):
    pass


def get_topic(topic_id: str) -> Topic:
    try:
        return topics()[topic_id]
    except KeyError:
        raise UnknownTopic(topic_id) from None


def index_topic_for_output(name: str) -> str | None:
    """The topic id for an index output name (``rx3day_ANN`` -> ``index.rxdday``); a
    custom index such as ``TXge40`` gets ``param.custom``; ``None`` if neither."""
    info = index_for_output(name)
    if info is not None:
        return info.topic_id
    import re

    if re.match(r"^(TX|TN|TM|DTR|PR)(gt|ge|lt|le)-?[\d.]+(_(ANN|MON))?$", name):
        return "param.custom"
    return None

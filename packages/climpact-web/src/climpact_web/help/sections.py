"""Section help (#177): the help behind each section's ⓘ, shown in the drawer.

A screen puts one ⓘ beside a section's heading with ``{% section_help "load.details" %}``
(``templatetags/help.py``). The button opens the drawer (``components/drawer.html``) with
the section's help: a few short notes, then the help topics of the section's fields and
results (``topics.py``), then one link per guide that says more. Without JavaScript the ⓘ
is a link to the same help on a page of its own (``help:section``).

A section is the unit of help, not a field: fields keep a hint only when their value is
not self-explanatory (DESIGN.md, "Don't put a help link under every field"). The ids
are ``<page>.<section>``; a test checks that every topic named here exists, and that
every id used in a template is here.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from climpact_web.help.guides import get_guide
from climpact_web.help.topics import Topic, UnknownTopic, get_topic


@dataclass(frozen=True)
class Note:
    """A short paragraph of a section's help, with an optional heading."""

    text: str | Promise
    title: str | Promise = ""


@dataclass(frozen=True)
class Section:
    id: str
    title: str | Promise  # the section's heading, as on the screen
    topics: tuple[str, ...] = ()
    notes: tuple[Note, ...] = ()
    # A template with help that needs markup (an example file), shown after the notes.
    extra: str = ""

    @property
    def url(self) -> str:
        return reverse("help:section", args=[self.id])

    @property
    def element_id(self) -> str:
        return "help-" + self.id.replace(".", "-").replace("_", "-")


def S(id, title, topics=(), notes=(), extra=""):  # noqa: N802 (a table of constructors)
    notes = tuple(n if isinstance(n, Note) else Note(n) for n in notes)
    return Section(id, title, tuple(topics), notes, extra)


SECTIONS = (
    # ---- Single station: Load ----------------------------------------------------------
    S(
        "upload.file",
        _("Your station file"),
        ["station.file"],
        extra="help/sections/_station_file_format.html",
    ),
    S(
        "load.details",
        _("Station details"),
        ["station.name", "station.latitude", "station.longitude", "station.base_period"],
        [_("These details change the results. Check them before you go on.")],
    ),
    S(
        "load.data",
        _("Your data"),
        ["qc.daily_series", "qc.nastatistics"],
        [
            _("This is the data as Climpact read it from your file."),
            _("The chart has no quality flags. The quality checks are the next step."),
            _(
                "To load another file, use Replace beside File in the Inputs panel. The "
                "station details are kept."
            ),
        ],
    ),
    # ---- Quality -------------------------------------------------------------------------
    S(
        "quality.verdict",
        _("Is the data fit to use?"),
        ["qc.homogeneity"],
        [
            _("Climpact never changes your data. You decide whether to correct the file."),
            _(
                "When you replace the file with a corrected one, the checks run again. "
                "Your station details and thresholds are kept."
            ),
            Note(_("Nothing looks wrong."), _("Ready to use")),
            Note(
                _("Up to 0.1% of the values checked look wrong. Correct them if you can."),
                _("Usable"),
            ),
            Note(
                _(
                    "More than 0.1% of the values look wrong, or more than 10% of the years "
                    "are too incomplete for annual values. You can still go on."
                ),
                _("Fix the file first"),
            ),
            _("Unusual values that may be real are counted. They never change the verdict."),
        ],
    ),
    S(
        "quality.wrong",
        _("Look wrong"),
        ["qc.tmaxmin", "qc.toolarge", "qc.duplicates"],
        [_("These values are almost always mistakes, such as typing errors or swapped columns.")],
    ),
    S(
        "quality.missing",
        _("Missing data"),
        ["qc.nastatistics", "results.missing_value"],
        [
            _(
                "A year marked “no annual value” has its annual indices left missing. Its "
                "monthly indices are missing only for the months concerned."
            ),
            _("Years not in the table have no missing days."),
        ],
    ),
    S(
        "quality.daily",
        _("Daily values"),
        ["qc.daily_series"],
        [
            _("Flagged values are circled. Click a circle to see the value in the list's detail."),
            _("“Show on the daily chart” in a finding's detail brings you back to the day here."),
            _("Drag across a chart to zoom in. Double-click to see all of it."),
        ],
    ),
    S(
        "quality.distributions",
        _("Distributions"),
        ["qc.outliers", "qc.rounding", "qc.precip_histogram", "qc.homogeneity"],
        [
            _("These are the plots of the quality checks of Climpact for R."),
            Note(
                _(
                    "One box per calendar month. The box spans the middle half of the "
                    "values and the line is the median. The whiskers end at the outlier "
                    "range set in the thresholds."
                ),
                _("By month"),
            ),
            Note(
                _(
                    "One box per year. The whiskers are at 4 interquartile ranges for "
                    "precipitation and 3 for temperature. A year that stands out may hold "
                    "wrong values or a change at the station."
                ),
                _("By year"),
            ),
        ],
    ),
    S(
        "quality.thresholds",
        _("Thresholds"),
        [
            "qcparam.iqr_temp",
            "qcparam.iqr_prec",
            "qcparam.prec_max",
            "qcparam.temp_max",
            "qcparam.flatline_days",
            "qcparam.jump",
        ],
        [
            _("The defaults are those of Climpact for R. Smaller numbers flag more values."),
            _("Change them in Your inputs. The checks run again and the verdict updates."),
        ],
    ),
    # ---- The Index settings sheet (#199; "Adjust and recalculate" on Results, #178) --------
    S("calculate.plots", _("Plots"), ["param.plot_title"]),
    S(
        "calculate.spells",
        _("Spell lengths"),
        ["param.wsdi_days", "param.csdi_days", "param.rx_days", "param.txtn_days"],
        [
            _("These set how many days in a row count towards an index."),
            _(
                "The number is part of the index's file name. With 3 days, WSDId is "
                "written as wsdi3 and Rxdday as rx3day."
            ),
        ],
    ),
    S(
        "calculate.degree",
        _("Degree days"),
        ["param.hdd_base", "param.cdd_base", "param.gdd_base"],
        [
            _("These are the base temperatures that degree days are counted from."),
            _("The base is part of the file name. With 18 °C, HDDheat is written as hddheat18."),
        ],
    ),
    S(
        "calculate.prcp",
        _("Precipitation and drought"),
        ["param.rnnmm", "param.spei_months"],
        [
            _(
                "The amount and the months are part of the file names. With 30 mm, Rnnmm "
                "is written as r30mm. With 24 months, SPI is written as 24month_spi."
            )
        ],
    ),
    S("calculate.custom", _("Your own index"), ["param.custom"]),
    S(
        "calculate.ehf",
        _("Heatwave definition"),
        ["index.hwEHF", "index.hw"],
        [
            _(
                "Heatwaves are found from the 90th percentiles of TX and TN, and from the "
                "excess heat factor (EHF) of Nairn and Fawcett (2013)."
            ),
            _("Climpact uses this definition for every station. There is nothing to choose."),
        ],
    ),
    S(
        "calculate.files",
        _("Files"),
        ["results.files"],
        [
            Note(
                _(
                    "A PNG of every index and a PDF of them all, as Climpact for R draws "
                    "them. They take about two thirds of the time. The charts on the "
                    "results page do not need them."
                ),
                _("Plots"),
            ),
            Note(
                _("Every result file in one download, in the folder layout of Climpact for R."),
                _("Zip file"),
            ),
            Note(
                _(
                    "One PDF to read, print or send. It has the station and settings, what "
                    "the quality checks found, and a page per index with its plot and "
                    "trends. Climpact for R has no report. It is a separate download, so "
                    "the zip keeps the layout of R."
                ),
                _("Report"),
            ),
        ],
    ),
    # ---- Results ------------------------------------------------------------------------
    S(
        "results.findings",
        _("What changed"),
        ["trend.sen_slope", "trend.significance"],
        [
            _("Each theme shows up to three of its significant trends, largest first."),
            _(
                "Largest means the trend per decade divided by how much the index varies "
                "from year to year. So days, °C and mm can be compared."
            ),
            _("“No significant change” is a finding too."),
        ],
    ),
    S(
        "results.catalogue",
        _("All indices"),
        ["trend.minimum_data", "results.missing_value", "trend.significance"],
        [
            _(
                "“Also measured” holds the averages, the growing season and degree days, "
                "your own index and the daily heat and cold factors."
            ),
            _(
                "Select a column header to sort by it, and again to reverse the order. A "
                "trend sorts by its value in the index's own units; indices without a "
                "trend stay last."
            ),
            _("Climpact does not write a table whose values are all missing."),
        ],
    ),
    # ---- One index ----------------------------------------------------------------------
    S(
        "result.index",
        _("This index"),
        ["trend.sen_slope", "trend.confidence", "trend.minimum_data"],
    ),
    S("result.anomalies", _("Standardised anomalies"), ["results.standardised"]),
    S(
        "result.trends",
        _("Trends in the trend file"),
        ["trend.confidence", "trend.seasons"],
        [
            _(
                "These are the rows of the trend file for this index, as written. The "
                "slope is Sen's slope per year, or per month for the monthly row, with "
                "its 95% confidence interval."
            )
        ],
    ),
    # ---- Files --------------------------------------------------------------------------
    S(
        "files.page",
        _("Files"),
        ["results.files", "results.thresholds"],
        [
            Note(
                _("The files of the calculation, in the folder layout of Climpact for R."),
                _("Zip file"),
            ),
            Note(_("The easiest file to read and share. It is not in the zip."), _("Report")),
            Note(
                _(
                    "The rows each check found, and the days missing per year, as CSV. "
                    "Climpact for R writes the same files in its qc folder."
                ),
                _("Quality checks"),
            ),
            Note(
                _(
                    "Each index has a table (CSV) and a plot of each series (PNG). The PDF "
                    "of all the plots is in the order of Climpact for R. The "
                    "days of occurrence are columns of the table. To save a chart as you "
                    "see it, open the index and use PNG or SVG above its chart."
                ),
                _("Each index"),
            ),
            Note(
                _(
                    "The correlation of each index with your sector data, and the scatter "
                    "plots. Climpact for R writes the same files in its corr folder."
                ),
                _("Sector comparison"),
            ),
        ],
    ),
    # ---- Sector -------------------------------------------------------------------------
    S(
        "sector.data",
        _("Sector data"),
        ["sector.file"],
        [_("Climpact correlates yearly sector data with the station's indices.")],
    ),
    S(
        "sector.plot",
        _("Plot attributes"),
        ["sector.title", "sector.y_label", "sector.detrend"],
        [
            _("Climpact fills in a title and a y-axis label. You can change them."),
            _("An empty label uses the file name, up to its first _ or full stop."),
        ],
    ),
    S(
        "sector.correlation",
        _("Correlation with each index"),
        ["sector.correlation"],
        [
            _(
                "Missing index values are correlated as the number -99.9, as in Climpact "
                "for R. This can distort the correlation of an index with missing years."
            ),
            _("NA means no correlation: a value is missing or does not vary."),
        ],
    ),
    S("sector.scatter", _("Your data against the station's temperatures"), ["sector.regression"]),
    # ---- Batch and gridded (fields that had their own help link before #177) --------
    S(
        "batch.options",
        _("Settings"),
        ["batch.base_period", "batch.workers", "batch.plots"],
    ),
    S(
        "gridded.task",
        _("What to calculate"),
        ["gridded.thresholds_file", "gridded.base_period"],
    ),
    S(
        "gridded.output",
        _("Output"),
        ["gridded.output", "gridded.institution"],
    ),
    S(
        "gridded.settings",
        _("Index parameters"),
        [
            "param.wsdi_days",
            "param.csdi_days",
            "param.rx_days",
            "param.txtn_days",
            "param.hdd_base",
            "param.cdd_base",
            "param.gdd_base",
            "param.rnnmm",
        ],
    ),
    S(
        "gridded.computing",
        _("Computing"),
        ["gridded.workers", "gridded.max_values"],
    ),
)


class UnknownSection(KeyError):
    pass


@cache
def _by_id() -> dict[str, Section]:
    return {s.id: s for s in SECTIONS}


def section_ids() -> frozenset[str]:
    return frozenset(_by_id())


def get_section(section_id: str) -> Section:
    try:
        return _by_id()[section_id]
    except KeyError:
        raise UnknownSection(section_id) from None


def section_context(section: Section, extra_topics=()) -> dict:
    """What the drawer and the section page show: the notes, the topics (``extra_topics``
    first, for a screen that adds its own, as an index page its index), and one link per
    guide, to the first of the section's topics in it."""
    ids = []
    for topic_id in [*extra_topics, *section.topics]:
        if topic_id and topic_id not in ids:
            ids.append(topic_id)
    shown: list[Topic] = [get_topic(t) for t in ids]
    guides, links = set(), []
    for topic in shown:
        if topic.guide and topic.guide not in guides:
            guides.add(topic.guide)
            guide = get_guide(topic.guide)
            links.append({"url": topic.url, "title": guide.title if guide else topic.guide})
    return {"section": section, "topics": shown, "guide_links": links}


def parse_topics(value) -> list[str]:
    """Topic ids from a template argument or a query string: a list, or one string of
    ids separated by spaces or commas. Unknown ids raise :class:`UnknownTopic`."""
    if not value:
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).replace(",", " ").split()
    for item in items:
        get_topic(item)
    return list(items)


__all__ = [
    "SECTIONS",
    "Note",
    "Section",
    "UnknownSection",
    "UnknownTopic",
    "get_section",
    "parse_topics",
    "section_context",
    "section_ids",
]

"""The index catalogue for the help (#81), built from the core's ``climate.indices.csv``.

The core's file is the single source of the definitions: the indices guide, the index
help topics and the index names on the results screens all come from it. This module adds
what the file lacks for people reading the app: a display name in the usual ET-SCI
spelling (``TXx``, ``Rx1day``), a group, the parameter that sets ``d``, ``n`` or ``nn``,
and plain units (``°C`` for ``degrees_C``).

The definitions are core data, not template text, so ``makemessages`` cannot find them.
``index_messages.py`` lists every one with ``gettext_noop`` so that translators get them in
the catalogue; regenerate it with ``python -m climpact_web.help.indices`` when the core's
file changes (a test fails when it is out of date).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path

from django.utils.translation import gettext_lazy as _

# The usual spelling of each short name (ETCCDI and ET-SCI papers, the R plots).
DISPLAY_NAMES = {
    "fd": "FD",
    "tnlt2": "TNlt2",
    "tnltm2": "TNltm2",
    "tnltm20": "TNltm20",
    "id": "ID",
    "su": "SU",
    "tr": "TR",
    "gsl": "GSL",
    "txx": "TXx",
    "tnn": "TNn",
    "tnx": "TNx",
    "txn": "TXn",
    "dtr": "DTR",
    "wsdi": "WSDI",
    "wsdid": "WSDId",
    "csdi": "CSDI",
    "csdid": "CSDId",
    "txgt50p": "TXgt50p",
    "tx10p": "TX10p",
    "tx90p": "TX90p",
    "tn10p": "TN10p",
    "tn90p": "TN90p",
    "tmge5": "TMge5",
    "tmlt5": "TMlt5",
    "tmge10": "TMge10",
    "tmlt10": "TMlt10",
    "txge30": "TXge30",
    "txge35": "TXge35",
    "tx95t": "TX95t",
    "hddheatn": "HDDheatn",
    "cddcoldn": "CDDcoldn",
    "gddgrown": "GDDgrown",
    "cdd": "CDD",
    "cwd": "CWD",
    "r10mm": "R10mm",
    "r20mm": "R20mm",
    "rx1day": "Rx1day",
    "rx5day": "Rx5day",
    "prcptot": "PRCPTOT",
    "sdii": "SDII",
    "r95p": "R95p",
    "r99p": "R99p",
    "r95ptot": "R95pTOT",
    "r99ptot": "R99pTOT",
    "rxdday": "Rxdday",
    "rnnmm": "Rnnmm",
    "txdtnd": "TXdTNd",
    "txbdtnbd": "TXbdTNbd",
    "hw": "HW",
    "hwEHF": "EHF heatwaves",
    "spei": "SPEI",
    "spi": "SPI",
    "tmm": "TMm",
    "txm": "TXm",
    "tnm": "TNm",
}

# Groups for the guide, in order. Every short name of the core's file is in exactly one
# (a test checks).
GROUPS = (
    (
        "temperature-thresholds",
        _("Temperature: days above or below a fixed value"),
        ("fd", "tnlt2", "tnltm2", "tnltm20", "id", "su", "tr", "tmge5", "tmlt5", "tmge10")
        + ("tmlt10", "txge30", "txge35"),
    ),
    (
        "temperature-extremes",
        _("Temperature: extremes, means and range"),
        ("txx", "tnn", "tnx", "txn", "dtr", "tmm", "txm", "tnm"),
    ),
    (
        "temperature-percentiles",
        _("Temperature: compared with the base period"),
        ("txgt50p", "tx10p", "tx90p", "tn10p", "tn90p", "tx95t", "wsdi", "wsdid", "csdi")
        + ("csdid", "txdtnd", "txbdtnbd"),
    ),
    (
        "temperature-seasons",
        _("Temperature: growing season and degree days"),
        ("gsl", "hddheatn", "cddcoldn", "gddgrown"),
    ),
    (
        "precipitation",
        _("Precipitation"),
        ("prcptot", "sdii", "r10mm", "r20mm", "rnnmm", "rx1day", "rx5day", "rxdday", "cdd")
        + ("cwd", "r95p", "r99p", "r95ptot", "r99ptot"),
    ),
    ("heatwaves", _("Heatwaves"), ("hw", "hwEHF")),
    ("drought", _("Drought"), ("spi", "spei")),
)

# The parameter (help topic id) that sets the user-defined part of an index.
INDEX_PARAMS = {
    "wsdid": "param.wsdi_days",
    "csdid": "param.csdi_days",
    "rxdday": "param.rx_days",
    "rnnmm": "param.rnnmm",
    "txdtnd": "param.txtn_days",
    "txbdtnbd": "param.txtn_days",
    "hddheatn": "param.hdd_base",
    "cddcoldn": "param.cdd_base",
    "gddgrown": "param.gdd_base",
    "spei": "param.spei_months",
    "spi": "param.spei_months",
}

UNITS = {
    "days": _("days"),
    "degrees_C": "°C",
    "%": _("% of days"),
    "degree-days": _("degree-days"),
    "mm": "mm",
    "mm/day": _("mm per day"),
    "events": _("events"),
    "unitless": _("no units"),
    "NA": _("several"),
}


@dataclass(frozen=True)
class IndexInfo:
    short: str  # the core's short name, e.g. "txx", "rxdday"
    name: str  # display name, e.g. "TXx"
    long_name: str  # sentence case, from the core's file
    definition: str  # the annual row's definition, with °C
    units: str  # the core's units
    annual: bool
    monthly: bool
    base_period: bool  # uses the base period's percentiles
    group: str

    @property
    def anchor(self) -> str:
        return f"index-{self.short.lower()}"

    @property
    def topic_id(self) -> str:
        return f"index.{self.short}"

    @property
    def param_topic(self) -> str | None:
        return INDEX_PARAMS.get(self.short)


# Words kept capitalised when long names are put in sentence case.
_KEEP_CASE = {"Nairn", "Fawcett", "TX", "TN", "TM", "PR", "DTR", "WSDI", "CSDI", "Max", "Min"}


def sentence_case(text: str) -> str:
    words = text.split(" ")
    out = [words[0]]
    for word in words[1:]:
        if word in _KEEP_CASE or not word[:1].isupper() or word[1:2].isupper():
            out.append(word)
        else:
            out.append(word.lower())
    return " ".join(out)


def plain(text: str) -> str:
    """The core's definition with ``degrees_C`` written as °C."""
    return re.sub(r"\s*degrees_C", " °C", text).replace("  ", " ").strip()


def _rows() -> list[dict[str, str]]:
    text = resources.files("climpact.data").joinpath("climate.indices.csv").read_text()
    return list(csv.DictReader(text.splitlines(), delimiter="\t"))


@cache
def catalogue() -> tuple[IndexInfo, ...]:
    """One entry per short name, in the order of the core's file."""
    rows = _rows()
    group_of = {short: key for key, _label, shorts in GROUPS for short in shorts}
    seen: dict[str, dict] = {}
    for row in rows:
        short = row["Short.name"]
        entry = seen.setdefault(short, {"rows": []})
        entry["rows"].append(row)
    out = []
    for short, entry in seen.items():
        first = entry["rows"][0]
        flags = {r["Annual.flag"] for r in entry["rows"]}
        # The annual row's definition reads best ("Annual number of days ..."); tx95t
        # and the monthly-only drought indices have one row.
        annual_row = next((r for r in entry["rows"] if r["Annual.flag"] == "T"), first)
        out.append(
            IndexInfo(
                short=short,
                name=DISPLAY_NAMES.get(short, short),
                long_name=sentence_case(plain(first["Long.name"])),
                definition=plain(annual_row["Definition"]),
                units=first["Units"],
                annual="T" in flags,
                monthly="F" in flags,
                base_period=first["Base.period.flag"] == "T",
                group=group_of.get(short, ""),
            )
        )
    return tuple(out)


def by_short() -> dict[str, IndexInfo]:
    return {info.short: info for info in catalogue()}


# Output names that depend on a parameter, to the short name of the core's file.
_PATTERNS = (
    (re.compile(r"^r\d+(\.\d+)?mm$"), "rnnmm"),
    (re.compile(r"^rx\d+day$"), "rxdday"),
    (re.compile(r"^wsdi\d+$"), "wsdid"),
    (re.compile(r"^csdi\d+$"), "csdid"),
    (re.compile(r"^tx\d+tn\d+$"), "txdtnd"),
    (re.compile(r"^txb\d+tnb\d+$"), "txbdtnbd"),
    (re.compile(r"^hddheat"), "hddheatn"),
    (re.compile(r"^cddcold"), "cddcoldn"),
    (re.compile(r"^gddgrow"), "gddgrown"),
    (re.compile(r"^(tx90|tn90|tm90)-"), "hw"),
    (re.compile(r"^ehf-"), "hwEHF"),
    (re.compile(r"^(ehf|ecf)daily$"), "hwEHF"),
    (re.compile(r"^\d+month_spi$"), "spi"),
    (re.compile(r"^\d+month_spei$"), "spei"),
)


def index_for_output(name: str) -> IndexInfo | None:
    """The catalogue entry for an output name as the core writes it: ``txx``,
    ``txx_MON``, ``rx3day_ANN``, ``r30mm``, ``TX90-HWN_ANN``, ``3month_spi_MON``...
    ``None`` for names that are not indices (a custom index such as ``TXge40``)."""
    base = re.sub(r"_(ANN|MON|DAY)$", "", name)
    indices = by_short()
    if base in indices:
        return indices[base]
    lower = base.lower()
    for short, info in indices.items():
        if short.lower() == lower:
            return info
    for pattern, short in _PATTERNS:
        if pattern.search(lower):
            return indices[short]
    return None


# ---- index_messages.py -------------------------------------------------------------------

MESSAGES_FILE = Path(__file__).with_name("index_messages.py")


def messages_source() -> str:
    """The text of ``index_messages.py``: every long name and definition, for
    ``makemessages``."""
    strings: list[str] = []
    for info in catalogue():
        for text in (info.long_name, info.definition):
            if text not in strings:
                strings.append(text)
    lines = [
        '"""Generated by ``python -m climpact_web.help.indices`` from the core\'s',
        "``climate.indices.csv``: the index names and definitions, so that ``makemessages`` puts",
        'them in the translation catalogue. Do not edit."""',
        "",
        "from django.utils.translation import gettext_noop",
        "",
        "MESSAGES = (",
    ]
    for text in strings:
        line = f"    gettext_noop({_quoted(text)}),"
        if len(line) > 100:  # as ruff format wraps it
            line = f"    gettext_noop(\n        {_quoted(text)}\n    ),"
        lines.append(line)
    lines += [")", ""]
    return "\n".join(lines)


def _quoted(text: str) -> str:
    """A double-quoted Python string, as ruff format writes it."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


if __name__ == "__main__":
    MESSAGES_FILE.write_text(messages_source())
    print(f"wrote {MESSAGES_FILE}")

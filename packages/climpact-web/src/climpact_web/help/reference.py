"""The index reference (#319, the HelpIndices and HelpIndex boards): a list of every index
by theme, and a page for each index at ``/help/indices/<code>/``.

Everything a page says about one index is generated, so that it cannot drift from the
core:

- the definition, R's long name, unit, time scales and base period from the catalogue
  (:mod:`climpact_web.help.indices`, the core's ``climate.indices.csv``);
- the theme and its hue from :mod:`climpact_web.stations.themes`, so the reference reads
  like a station's Indices;
- the variables an index needs from the core's gridded variable list
  (``climpact.gridded.indices``, R's ``get.climdex.variable.list``);
- the setting and its default from ``INDEX_PARAMS`` and ``IndexParams``, and the file
  names from the core's renaming (``rx3day``, ``wsdi1``, ``hddheat18``);
- the missing-data line from the core's rules (``MAX_MISSING_DAYS``).

Only the lead sentence, How it is calculated (written once per kind of index) and the few
"Read with care" boxes are written by hand, in ``guides/<language>/index-notes.md``.

Each index has one address, its lowercase short name (``/help/indices/tx90p/``); other
spellings and output names (``TX90p``, ``wsdi3``, ``24month_spi``) redirect to it
(:func:`canonical_slug`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import markdown
from django.urls import reverse
from django.utils.translation import get_language, gettext
from django.utils.translation import gettext_lazy as _

from climpact.config import IndexParams
from climpact_web.help.guides import GUIDES_DIR, language_candidates, strip_tags
from climpact_web.help.indices import (
    GROUPS,
    INDEX_PARAMS,
    UNITS,
    IndexInfo,
    by_short,
    catalogue,
    index_for_output,
)
from climpact_web.stations.themes import THEMES, hue_of

NOTES_FILE = "index-notes.md"
STATION = "sydney"  # the command-line example's station, from sydney.txt

# The kind of each index: which text How it is calculated starts with.
KINDS = {
    "fixed-count": (
        "fd tnlt2 tnltm2 tnltm20 id su tr txge30 txge35 tmge5 tmlt5 tmge10 tmlt10 r10mm r20mm rnnmm"
    ),
    "percentile-count": "txgt50p tx10p tx90p tn10p tn90p",
    "threshold-value": "tx95t",
    "spell": "wsdi wsdid csdi csdid",
    "dual-spell": "txdtnd txbdtnbd",
    "rain-spell": "cdd cwd",
    "extreme": "txx tnn tnx txn",
    "rain-extreme": "rx1day rx5day rxdday",
    "mean": "txm tnm tmm dtr",
    "rain-total": "prcptot sdii",
    "rain-percentile": "r95p r99p r95ptot r99ptot",
    "degree-days": "hddheatn cddcoldn gddgrown",
    "season": "gsl",
    "heatwave": "hw hwEHF",
    "drought": "spi spei",
}
KIND_OF = {short: kind for kind, shorts in KINDS.items() for short in shorts.split()}

# The percentile in an index's definition, for the kind's text.
PERCENTILES = {
    "txgt50p": _("median (50th percentile)"),
    "tx10p": _("10th percentile"),
    "tn10p": _("10th percentile"),
    "tx90p": _("90th percentile"),
    "tn90p": _("90th percentile"),
    "r95p": _("95th percentile"),
    "r95ptot": _("95th percentile"),
    "r99p": _("99th percentile"),
    "r99ptot": _("99th percentile"),
}

# The index that is its opposite, listed first under Related indices.
COUNTERPARTS = {
    "tx90p": "tx10p",
    "tn90p": "tn10p",
    "wsdi": "csdi",
    "wsdid": "csdid",
    "txdtnd": "txbdtnbd",
    "txx": "txn",
    "tnx": "tnn",
    "su": "id",
    "tr": "fd",
    "cdd": "cwd",
    "spi": "spei",
    "hddheatn": "cddcoldn",
    "tmge5": "tmlt5",
    "tmge10": "tmlt10",
    "r95p": "r95ptot",
    "r99p": "r99ptot",
    "rx1day": "rx5day",
    "hw": "hwEHF",
    "txm": "tnm",
}
COUNTERPARTS |= {b: a for a, b in list(COUNTERPARTS.items()) if b not in COUNTERPARTS}

# Titles on the page that say "its full name", not the short one: where the short name
# only repeats the code with a parameter ("SPI, n months"), R's long name instead.
LONG_TITLES = ("spi", "spei")

ZHANG_2011 = (
    "Zhang X, Alexander L, Hegerl G C and others (2011). Indices for monitoring changes in "
    "extremes based on daily temperature and precipitation data. WIREs Climate Change 2, "
    "851–870."
)
WMO_2016 = "WMO (2016). Handbook of drought indicators and indices. WMO-No. 1173."
REFERENCES = {
    "hw": (
        "Perkins S E and Alexander L V (2013). On the measurement of heat waves. Journal of "
        "Climate 26, 4500–4517.",
    ),
    "hwEHF": (
        "Nairn J R and Fawcett R G (2015). The excess heat factor: a metric for heatwave "
        "intensity and its use in classifying heatwave severity. International Journal of "
        "Environmental Research and Public Health 12, 227–253.",
    ),
    "spi": (
        "McKee T B, Doesken N J and Kleist J (1993). The relationship of drought frequency "
        "and duration to time scales. 8th Conference on Applied Climatology, 179–184.",
        WMO_2016,
    ),
    "spei": (
        "Vicente-Serrano S M, Beguería S and López-Moreno J I (2010). A multiscalar drought "
        "index sensitive to global warming: the standardized precipitation "
        "evapotranspiration index. Journal of Climate 23, 1696–1718.",
        WMO_2016,
    ),
}

# The variables each index needs: R's gridded variable list (tavg: TM, the mean of TX and
# TN), with the indices that need more than one.
USES_OVERRIDES = {
    "dtr": "TX, TN",
    "txdtnd": "TX, TN",
    "txbdtnbd": "TX, TN",
    "hw": "TX, TN",
    "spei": "PR, TX, TN",
}
VARIABLE_LABELS = {"tmax": "TX", "tmin": "TN", "prec": "PR", "tavg": "TM"}

# The command-line option and an example value for each setting (IndexParams field).
SETTING_OPTIONS = {
    "wsdi_days": ("--wsdi-days", 3, ""),
    "csdi_days": ("--csdi-days", 3, ""),
    "rx_days": ("--rx-days", 7, ""),
    "txtn_days": ("--txtn-days", 3, ""),
    "hdd_base": ("--hdd-base", 15.0, " °C"),
    "cdd_base": ("--cdd-base", 22.0, " °C"),
    "gdd_base": ("--gdd-base", 5.0, " °C"),
    "rnnmm": ("--rnnmm", 50.0, " mm"),
    "spei_months": ("--spei-months", 36, ""),
}


def slug(info: IndexInfo) -> str:
    return info.short.lower()


def index_url(info: IndexInfo) -> str:
    return reverse("help:index", args=[slug(info)])


def canonical_slug(code: str) -> str | None:
    """The address of the index ``code`` names, in any spelling or as an output name
    (``TX90p``, ``rx3day``, ``wsdi3``, ``24month_spi``), or None."""
    lower = code.lower()
    for info in catalogue():
        if slug(info) == lower:
            return slug(info)
    info = index_for_output(code)
    return slug(info) if info else None


def theme_of(info: IndexInfo):
    return next((t for t in THEMES if info.short in t.shorts), None)


def themes() -> list[tuple]:
    """The themes with indices, in order, each with its indices in the theme's order."""
    known = by_short()
    return [(t, [known[s] for s in t.shorts if s in known]) for t in THEMES if t.shorts]


def scales(info: IndexInfo) -> str:
    if info.short == "tx95t":
        return "DAY"
    return " ".join(f for f, on in (("ANN", info.annual), ("MON", info.monthly)) if on)


def title_name(info: IndexInfo) -> str:
    """The name beside the code in a page's title: the short name, or R's long name where
    the short name only repeats the code."""
    if info.short in LONG_TITLES:
        return gettext(info.long_name)
    return info.short_name()


def unit(info: IndexInfo) -> str:
    return str(UNITS.get(info.units, info.units))


# ---- The hand-written notes --------------------------------------------------------------


@dataclass
class Notes:
    lead: str = ""  # HTML of one paragraph
    caveat: str = ""  # HTML, without "Read with care:"
    paragraphs: list[str] = field(default_factory=list)  # HTML


def _sections(text: str) -> dict[str, str]:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    parts = re.split(r"^## (.+)$", text, flags=re.M)
    return {key.strip(): body.strip() for key, body in zip(parts[1::2], parts[2::2], strict=True)}


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _html(text: str) -> str:
    return markdown.markdown(text, output_format="html")


@lru_cache(maxsize=8)
def _notes(language: str) -> tuple[dict[str, list[str]], dict[str, Notes]]:
    """The notes file in ``language`` (or English): the kinds' paragraphs (Markdown, with
    placeholders) and each index's notes (HTML)."""
    for code in language_candidates(language):
        path = GUIDES_DIR / code / NOTES_FILE
        if path.is_file():
            break
    sections = _sections(path.read_text(encoding="utf-8"))
    kinds, notes = {}, {}
    for key, body in sections.items():
        if key.startswith("kind:"):
            kinds[key.split(":", 1)[1].strip()] = _paragraphs(body)
            continue
        found = Notes()
        for i, paragraph in enumerate(_paragraphs(body)):
            if i == 0:
                found.lead = _html(paragraph)
            elif paragraph.startswith("Read with care:"):
                rest = paragraph.removeprefix("Read with care:").strip()
                found.caveat = _html(rest[:1].upper() + rest[1:])
            else:
                found.paragraphs.append(_html(paragraph))
        notes[key] = found
    return kinds, notes


def notes(short: str) -> Notes:
    return _notes(get_language() or "en")[1].get(short, Notes())


def lead_text(info: IndexInfo) -> str:
    """The lead as plain text: the page's description for search engines."""
    found = notes(info.short)
    return strip_tags(found.lead) if found.lead else gettext(info.definition) + "."


def calculation(info: IndexInfo) -> list[str]:
    """How it is calculated: the kind's paragraphs, then the index's own (HTML)."""
    kinds = _notes(get_language() or "en")[0]
    values = {"code": info.name, "pct": str(PERCENTILES.get(info.short, ""))}
    out = []
    for paragraph in kinds.get(KIND_OF.get(info.short, ""), []):
        out.append(_html(paragraph.format(**values)))
    return out + notes(info.short).paragraphs


# ---- At a glance -------------------------------------------------------------------------


def uses(info: IndexInfo) -> str:
    if info.short in USES_OVERRIDES:
        return USES_OVERRIDES[info.short]
    from climpact.gridded.indices import _BY_VARIABLE

    for variable, shorts in _BY_VARIABLE.items():
        if info.short in shorts:
            label = VARIABLE_LABELS[variable]
            return gettext("TM (the mean of TX and TN)") if label == "TM" else label
    return ""


def time_scales(info: IndexInfo) -> str:
    if info.short == "tx95t":
        return gettext("Daily (DAY): one value for each calendar day")
    if info.short in ("spi", "spei"):
        return gettext("Monthly (MON) only, over 3, 6 and 12 months and one more you choose")
    if info.annual and info.monthly:
        return gettext("Yearly (ANN) and monthly (MON)")
    return gettext("Yearly (ANN) only") if info.annual else gettext("Monthly (MON) only")


BASE_PERIOD = {
    "percentile-count": _(
        "Yes: a percentile for each calendar day, from a 5-day window in the base period "
        "(1971–2000 by default)"
    ),
    "threshold-value": _(
        "Yes: the percentile for each calendar day, from a 5-day window in the base period "
        "(1971–2000 by default)"
    ),
    "spell": _(
        "Yes: a percentile for each calendar day, from a 5-day window in the base period "
        "(1971–2000 by default)"
    ),
    "dual-spell": _(
        "Yes: the percentiles of TX and TN for each calendar day, from a 5-day window in "
        "the base period (1971–2000 by default)"
    ),
    "rain-percentile": _("Yes: a percentile of the wet days of the base period"),
    "drought": _("Yes: the distribution is fitted to the base period's months"),
}
BASE_PERIOD_INDEX = {
    "hw": _("Yes: the 90th percentile for each calendar day, from a 15-day window"),
    "hwEHF": _("Yes: the 95th percentile of TM, and the 85th of positive EHF, in the base period"),
}


def base_period(info: IndexInfo) -> str:
    if not info.base_period:
        return gettext("No")
    text = BASE_PERIOD_INDEX.get(info.short) or BASE_PERIOD.get(KIND_OF.get(info.short, ""))
    return str(text or gettext("Yes"))


def missing_data(info: IndexInfo) -> str:
    from climpact.products.indices import MAX_MISSING_DAYS

    year = gettext(
        "no yearly value when more than %(days)s days of the year, or any month, are missing"
    ) % {"days": MAX_MISSING_DAYS["ANN"]}
    month = gettext("no monthly value when more than %(days)s days of the month are missing") % {
        "days": MAX_MISSING_DAYS["MON"]
    }
    if info.short in ("spi", "spei"):
        text = gettext(
            "a month needs every month of its time scale; a short base period leaves many "
            "months missing"
        )
    elif info.short == "tx95t":
        text = gettext("calculated from the days of the base period that are not missing")
    elif info.annual and info.monthly:
        text = f"{month}; {year}"
    else:
        text = year
    return text[:1].upper() + text[1:]


def _setting(info: IndexInfo) -> tuple[str, str, object, str, object] | None:
    """(field, option, default, unit, example) of the index's setting."""
    topic = INDEX_PARAMS.get(info.short)
    if topic is None:
        return None
    attr = topic.split(".", 1)[1]
    option, example, suffix = SETTING_OPTIONS[attr]
    return attr, option, getattr(IndexParams(), attr), suffix, example


def _number(value) -> str:
    from climpact.products.tables import format_number

    return format_number(value) if isinstance(value, float) else str(value)


def settings_text(info: IndexInfo) -> str:
    setting = _setting(info)
    if setting is None:
        return gettext("None")
    from climpact_web.help.topics import get_topic

    attr, option, default, suffix, example = setting
    name = output_name(info, "ANN" if info.annual else "MON", **{attr: example})
    return gettext(
        "%(label)s: default %(default)s%(unit)s. Set it in the index settings, or with "
        "%(option)s on the command line; the file name carries it: %(example)s%(unit)s is "
        "written %(name)s"
    ) % {
        "label": get_topic(topic_id(info)).title,
        "default": _number(default),
        "unit": suffix,
        "option": option,
        "example": _number(example),
        "name": name,
    }


def topic_id(info: IndexInfo) -> str:
    return INDEX_PARAMS[info.short]


def facts(info: IndexInfo) -> list[tuple[str, str]]:
    return [
        (gettext("Definition (ET-SCI)"), gettext(info.definition)),
        (gettext("Name in Climpact for R"), gettext(info.long_name)),
        (gettext("Unit"), unit(info)),
        (gettext("Time scales"), time_scales(info)),
        (gettext("Uses"), uses(info)),
        (gettext("Base period"), base_period(info)),
        (gettext("Settings"), settings_text(info)),
        (gettext("Missing data"), missing_data(info)),
    ]


# ---- Files and the command line ----------------------------------------------------------


def output_name(info: IndexInfo, freq: str, **params) -> str:
    """The name the core gives the index's output (``rx3day``, ``wsdi1``, ``3month_spi``)
    with the default settings, or with ``params`` changed."""
    from climpact.gridded.indices import _renamed

    p = IndexParams(**params)
    if info.short in ("spi", "spei"):
        return f"{p.spei_months}month_{info.short}"
    return _renamed(info.short, freq, p)[0]


HW_PARTS = ("HWN", "HWF", "HWD", "HWM", "HWA")
EHF_PARTS = ("HWN", "HWF", "HWD", "HWMD", "HWLS", "HWPS", "HWLI", "HWPI")


def files(info: IndexInfo) -> list[tuple[str, str]]:
    """(what, file) of each file the index is written to, for a station and a grid."""
    station = "indices/<station>_"
    if info.short == "hw":
        rows = [
            (
                gettext("Station, yearly"),
                f"{station}TX90-HWN_ANN.csv; "
                + gettext("also %(parts)s, and the same for TN90")
                % {"parts": ", ".join(HW_PARTS[1:])},
            )
        ]
    elif info.short == "hwEHF":
        rows = [
            (
                gettext("Station, yearly"),
                f"{station}EHF-HWN_ANN.csv; "
                + gettext("also %(parts)s") % {"parts": ", ".join(EHF_PARTS[1:])},
            ),
            (gettext("Station, daily"), f"{station}EHFdaily.csv, {station}ECFdaily.csv"),
        ]
    elif info.short in ("spi", "spei"):
        rows = [
            (
                gettext("Station, monthly"),
                ", ".join(
                    f"{station}{n}month_{info.short}_MON.csv"
                    for n in (3, 6, 12, IndexParams().spei_months)
                ),
            )
        ]
    elif info.short == "tx95t":
        rows = [(gettext("Station, daily thresholds"), f"{station}tx95t_DAY.csv")]
    else:
        rows = []
        if info.annual:
            rows.append(
                (gettext("Station, yearly"), f"{station}{output_name(info, 'ANN')}_ANN.csv")
            )
        if info.monthly:
            rows.append(
                (gettext("Station, monthly"), f"{station}{output_name(info, 'MON')}_MON.csv")
            )
    rows += _gridded_files(info)
    return rows


def _gridded_files(info: IndexInfo) -> list[tuple[str, str]]:
    from climpact.gridded.indices import index_files

    labels = {
        "ANN": gettext("Gridded, yearly"),
        "MON": gettext("Gridded, monthly"),
        "DAY": gettext("Gridded, daily thresholds"),
    }
    rows = []
    specs = [spec for spec in index_files(IndexParams()) if spec.index == info.short]
    for spec in sorted(specs, key=lambda spec: ("ANN", "MON", "DAY").index(spec.freq)):
        name = f"{spec.key}_<model>_<scenario>_<run>_<start>-<end>.nc"
        if spec.scaled:
            name += "; " + gettext("a scale dimension: 3, 6 and 12 months")
        elif len(spec.variables) > 1:
            name += "; " + gettext("%(count)s variables") % {"count": len(spec.variables)}
        rows.append((labels[spec.freq], name))
    return rows


def command_line(info: IndexInfo) -> list[dict]:
    """The example on the command line: the run, with the index's option if it has one,
    and a comment naming the file it writes."""
    command = f"climpact run {STATION}.txt --out results"
    setting = _setting(info)
    params = {}
    if setting is not None:
        attr, option, _default, _unit, example = setting
        command += f" {option} {_number(example)}"
        params = {attr: example}
    first = files(info)[0][1].split(";")[0].split(",")[0]
    if params:
        freq = "ANN" if info.annual else "MON"
        if info.short in ("spi", "spei"):
            first = f"indices/<station>_{output_name(info, freq, **params)}_{freq}.csv"
        else:
            first = first.replace(output_name(info, freq), output_name(info, freq, **params))
    written = f"results/{STATION}/" + first.replace("<station>", STATION)
    return [
        {"prompt": "$ ", "text": command, "comment": False},
        {
            "prompt": "",
            "text": "# " + gettext("writes %(file)s") % {"file": written},
            "comment": True,
        },
    ]


# ---- Related, previous and next ----------------------------------------------------------


def related(info: IndexInfo, limit: int = 4) -> list[IndexInfo]:
    """The index's counterpart, then its nearest neighbours in the guide's group."""
    known = by_short()
    out: list[str] = []
    if info.short in COUNTERPARTS:
        out.append(COUNTERPARTS[info.short])
    group = next((shorts for _key, _label, shorts in GROUPS if info.short in shorts), ())
    theme = theme_of(info)
    # The nearest in the guide's group first, then in the theme.
    for members in (group, theme.shorts if theme else ()):
        if info.short not in members:
            continue
        here = members.index(info.short)
        for short in sorted(
            members, key=lambda s: (abs(members.index(s) - here), members.index(s))
        ):
            if short != info.short and short not in out:
                out.append(short)
    return [known[s] for s in out[:limit] if s in known]


def neighbours(info: IndexInfo) -> tuple[IndexInfo | None, IndexInfo | None]:
    theme = theme_of(info)
    known = by_short()
    members = [known[s] for s in theme.shorts if s in known] if theme else []
    if info not in members:
        return None, None
    i = members.index(info)
    return (members[i - 1] if i > 0 else None, members[i + 1] if i + 1 < len(members) else None)


def link(info: IndexInfo | None) -> dict | None:
    if info is None:
        return None
    return {"code": info.name, "name": info.short_name(), "url": index_url(info)}


def references(info: IndexInfo) -> tuple[str, ...]:
    return REFERENCES.get(info.short, (ZHANG_2011,))


# ---- The pages ---------------------------------------------------------------------------


def page(info: IndexInfo) -> dict:
    """Everything the index's page shows."""
    theme = theme_of(info)
    found = notes(info.short)
    previous, following = neighbours(info)
    return {
        "info": info,
        "code": info.name,
        "name": title_name(info),
        "theme": theme,
        "hue": f"hue-{hue_of(theme.key)}" if theme else "hue-other",
        "lead": found.lead,
        "lead_text": lead_text(info),
        "facts": facts(info),
        "calculation": calculation(info),
        "caveat": found.caveat,
        "files": files(info),
        "command_line": command_line(info),
        "related": [link(r) for r in related(info)],
        "references": references(info),
        "previous": link(previous),
        "next": link(following),
    }


def list_rows(query: str = "", theme_key: str = "") -> tuple[list[dict], int, int]:
    """The list page's groups, every row marked ``match`` when it passes ``query`` (words of
    the code, name or definition) and ``theme_key``; and how many match, of how many. The
    rows that do not match are drawn hidden, so the page's script can filter in place."""
    words = [w for w in query.lower().split() if w]
    groups, shown, total = [], 0, 0
    for theme, members in themes():
        rows = []
        for info in members:
            total += 1
            row = {
                "code": info.name,
                "url": index_url(info),
                "name": info.short_name(),
                "definition": gettext(info.definition),
                "unit": unit(info),
                "scales": scales(info),
                "base_period": info.base_period,
            }
            row["search"] = " ".join(
                [info.short, info.name, row["name"], row["definition"]]
            ).lower()
            row["match"] = (not theme_key or theme.key == theme_key) and all(
                w in row["search"] for w in words
            )
            rows.append(row)
        matches = sum(row["match"] for row in rows)
        shown += matches
        groups.append(
            {
                "key": theme.key,
                "label": theme.label,
                "hue": f"hue-{hue_of(theme.key)}",
                "count": len(members),
                "rows": rows,
                "matches": matches,
            }
        )
    return groups, shown, total


def theme_pills(theme_key: str) -> list[dict]:
    pills = [{"key": "", "label": gettext("All"), "hue": "", "count": len(catalogue())}]
    for theme, members in themes():
        pills.append(
            {
                "key": theme.key,
                "label": theme.label,
                "hue": f"hue-{hue_of(theme.key)}",
                "count": len(members),
            }
        )
    for pill in pills:
        pill["current"] = pill["key"] == theme_key
    return pills


def search_entries() -> list[dict]:
    """The index pages for the help's search: title, address and text."""
    out = []
    for info in catalogue():
        text = " ".join(
            [lead_text(info), gettext(info.definition), gettext(info.long_name)]
            + [strip_tags(p) for p in calculation(info)]
        )
        out.append(
            {"title": f"{info.name} {title_name(info)}", "url": index_url(info), "text": text}
        )
    return out

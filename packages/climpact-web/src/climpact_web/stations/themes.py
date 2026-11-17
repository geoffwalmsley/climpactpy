"""The themes of the results page (#175, Decision C of the redesign, #171): what changed at
a station, in the terms people ask about, before the full catalogue.

Four themes get a headline each (Heat, Cold, Rain, Drought); the indices that are neither
extremes of one kind nor the other go on one line each under "Also measured" (averages,
growing season and degree days, the user's own index). The daily EHF and ECF tables have
no trend, so they are left to the catalogue alone.

The mapping is here and nowhere else. It is by the catalogue's short name
(:mod:`climpact_web.help.indices`), so indices whose output name depends on a parameter
(``rx3day``, ``r30mm``, ``wsdi1``, ``hddheat18``, ``24month_spi``) follow their short name
(``rxdday``, ``rnnmm``, ``wsdid``, ``hddheatn``, ``spi``). The heatwave tables share two
short names (``hw``: the Tx90 and Tn90 heatwaves; ``hwEHF``: the EHF heatwaves), all Heat.
A test checks that every short name of the core's file has a place.

The findings are written from the trends, as template sentences in the interface language,
never by hand for a station.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from climpact_web.charts.data import number

# How many of a theme's significant trends its headline shows.
TOP = 3


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    shorts: tuple[str, ...]
    headline: bool  # a theme with a headline, or a line under "Also measured"


THEMES = (
    Theme(
        "heat",
        gettext_lazy("Heat"),
        ("su", "tr", "txge30", "txge35", "txx", "tnx", "tx90p", "tn90p", "tx95t", "wsdi")
        + ("wsdid", "txdtnd", "hw", "hwEHF"),
        True,
    ),
    Theme(
        "cold",
        gettext_lazy("Cold"),
        ("fd", "tnlt2", "tnltm2", "tnltm20", "id", "tnn", "txn", "tx10p", "tn10p", "csdi")
        + ("csdid", "txbdtnbd"),
        True,
    ),
    Theme(
        "rain",
        gettext_lazy("Rain"),
        ("prcptot", "sdii", "r10mm", "r20mm", "rnnmm", "rx1day", "rx5day", "rxdday", "cwd")
        + ("r95p", "r99p", "r95ptot", "r99ptot"),
        True,
    ),
    Theme("drought", gettext_lazy("Drought"), ("spi", "spei", "cdd"), True),
    Theme(
        "averages",
        gettext_lazy("Averages"),
        ("txm", "tnm", "tmm", "txgt50p", "dtr"),
        False,
    ),
    Theme(
        "seasons",
        gettext_lazy("Growing season and degree days"),
        ("gsl", "gddgrown", "hddheatn", "cddcoldn", "tmge5", "tmlt5", "tmge10", "tmlt10"),
        False,
    ),
    Theme("custom", gettext_lazy("Your own index"), (), False),
)

# The colour of each theme (#196): the four headline themes have a hue of their own
# (``--color-heat`` ...), the "Also measured" themes share the neutral ``--color-other``.
# Templates use it as a class, ``hue-<hue>`` (results.css).
HUES = ("heat", "cold", "rain", "drought")
NEUTRAL_HUE = "other"


def hue_of(key: str) -> str:
    """The hue of the theme ``key``: its own for Heat, Cold, Rain and Drought, the neutral
    for the others and for a card in no theme."""
    return key if key in HUES else NEUTRAL_HUE


# Cards in no theme, on purpose: daily values with no trend.
CATALOGUE_ONLY = ("EHFdaily", "ECFdaily")

# The index whose trend the one-sentence summary gives.
MEAN_TEMPERATURE = "tmm"


# The catalogue's filter chips (#200): one per headline theme, and one, "Also measured",
# for every other card (the "Also measured" themes and the daily tables in no theme).
ALSO_MEASURED = "other"


def chip_of(key: str) -> str:
    """The filter chip of a card of the theme ``key``: the headline theme's own, else
    ALSO_MEASURED."""
    return key if key in HUES else ALSO_MEASURED


def by_key() -> dict[str, Theme]:
    return {theme.key: theme for theme in THEMES}


def theme_of(key: str, info) -> str:
    """The theme of the card ``key`` (``info`` its catalogue entry, None for the user's own
    index), or "" for a card left to the catalogue."""
    if key in CATALOGUE_ONLY:
        return ""
    if info is None:
        return "custom"
    for theme in THEMES:
        if info.short in theme.shorts:
            return theme.key
    return ""


# ---- findings ---------------------------------------------------------------------------


def trend_text(card, signed: bool = True) -> str:
    """``+0.65 percentage points per decade``: the card's trend with its units (without
    the sign, ``0.12 °C per decade``, for "rose by")."""
    slope = card.trend["slope_text"] if signed else number(abs(card.trend["slope"]))
    if card.trend_units:
        # A no-break space keeps the number with its units. It is joined here, outside the
        # message: older xgettext (0.21, Ubuntu 24.04) keeps "\u00a0" in a Python msgid as
        # written and newer versions decode it, so the catalogue would differ (#205).
        slope = f"{slope}\u00a0{card.trend_units}"
    return _("%(slope)s per decade") % {"slope": slope}


def finding(cards) -> str:
    """One sentence on the significant trends among ``cards``, counting only those with a
    trend: "4 of 12 indices increased significantly.", "No significant change across 13
    indices."; "" when none has a trend."""
    tested = [c for c in cards if c.trend and c.trend.get("valid")]
    if not tested:
        return ""
    m = len(tested)
    changed = [c for c in tested if c.significant]
    up = sum(1 for c in changed if c.trend["direction"] == "up")
    down = len(changed) - up
    if not changed:
        return ngettext(
            "No significant change in the one index with a trend.",
            "No significant change across %(m)s indices.",
            m,
        ) % {"m": m}
    if not down:
        return ngettext(
            "%(n)s of %(m)s index increased significantly.",
            "%(n)s of %(m)s indices increased significantly.",
            m,
        ) % {"n": up, "m": m}
    if not up:
        return ngettext(
            "%(n)s of %(m)s index decreased significantly.",
            "%(n)s of %(m)s indices decreased significantly.",
            m,
        ) % {"n": down, "m": m}
    return ngettext(
        "%(n)s of %(m)s index changed significantly: %(up)s increased and %(down)s decreased.",
        "%(n)s of %(m)s indices changed significantly: %(up)s increased and %(down)s decreased.",
        m,
    ) % {"n": len(changed), "m": m, "up": up, "down": down}


@dataclass
class ThemeResult:
    theme: Theme
    cards: list = field(default_factory=list)  # in the catalogue's order

    @property
    def key(self) -> str:
        return self.theme.key

    @property
    def label(self) -> str:
        return str(self.theme.label)

    @property
    def hue(self) -> str:
        return hue_of(self.theme.key)

    @property
    def significant(self) -> list:
        return [c for c in self.cards if c.significant]

    @property
    def top(self) -> list:
        """Up to TOP significant trends, the largest change first (see ``Card.change``)."""
        return sorted(self.significant, key=lambda c: -c.change)[:TOP]

    @property
    def finding(self) -> str:
        return finding(self.cards)

    @property
    def badge(self) -> str:
        n = len(self.significant)
        if n:
            return ngettext("%(n)s changed", "%(n)s changed", n) % {"n": n}
        return _("No clear change") if self.finding else _("No trend")


def results(cards) -> list[ThemeResult]:
    """Every theme with at least one card, in the order of THEMES."""
    out = []
    for theme in THEMES:
        members = [c for c in cards if c.theme == theme.key]
        if members:
            out.append(ThemeResult(theme, members))
    return out


def summary(cards, themes: list[ThemeResult], first_year) -> list[str]:
    """The sentences of the one-sentence answer at the top of the page: how many indices
    changed, the mean temperature's trend, and which themes changed."""
    total = len(cards)
    changed = sum(1 for c in cards if c.significant)
    sentences = []
    if changed:
        sentences.append(
            ngettext(
                "%(n)s of %(total)s index changed significantly since %(year)s.",
                "%(n)s of %(total)s indices changed significantly since %(year)s.",
                total,
            )
            % {"n": changed, "total": total, "year": first_year}
        )
    else:
        sentences.append(_("No index changed significantly since %(year)s.") % {"year": first_year})
    mean = next((c for c in cards if c.key == MEAN_TEMPERATURE), None)
    if mean is not None and mean.trend and mean.trend.get("valid"):
        if not mean.significant:
            sentences.append(_("Mean temperature did not change significantly."))
        else:
            text = _("Mean temperature rose by %(trend)s.")
            if mean.trend["direction"] == "down":
                text = _("Mean temperature fell by %(trend)s.")
            sentences.append(text % {"trend": trend_text(mean, signed=False)})
    headline = [t for t in themes if t.theme.headline and t.finding]
    moved = [t.label for t in headline if t.significant]
    still = [t.label for t in headline if not t.significant]
    if moved and still:
        sentences.append(
            _("Changed: %(changed)s. No significant change: %(unchanged)s.")
            % {"changed": _(", ").join(moved), "unchanged": _(", ").join(still)}
        )
    elif moved:
        sentences.append(_("Changed: %(changed)s.") % {"changed": _(", ").join(moved)})
    elif still and changed:
        sentences.append(
            _("No significant change in %(unchanged)s.") % {"unchanged": _(", ").join(still)}
        )
    return sentences

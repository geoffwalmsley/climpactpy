"""The themes of a station's Indices (#175, Decision C of the redesign, #171): the terms
people ask about, which the filter rail filters by (#236) and whose hues colour the dots,
sparklines and charts.

Four themes have a filter and a hue each (Heat, Cold, Rain, Drought); the indices that
are neither extremes of one kind nor the other are under "Also measured" (averages,
growing season and degree days, the user's own index), as are the daily EHF and ECF
tables, which have no theme.

The mapping is here and nowhere else. It is by the catalogue's short name
(:mod:`climpact_web.help.indices`), so indices whose output name depends on a parameter
(``rx3day``, ``r30mm``, ``wsdi1``, ``hddheat18``, ``24month_spi``) follow their short name
(``rxdday``, ``rnnmm``, ``wsdid``, ``hddheatn``, ``spi``). The heatwave tables share two
short names (``hw``: the Tx90 and Tn90 heatwaves; ``hwEHF``: the EHF heatwaves), all Heat.
A test checks that every short name of the core's file has a place.

The theme tiles and their findings went with #236: the one line above the table answers,
and the table is filtered by theme rather than narrated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.utils.translation import gettext_lazy


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    shorts: tuple[str, ...]
    headline: bool  # a theme with a filter of its own, or one under "Also measured"


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

# The index whose trend the Indices' answer line gives (#236).
MEAN_TEMPERATURE = "tmm"


# The filter rail's themes (#200, #236): one per headline theme, and one, "Also
# measured", for every other card (the "Also measured" themes and the daily tables in no
# theme).
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


def results(cards) -> list[ThemeResult]:
    """Every theme with at least one card, in the order of THEMES."""
    out = []
    for theme in THEMES:
        members = [c for c in cards if c.theme == theme.key]
        if members:
            out.append(ThemeResult(theme, members))
    return out

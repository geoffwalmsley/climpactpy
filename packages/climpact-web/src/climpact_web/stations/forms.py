"""Step 1 forms: the station file and the station metadata.

The metadata fields are exactly those of the R app's step 1
(``climpact/modules/singleStationStep1UI.R``): station name, latitude, longitude and the
base period's first and last years. The R defaults are kept for the base period
(1971-2000). Latitude and longitude start empty rather than at R's 0, 0: a forgotten
latitude of 0 silently puts the station in the Southern Hemisphere (see TECHNICAL.md).
"""

from __future__ import annotations

from django import forms
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from climpact_web.jobs.forms import STATION_NAME
from climpact_web.stations.station_file import base_period_days

# climdex.pcic computes no thresholds when this many days of the base period or fewer lie
# between the data's first and last dates (climpact.thresholds.MIN_BASE_DAYS).
MIN_BASE_DAYS = 359

ACCEPT = ".txt,.csv,.dat,.prn,text/plain,text/csv"


class UploadForm(forms.Form):
    station_file = forms.FileField(
        label=_("Station file"),
        help_text=_(
            "A text file of daily data with six columns: year, month, day, precipitation "
            "(mm), maximum and minimum temperature (°C), separated by spaces, tabs or "
            "commas. Missing values are -99.9."
        ),
        widget=forms.ClearableFileInput(attrs={"accept": ACCEPT}),
        error_messages={
            "required": _("Choose a station file."),
            "empty": _("The file is empty."),
        },
    )


# R's defaults (load_data_qc), the same as climpact.config.QCParams (checked by a test;
# the web server does not import the core, which imports xclim).
QC_DEFAULTS = {
    "iqr_temp": 3.0,
    "iqr_prec": 5.0,
    "prec_max": 200.0,
    "temp_max": 50.0,
    "flatline_days": 5,
    "jump": 20.0,
}


def _qc_number(label, help_text, minimum, maximum, unit="", integer=False):
    field_class = forms.IntegerField if integer else forms.FloatField
    limits = {"min_value": minimum}
    if maximum is not None:
        limits["max_value"] = maximum
    if maximum is None:
        range_text = _("Enter a number of at least %(min)s.") % {"min": minimum}
    else:
        range_text = _("Enter a number from %(min)s to %(max)s.") % {
            "min": minimum,
            "max": maximum,
        }
    attrs = {"inputmode": "numeric" if integer else "decimal"}
    if not integer:
        attrs["step"] = "any"
    field = field_class(
        label=label,
        help_text=help_text,
        **limits,
        error_messages={
            "required": range_text,
            "invalid": range_text,
            "min_value": range_text,
            "max_value": range_text,
        },
        widget=forms.NumberInput(attrs=attrs),
    )
    field.unit = unit
    return field


class QCParamsForm(forms.Form):
    """The quality-control thresholds: the six of the R app's step 2
    (``singleStationStep2UI.R``), with its defaults, limits and explanations."""

    iqr_temp = _qc_number(
        _("Outlier range for temperature"),
        _(
            "The number of interquartile ranges beyond the monthly box at which a "
            "temperature counts as an outlier. Default 3."
        ),
        1,
        10,
        _("IQR"),
    )
    iqr_prec = _qc_number(
        _("Outlier range for precipitation"),
        _(
            "The number of interquartile ranges beyond the monthly box (days with rain "
            "only) at which precipitation counts as an outlier. Default 5."
        ),
        1,
        None,
        _("IQR"),
    )
    prec_max = _qc_number(
        _("Largest daily precipitation"),
        _("Daily precipitation above this amount is flagged for checking. Default 200."),
        0,
        1500,
        _("mm"),
    )
    temp_max = _qc_number(
        _("Largest temperature"),
        _(
            "A temperature above this value, or below its negative, is flagged for "
            "checking. Default 50."
        ),
        0,
        60,
        "°C",
    )
    flatline_days = _qc_number(
        _("Days without change"),
        _(
            "A maximum or minimum temperature that stays the same for more than this "
            "many days in a row is flagged. Default 5."
        ),
        3,
        15,
        _("days"),
        integer=True,
    )
    jump = _qc_number(
        _("Day-to-day temperature change"),
        _(
            "A maximum or minimum temperature that changes by this amount or more from "
            "one day to the next is flagged. Default 20."
        ),
        5,
        30,
        "°C",
    )

    @classmethod
    def initial_for(cls, stored: dict | None) -> dict:
        return {**QC_DEFAULTS, **{k: v for k, v in (stored or {}).items() if k in QC_DEFAULTS}}

    def changed_from_defaults(self) -> bool:
        return any(self.cleaned_data[k] != v for k, v in QC_DEFAULTS.items())


class RunAllForm(forms.Form):
    """The whole calculation with default index parameters, from the placeholder of step
    3 until the indices step (#78) exists. A checkbox left unticked is absent
    from the request, so both default to ticked on the page."""

    plots = forms.BooleanField(
        label=_("Draw plots"),
        help_text=_("A plot of every index. They take about two thirds of the time."),
        required=False,
        initial=True,
    )
    zip = forms.BooleanField(
        label=_("Make a zip file of the results"),
        help_text=_("Every result file in one download, in the folder layout of Climpact for R."),
        required=False,
        initial=True,
    )


class MetadataForm(forms.Form):
    """Station metadata, validated against the data (``summary`` from
    :func:`climpact_web.stations.station_file.summarise`)."""

    # The groups validated together as fields change (htmx): each is re-rendered alone.
    UNITS = {
        "station_name": ("station_name",),
        "latitude": ("latitude",),
        "longitude": ("longitude",),
        "base_period": ("base_start", "base_end"),
    }

    station_name = forms.CharField(
        label=_("Station name"),
        max_length=100,
        help_text=_("Used in the names of the result files."),
        validators=[
            RegexValidator(
                STATION_NAME,
                _("Use letters, digits, spaces and . ( ) - _ only, not starting with a dot."),
            )
        ],
        error_messages={"required": _("Enter a station name.")},
    )
    latitude = forms.FloatField(
        label=_("Latitude"),
        min_value=-90,
        max_value=90,
        help_text=_("Decimal degrees, e.g. -40.992. Negative south of the equator."),
        error_messages={
            "required": _("Enter the latitude."),
            "invalid": _("Enter the latitude as a number of degrees, e.g. -40.992."),
            "min_value": _("Latitude must be between -90 and 90."),
            "max_value": _("Latitude must be between -90 and 90."),
        },
        widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}),
    )
    longitude = forms.FloatField(
        label=_("Longitude"),
        min_value=-180,
        max_value=180,
        help_text=_("Decimal degrees, e.g. 148.346. Negative west of Greenwich."),
        error_messages={
            "required": _("Enter the longitude."),
            "invalid": _("Enter the longitude as a number of degrees, e.g. 148.346."),
            "min_value": _("Longitude must be between -180 and 180."),
            "max_value": _("Longitude must be between -180 and 180."),
        },
        widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}),
    )
    base_start = forms.IntegerField(
        label=_("First year"),
        min_value=0,
        max_value=9999,
        error_messages={
            "required": _("Enter the first year of the base period."),
            "invalid": _("Enter a year, e.g. 1971."),
        },
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    base_end = forms.IntegerField(
        label=_("Last year"),
        min_value=0,
        max_value=9999,
        error_messages={
            "required": _("Enter the last year of the base period."),
            "invalid": _("Enter a year, e.g. 2000."),
        },
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )

    def __init__(self, *args, summary: dict | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.summary = summary or {}
        self.warnings: dict[str, list[str]] = {}

    def warn(self, unit: str, message: str) -> None:
        self.warnings.setdefault(unit, []).append(message)

    def clean_station_name(self):
        return self.cleaned_data["station_name"].strip()

    def clean(self):
        data = super().clean()
        if data.get("latitude") == 0:
            self.warn(
                "latitude",
                _(
                    "Latitude 0 is treated as the Southern Hemisphere (as in Climpact for "
                    "R), which decides the season used for the growing season length and "
                    "heatwaves."
                ),
            )
        start, end = data.get("base_start"), data.get("base_end")
        if start is None or end is None:
            return data
        if start > end:
            self.add_error("base_end", _("The last year must not be before the first year."))
            return data
        if not self.summary:
            return data
        first, last = self.summary["first_year"], self.summary["last_year"]
        if end < first or start > last:
            self.add_error(
                "base_end",
                _(
                    "The base period %(start)s-%(end)s has no data: the file covers "
                    "%(first)s to %(last)s. Choose years within that range."
                )
                % {"start": start, "end": end, "first": first, "last": last},
            )
            return data
        days = base_period_days(self.summary, start, end)
        if days <= MIN_BASE_DAYS:
            self.warn(
                "base_period",
                _(
                    "Less than a year of the base period is covered by the data, so the "
                    "percentile thresholds and the indices that use them (TX90p, WSDI, "
                    "R95p and others) cannot be calculated."
                ),
            )
        elif start < first or end > last:
            covered = min(end, last) - max(start, first) + 1
            self.warn(
                "base_period",
                ngettext(
                    "The file covers only %(covered)d year of the base period "
                    "(%(first)s to %(last)s). The thresholds use the years with data.",
                    "The file covers only %(covered)d years of the base period "
                    "(%(first)s to %(last)s). The thresholds use the years with data.",
                    covered,
                )
                % {"covered": covered, "first": first, "last": last},
            )
        return data

    def unit_errors(self, unit: str) -> bool:
        return any(self[name].errors for name in self.UNITS[unit])

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


class RunAllForm(forms.Form):
    """The whole calculation with default parameters, from the placeholder of step 2 until
    the quality (#77) and indices (#78) steps exist. A checkbox left unticked is absent
    from the request, so both default to ticked on the page."""

    plots = forms.BooleanField(label=_("Draw plots"), required=False, initial=True)
    zip = forms.BooleanField(
        label=_("Make a zip file of the results"), required=False, initial=True
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

import re

from django import forms
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

# The station name becomes a folder and file names (the core writes <out>/<name>/...).
STATION_NAME = r"^[\w()\-][\w .()\-]*$"


def safe_station_name(text: str) -> str:
    """A station name from a file name: characters other than letters, digits, spaces and
    ``.()-_`` become ``_``."""
    name = re.sub(r"[^\w .()\-]", "_", text).strip().lstrip(".")
    return name[:100] or "station"


class StationJobForm(forms.Form):
    """A minimal form to start a station run. The real single-station steps (#76-#78)
    replace it; it exists so a run can be started from the browser now."""

    station_file = forms.FileField(
        label=_("Station file"),
        help_text=_("Daily data in Climpact's text format: year month day prcp tmax tmin."),
    )
    name = forms.CharField(
        label=_("Station name"),
        max_length=100,
        required=False,
        validators=[
            RegexValidator(
                STATION_NAME,
                _("Use letters, digits, spaces and . ( ) - _ only, not starting with a dot."),
            )
        ],
        help_text=_("Used in the names of the result files. Default: the file name."),
    )
    latitude = forms.FloatField(label=_("Latitude"), min_value=-90, max_value=90, initial=0)
    longitude = forms.FloatField(label=_("Longitude"), min_value=-180, max_value=180, initial=0)
    base_start = forms.IntegerField(label=_("First year of the base period"), initial=1971)
    base_end = forms.IntegerField(label=_("Last year of the base period"), initial=2000)
    plots = forms.BooleanField(label=_("Draw plots"), required=False, initial=True)
    zip = forms.BooleanField(
        label=_("Make a zip file of the results"), required=False, initial=True
    )

    def clean(self):
        data = super().clean()
        start, end = data.get("base_start"), data.get("base_end")
        if start is not None and end is not None and start > end:
            raise forms.ValidationError(_("The base period must start before it ends."))
        return data

"""Example form for the pattern library: one of each field kind the screens use."""

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class PatternDemoForm(forms.Form):
    station_name = forms.CharField(
        label=_("Station name"),
        help_text=_("Used in output file names. Defaults to the file name."),
        max_length=80,
    )
    latitude = forms.FloatField(
        label=_("Latitude"),
        min_value=-90,
        max_value=90,
        help_text=_("Decimal degrees, negative in the southern hemisphere."),
    )
    base_start = forms.IntegerField(label=_("Base period start"), min_value=1800)
    base_end = forms.IntegerField(label=_("Base period end"), min_value=1800)
    variable = forms.ChoiceField(
        label=_("Variable"),
        choices=[("tx", _("Maximum temperature")), ("tn", _("Minimum temperature"))],
    )
    method = forms.ChoiceField(
        label=_("Trend method"),
        choices=[("ols", _("Least squares")), ("sen", _("Sen's slope"))],
        widget=forms.RadioSelect,
        initial="ols",
    )
    notes = forms.CharField(
        label=_("Notes"), required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    detrend = forms.BooleanField(
        label=_("Detrend data"),
        required=False,
        help_text=_("Remove the linear trend before correlating."),
    )
    station_file = forms.FileField(label=_("Station file"))
    corrected_file = forms.FileField(
        label=_("Corrected file"),
        required=False,
        help_text=_("The checks run again as soon as you choose the file."),
    )

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("base_start"), cleaned.get("base_end")
        if start and end and end <= start:
            self.add_error("base_end", ValidationError(_("The end must be after the start.")))
        return cleaned

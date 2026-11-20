"""The batch's options, Add stations' "Applies to every station" (#233): the fields of the
R app's batch screen (``climpact/modules/batchStep1UI.R``) after its files, the base
period's first and last years and, in the local install, the number of cores; plus the
plots, which R always draws. The batch's own upload forms went with #271; the several-file
field stays for the gridded page."""

from __future__ import annotations

import os

from django import forms
from django.conf import settings
from django.core.validators import MaxValueValidator
from django.utils.translation import gettext_lazy as _

ACCEPT_TEXT = ".txt,.csv,.dat,.prn,text/plain,text/csv"
ACCEPT_FILES = ACCEPT_TEXT + ",.zip,application/zip"


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Several files in one input (Django's documented pattern)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": ACCEPT_FILES}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, list | tuple):
            return [single(d, initial) for d in data]
        return [single(data, initial)] if data else []


def cpu_count() -> int:
    return os.cpu_count() or 1


class OptionsForm(forms.Form):
    """The run's options. ``workers`` is only offered in the local install, as R's
    "Number of cores" is (a hosted server shares its processors)."""

    base_start = forms.IntegerField(
        label=_("First year"),
        min_value=0,
        max_value=9999,
        error_messages={
            "required": _("Enter the first year of the base period."),
            "invalid": _("Enter a year, e.g. 1971."),
            "min_value": _("Enter a year, e.g. 1971."),
            "max_value": _("Enter a year, e.g. 1971."),
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
            "min_value": _("Enter a year, e.g. 2000."),
            "max_value": _("Enter a year, e.g. 2000."),
        },
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    workers = forms.IntegerField(
        label=_("Stations to calculate at the same time"),
        min_value=1,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    plots = forms.BooleanField(
        label=_("Draw the plots of every index and write each station's PDF report"),
        help_text=_(
            "Plots and reports take about two thirds of the time. The tables are written "
            "either way."
        ),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if settings.IS_HOSTED:
            del self.fields["workers"]
            return
        cores = cpu_count()
        field = self.fields["workers"]
        field.max_value = cores
        field.validators.append(MaxValueValidator(cores))
        field.widget.attrs["max"] = cores
        field.help_text = _(
            "Your computer has %(count)d processor cores. Each station runs on one."
        ) % {"count": cores}
        field.error_messages.update(
            {
                "required": _("Enter how many stations to calculate at the same time (1 or more)."),
                "invalid": _("Enter a whole number, e.g. 2."),
                "min_value": _("You need at least 1."),
                "max_value": _("You cannot use more than %(count)d on this computer.")
                % {"count": cores},
            }
        )

    def clean(self):
        data = super().clean()
        start, end = data.get("base_start"), data.get("base_end")
        if start is not None and end is not None and start > end:
            self.add_error("base_end", _("The last year must not be before the first year."))
        return data

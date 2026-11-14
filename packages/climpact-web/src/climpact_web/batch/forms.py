"""The batch page's forms. The fields are those of the R app's batch screen
(``climpact/modules/batchStep1UI.R``): the metadata file, the station files, the base
period's first and last years and, in the local install, the number of cores; plus the
plots, which R always draws."""

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


METADATA_HELP = _(
    "A text file with a line of column names, then one line per station: station_file, "
    "latitude, longitude, wsdin, csdin, Tb_HDD, Tb_CDD, Tb_GDD, rxnday, rnnmm, txtn and "
    "SPEI, separated by spaces or tabs."
)
FILES_HELP = _(
    "Every station file named in the metadata file, in Climpact's six-column format. "
    "Choose several files at once, or a zip of them (the zip may hold the metadata file "
    "too)."
)


class UploadForm(forms.Form):
    metadata_file = forms.FileField(
        label=_("Batch metadata file"),
        help_text=METADATA_HELP,
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": ACCEPT_FILES}),
        error_messages={"empty": _("The metadata file is empty.")},
    )
    station_files = MultipleFileField(
        label=_("Station files"),
        help_text=FILES_HELP,
        required=False,
        error_messages={"empty": _("One of the station files is empty.")},
    )

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        if not data.get("station_files") and not data.get("metadata_file"):
            # R: "Please specify the name of metadata text file (Step 1)." and "Please
            # upload files to process (Step 2)."
            self.add_error("metadata_file", _("Choose the batch metadata file."))
            self.add_error("station_files", _("Choose the station files, or a zip of them."))
        elif not data.get("station_files") and not _is_zip(data.get("metadata_file")):
            self.add_error("station_files", _("Choose the station files, or a zip of them."))
        return data


def _is_zip(uploaded) -> bool:
    return bool(uploaded) and uploaded.name.lower().endswith(".zip")


class AddFilesForm(forms.Form):
    """On the check page: more station files, or a new metadata file."""

    station_files = MultipleFileField(
        label=_("Add or replace station files"),
        help_text=_("Files with the same name as one already loaded replace it. A zip works too."),
        required=False,
    )
    metadata_file = forms.FileField(
        label=_("Replace the metadata file"),
        help_text=_("A new metadata file replaces the one loaded; the stations are checked again."),
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": ACCEPT_TEXT}),
        error_messages={"empty": _("The metadata file is empty.")},
    )

    def clean(self):
        data = super().clean()
        if not self.errors and not data.get("station_files") and not data.get("metadata_file"):
            self.add_error("station_files", _("Choose the files to add."))
        return data


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

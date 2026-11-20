"""The gridded forms. The fields are those of the R app's two gridded screens
(``climpact/modules/griddedStep1UI.R``, indices, and ``griddedStep2UI.R``, thresholds):
the input files, the names of the three variables, the output file name template (or the
thresholds file name), the institution's name and ID, the base period, the number of
cores, the indices to calculate, a thresholds file, the EHF definition and the number of
values processed at once; plus the parameters of the parameterised indices (the command
line's, R's wrapper script values), the rechunking of the core and, in the local install,
a folder to copy the results to."""

from __future__ import annotations

import os
import re
from pathlib import Path

from django import forms
from django.conf import settings
from django.core.validators import MaxValueValidator
from django.utils.translation import gettext_lazy as _

from climpact_web.batch.forms import MultipleFileField, MultipleFileInput, cpu_count
from climpact_web.gridded.inspection import ROLES, Summary, is_netcdf

ACCEPT_NETCDF = ".nc,.nc4,.netcdf,application/netcdf,application/x-netcdf"
MAX_FILES = 200  # a variable may be split across many files, one per year (#291)
MIN_BASE_DAYS = 359  # the core: with this many base-period days or fewer, R stops


def expand(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path.strip().strip('"').strip("'"))))


def path_lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


class PathsForm(forms.Form):
    """Local mode: netCDF files on this computer, by path, read in place."""

    paths = forms.CharField(
        label=_("netCDF files on this computer"),
        help_text=_(
            "One full path per line, e.g. /data/tasmax_day_1991-2010.nc. Use Browse to find "
            "them. The files are read where they are; nothing is copied."
        ),
        widget=forms.Textarea(attrs={"rows": 3, "spellcheck": "false", "autocomplete": "off"}),
        error_messages={"required": _("Enter the path of at least one netCDF file.")},
    )

    def clean_paths(self) -> list[str]:
        lines = path_lines(self.cleaned_data["paths"])
        if not lines:
            raise forms.ValidationError(_("Enter the path of at least one netCDF file."))
        if len(lines) > MAX_FILES:
            raise forms.ValidationError(_("Choose at most %(count)d files.") % {"count": MAX_FILES})
        problems, out = [], []
        for line in lines:
            path = expand(line)
            if not path.is_absolute():
                problems.append(
                    _("%(path)s: give the full path, starting at the top folder.") % {"path": line}
                )
            elif not path.exists():
                problems.append(_("%(path)s: no such file.") % {"path": line})
            elif path.is_dir():
                problems.append(
                    _("%(path)s is a folder: choose the files in it with Browse.") % {"path": line}
                )
            elif not os.access(path, os.R_OK):
                problems.append(_("%(path)s cannot be read (permissions).") % {"path": line})
            elif not is_netcdf(path):
                problems.append(_("%(path)s is not a netCDF file.") % {"path": line})
            else:
                resolved = str(path.resolve())
                if resolved in out:
                    problems.append(_("%(path)s is listed twice.") % {"path": line})
                else:
                    out.append(resolved)
        if problems:
            raise forms.ValidationError(problems)
        return out


class UploadForm(forms.Form):
    """Uploaded netCDF files (both modes, up to GRIDDED_MAX_UPLOAD_MB in all)."""

    files = MultipleFileField(
        label=_("netCDF files"),
        widget=MultipleFileInput(attrs={"accept": ACCEPT_NETCDF}),
        error_messages={"empty": _("One of the files is empty.")},
    )

    def clean_files(self):
        files = self.cleaned_data["files"]
        if not files:
            raise forms.ValidationError(_("Choose one or more netCDF files."))
        if len(files) > MAX_FILES:
            raise forms.ValidationError(_("Choose at most %(count)d files.") % {"count": MAX_FILES})
        problems = []
        for f in files:
            head = f.read(8)
            f.seek(0)
            if not head.startswith((b"CDF\x01", b"CDF\x02", b"CDF\x05", b"\x89HDF\r\n\x1a\n")):
                problems.append(_("%(name)s is not a netCDF file.") % {"name": f.name})
        if problems:
            raise forms.ValidationError(problems)
        return files


class RenameForm(forms.Form):
    """Rename a run (#289): a name of its own, or empty for the one made from its files."""

    name = forms.CharField(
        label=_("Run name"),
        max_length=200,
        required=False,
        help_text=_("Leave it empty for a name made from the files."),
    )


# ---- Set-up --------------------------------------------------------------------------------

TASKS = (
    ("indices", _("Indices")),
    ("thresholds", _("Thresholds file only")),
    ("both", _("Thresholds file, then indices")),
)
THRESHOLD_SOURCES = (
    ("compute", _("Calculate them from the base period of these files")),
    ("file", _("Read them from a thresholds file")),
)
RECHUNK = (
    ("auto", _("Automatic: when the files are chunked by time step")),
    ("yes", _("Always")),
    ("no", _("Never")),
)
TEMPLATE_RE = re.compile(r"^[^/\\_]+(_[^/\\_]+){5,}\.nc$")
FILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*\.nc$")


def index_choices() -> list[tuple[str, list[tuple[str, str]]]]:
    """The indices R's gridded code writes, grouped by the variable they need, as
    ``(group label, [(short name, label)])``; labels name the long name."""
    from climpact.gridded.indices import _BY_VARIABLE, index_files
    from climpact_web.help.indices import LONG_NAME_FIXES

    names = {}
    for spec in index_files():
        names.setdefault(spec.index, LONG_NAME_FIXES.get(spec.index, spec.long_name))
    labels = {
        "tmax": _("Maximum temperature"),
        "tmin": _("Minimum temperature"),
        "prec": _("Precipitation"),
        "tavg": _("Both temperatures"),
    }
    return [
        (labels[var], [(i, f"{i}: {names[i]}") for i in indices if i in names])
        for var, indices in _BY_VARIABLE.items()
    ]


def all_indices() -> list[str]:
    return [i for _group, items in index_choices() for i, _label in items]


SLOW_INDICES = ("hw", "hwEHF", "spi", "spei")


def default_base(first: int | None, last: int | None) -> tuple[int, int]:
    """1971-2000 (WMO's reference period, the command line's default) when the data cover
    it, else R's gridded default 1991-2010 when they do, else the data's first 30 years."""
    if first is None or last is None:
        return 1971, 2000
    for start, end in ((1971, 2000), (1991, 2010), (1961, 1990), (1981, 2010)):
        if first <= start and end <= last:
            return start, end
    return first, min(last, first + 29)


def default_template(first: int | None, last: int | None) -> str:
    from climpact.gridded.indices import DEFAULT_TEMPLATE

    return DEFAULT_TEMPLATE.format(start=first or 1971, end=last or 2000)


def default_thresholds_name(files: list, start: int, end: int) -> str:
    stem = Path(files[0]["name"]).stem if files else "grid"
    stem = re.sub(r"[^A-Za-z0-9._+-]", "_", stem).lstrip("._-") or "grid"
    return f"{stem}.thresholds.{start}-{end}.nc"


def _year(label, example):
    return forms.IntegerField(
        label=label,
        min_value=0,
        max_value=9999,
        error_messages={
            "required": _("Enter a year, e.g. %(year)s.") % {"year": example},
            "invalid": _("Enter a year, e.g. %(year)s.") % {"year": example},
            "min_value": _("Enter a year, e.g. %(year)s.") % {"year": example},
            "max_value": _("Enter a year, e.g. %(year)s.") % {"year": example},
        },
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )


def _number(label, help_text, kind=int, min_value=None, max_value=None, unit_name=""):
    field_class = forms.IntegerField if kind is int else forms.FloatField
    messages = {
        "required": _("Enter a value."),
        "invalid": _("Enter a whole number.") if kind is int else _("Enter a number."),
    }
    if min_value is not None:
        messages["min_value"] = _("Enter %(min)s or more.") % {"min": min_value}
    if max_value is not None:
        messages["max_value"] = _("Enter %(max)s or less.") % {"max": max_value}
    return field_class(
        label=label,
        help_text=help_text,
        min_value=min_value,
        max_value=max_value,
        error_messages=messages,
        widget=forms.NumberInput(attrs={"inputmode": "numeric" if kind is int else "decimal"}),
    )


class SetupForm(forms.Form):
    """Variables, what to calculate and the parameters, checked against the files'
    summary (the base period against their years)."""

    tasmax = forms.ChoiceField(
        label=_("Maximum temperature (TX)"),
        error_messages={"required": _("Choose the variable.")},
    )
    tasmin = forms.ChoiceField(
        label=_("Minimum temperature (TN)"),
        error_messages={"required": _("Choose the variable.")},
    )
    pr = forms.ChoiceField(
        label=_("Precipitation"),
        error_messages={"required": _("Choose the variable.")},
    )

    task = forms.ChoiceField(
        label=_("What to calculate"),
        choices=TASKS,
        widget=forms.RadioSelect,
        initial="indices",
    )
    thresholds_source = forms.ChoiceField(
        label=_("Percentile thresholds for the indices"),
        choices=THRESHOLD_SOURCES,
        widget=forms.RadioSelect,
        initial="compute",
        required=False,
    )
    thresholds_path = forms.CharField(
        label=_("Thresholds file on this computer"),
        help_text=_("The full path of a file written by a thresholds run of Climpact."),
        required=False,
        widget=forms.TextInput(attrs={"spellcheck": "false", "autocomplete": "off"}),
    )
    thresholds_upload = forms.FileField(
        label=_("Thresholds file"),
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": ACCEPT_NETCDF}),
    )

    base_start = _year(_("First year"), 1971)
    base_end = _year(_("Last year"), 2000)

    template = forms.CharField(
        label=_("Output file name format"),
        help_text=_(
            "In the CMIP5 form var_daily_model_scenario_run_start-end.nc, as in Climpact for "
            "R. Each index file takes its name from this, with var replaced by the index."
        ),
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"spellcheck": "false", "autocomplete": "off"}),
    )
    thresholds_name = forms.CharField(
        label=_("Thresholds file name"),
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"spellcheck": "false", "autocomplete": "off"}),
    )
    institution = forms.CharField(
        label=_("Institution name"),
        help_text=_("Written into every output file's metadata."),
        max_length=200,
        error_messages={"required": _("Enter your institution's name.")},
    )
    institution_id = forms.CharField(
        label=_("Institution ID"),
        help_text=_("Usually an abbreviation, e.g. BoM."),
        max_length=60,
        error_messages={"required": _("Enter your institution's ID (usually an abbreviation).")},
    )

    indices = forms.MultipleChoiceField(
        label=_("Indices to calculate"),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        error_messages={"invalid_choice": _("%(value)s is not an index Climpact calculates.")},
    )

    wsdi_days = _number(_("WSDI days"), _("For wsdi<n>: 1 to 10."), int, 1, 10)
    csdi_days = _number(_("CSDI days"), _("For csdi<n>: 1 to 10."), int, 1, 10)
    rx_days = _number(_("Rx days"), _("For rx<n>day."), int, 1)
    txtn_days = _number(_("TXTN days"), _("For tx<n>tn<n> and txb<n>tnb<n>."), int, 1)
    hdd_base = _number(_("Heating base temperature"), _("For hddheat<n>, °C."), float)
    cdd_base = _number(_("Cooling base temperature"), _("For cddcold<n>, °C."), float)
    gdd_base = _number(_("Growing base temperature"), _("For gddgrow<n>, °C."), float)
    rnnmm = _number(_("Rnn threshold"), _("For r<nn>mm, mm."), float, 0)

    workers = forms.IntegerField(
        label=_("Processor cores to use"),
        min_value=1,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    max_values = _number(
        _("Values read at once (millions)"),
        _(
            "Bounds the memory used: about 8 MB per million. Climpact for R calls this the "
            "number of data values to process at once. Do not change it unless you know you "
            "need to."
        ),
        float,
        0.1,
        1000,
    )
    rechunk = forms.ChoiceField(
        label=_("Copy the files to a temporary file laid out by cell first"),
        help_text=_(
            "Files chunked by time step are very slow to read cell by cell; a temporary copy "
            "makes the run much faster on large grids. The values are the same either way."
        ),
        choices=RECHUNK,
        initial="auto",
    )
    tmp_dir = forms.CharField(
        label=_("Folder for the temporary copy"),
        help_text=_("Default: the calculation's own folder."),
        required=False,
        widget=forms.TextInput(attrs={"spellcheck": "false", "autocomplete": "off"}),
    )
    copy_to = forms.CharField(
        label=_("Also copy the results to this folder"),
        help_text=_(
            "A folder on this computer, created if needed. The results can be downloaded "
            "from the results page either way."
        ),
        required=False,
        widget=forms.TextInput(attrs={"spellcheck": "false", "autocomplete": "off"}),
    )

    LOCAL_ONLY = ("thresholds_path", "workers", "tmp_dir", "copy_to")
    PARAMS = (
        "wsdi_days",
        "csdi_days",
        "rx_days",
        "txtn_days",
        "hdd_base",
        "cdd_base",
        "gdd_base",
        "rnnmm",
    )

    def __init__(self, *args, choices=(), summary: Summary | None = None, **kwargs):
        self.summary = summary or Summary()
        self.thresholds_uploaded = kwargs.pop("thresholds_uploaded", "")
        super().__init__(*args, **kwargs)
        empty = [("", _("Choose a variable"))]
        for role in ROLES:
            self.fields[role].choices = empty + list(choices)
        self.fields["indices"].choices = index_choices()
        if settings.IS_HOSTED:
            for name in self.LOCAL_ONLY:
                del self.fields[name]
        else:
            del self.fields["thresholds_upload"]
            cores = cpu_count()
            field = self.fields["workers"]
            field.max_value = cores
            field.validators.append(MaxValueValidator(cores))
            field.widget.attrs.update({"max": cores, "min": 1})
            field.help_text = _(
                "Your computer has %(count)d processor cores. More cores calculate more cells "
                "at the same time."
            ) % {"count": cores}
            field.error_messages.update(
                {
                    "required": _("Enter how many cores to use (1 or more)."),
                    "invalid": _("Enter a whole number, e.g. 2."),
                    "min_value": _("You need at least 1."),
                    "max_value": _("You cannot use more than %(count)d on this computer.")
                    % {"count": cores},
                }
            )

    def clean_template(self) -> str:
        value = (self.cleaned_data.get("template") or "").strip()
        if value and (not TEMPLATE_RE.match(value) or "-" not in value.rsplit("_", 1)[-1]):
            raise forms.ValidationError(
                _(
                    "Use the CMIP5 form var_daily_model_scenario_run_start-end.nc: at least six "
                    "parts separated by _, ending in the years and .nc."
                )
            )
        return value

    def clean_thresholds_name(self) -> str:
        value = (self.cleaned_data.get("thresholds_name") or "").strip()
        if value and not FILE_NAME_RE.match(value):
            raise forms.ValidationError(
                _("Use a file name ending in .nc, with letters, digits and . _ + - only.")
            )
        return value

    def clean_tmp_dir(self) -> str:
        value = (self.cleaned_data.get("tmp_dir") or "").strip()
        if value:
            path = expand(value)
            if not path.is_absolute() or not path.is_dir():
                raise forms.ValidationError(_("Enter the full path of an existing folder."))
            if not os.access(path, os.W_OK):
                raise forms.ValidationError(_("Climpact cannot write to this folder."))
            return str(path)
        return ""

    def clean_copy_to(self) -> str:
        value = (self.cleaned_data.get("copy_to") or "").strip()
        if not value:
            return ""
        path = expand(value)
        if not path.is_absolute():
            raise forms.ValidationError(_("Enter the full path of a folder."))
        if path.exists() and not path.is_dir():
            raise forms.ValidationError(_("This is a file, not a folder."))
        parent = path if path.exists() else next((p for p in path.parents if p.exists()), None)
        if parent is None or not os.access(parent, os.W_OK):
            raise forms.ValidationError(_("Climpact cannot write to this folder."))
        return str(path)

    def clean(self):
        data = super().clean()
        task = data.get("task") or "indices"
        start, end = data.get("base_start"), data.get("base_end")
        if start is not None and end is not None and start > end:
            self.add_error("base_end", _("The last year must not be before the first year."))
            start = end = None
        use_file = task == "indices" and data.get("thresholds_source") == "file"
        if task != "indices":
            data["thresholds_source"] = "compute"
        if use_file:
            if settings.IS_HOSTED:
                if not data.get("thresholds_upload") and not self.thresholds_uploaded:
                    self.add_error("thresholds_upload", _("Choose the thresholds file."))
            else:
                path_text = (data.get("thresholds_path") or "").strip()
                if not path_text:
                    self.add_error("thresholds_path", _("Enter the path of the thresholds file."))
                else:
                    path = expand(path_text)
                    if not path.is_absolute() or not path.is_file():
                        self.add_error("thresholds_path", _("No such file."))
                    elif not is_netcdf(path):
                        self.add_error("thresholds_path", _("This is not a netCDF file."))
                    else:
                        data["thresholds_path"] = str(path.resolve())
        if task in ("thresholds", "both") and not data.get("thresholds_name") and start:
            data["thresholds_name"] = ""
        if start is not None and end is not None and self.summary.first:
            self._check_base_period(start, end, use_file)
        return data

    def _check_base_period(self, start: int, end: int, use_file: bool) -> None:
        from climpact_web.gridded.views import base_days

        s = self.summary
        days = base_days(s, start, end)
        if use_file:
            # R: a thresholds file is only for data outside the base period
            # (check.quantile.validity wants in-base thresholds otherwise).
            if s.first_year <= end and start <= s.last_year:
                self.add_error(
                    "base_end",
                    _(
                        "With a thresholds file, the data must have no day in the base period, "
                        "as in Climpact for R: these files run from %(first)s to %(last)s. Use "
                        "the thresholds file's own base period, or calculate the thresholds "
                        "from these files instead."
                    )
                    % {"first": s.first_year, "last": s.last_year},
                )
        elif days <= MIN_BASE_DAYS:
            self.add_error(
                "base_end",
                _(
                    "The files cover %(days)d days of this base period (%(first)s to "
                    "%(last)s are in the data); at least %(min)d are needed to calculate the "
                    "percentile thresholds."
                )
                % {
                    "days": days,
                    "first": s.first_year,
                    "last": s.last_year,
                    "min": MIN_BASE_DAYS + 1,
                },
            )

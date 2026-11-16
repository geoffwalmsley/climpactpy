"""The index settings form (#78): the Inputs panel's Index settings sheet since #199
("Adjust and recalculate" on Results from #178).

Every field of the R app's step 3 (``climpact/modules/singleStationStep3UI.R``): the plot
title, d for WSDId, CSDId, Rxdday and TXdTNd/TXbdTNbd, the base temperatures of HDDheat,
CDDcold and GDDgrow, nn for Rnnmm, the extra SPEI/SPI time scale and the custom threshold
index (variable, operator, threshold). They are :class:`climpact.config.IndexParams` and
are checked with the core's :func:`climpact.batch.validate_params` (R's
``validate_climdexInputParams``), so the web app accepts exactly what the core and R accept.

R has no EHF definition on this screen: station runs always use Nairn and Fawcett (2013)
("NF13", the only definition ``climdex.hwEHF`` accepts); the page says so.

Additions over R, all optional: the custom index can be left out (R always calculates
it), and the plots and the zip file can be skipped (both on by default, as in R).
"""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

CUSTOM_VARIABLES = [
    ("TN", _("TN, minimum temperature")),
    ("TX", _("TX, maximum temperature")),
    ("TM", _("TM, mean temperature")),
    ("PR", _("PR, precipitation")),
    ("DTR", _("DTR, diurnal temperature range")),
]
CUSTOM_OPERATORS = [
    (">", _("> greater than")),
    (">=", _("≥ greater than or equal to")),
    ("<", _("< less than")),
    ("<=", _("≤ less than or equal to")),
]

# R's validate_climdexInputParams messages (climpact.batch.validate_params) -> the field.
_CORE_MESSAGE_FIELDS = (
    ("WSDId", "wsdi_days"),
    ("CSDId", "csdi_days"),
    ("RXnDAY", "rx_days"),
    ("TXdTNd", "txtn_days"),
    ("Rnnmm", "rnnmm"),
    ("Custom SPEI", "spei_months"),
)

PARAM_FIELDS = (
    "wsdi_days",
    "csdi_days",
    "rx_days",
    "txtn_days",
    "hdd_base",
    "cdd_base",
    "gdd_base",
    "rnnmm",
    "spei_months",
)


def _days(label, help_text, initial, minimum=1, maximum=None, required_message=""):
    kwargs = {"min_value": minimum}
    messages = {
        "required": required_message,
        "invalid": _("Enter a whole number of days."),
        "min_value": _("Enter at least %(limit_value)s."),
        "max_value": _("Enter at most %(limit_value)s."),
    }
    if maximum is not None:
        kwargs["max_value"] = maximum
        messages["min_value"] = messages["max_value"] = _(
            "Enter a whole number from %(low)s to %(high)s."
        ) % {"low": minimum, "high": maximum}
    return forms.IntegerField(
        label=label,
        help_text=help_text,
        initial=initial,
        error_messages=messages,
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "step": "1"}),
        **kwargs,
    )


def _degrees(label, help_text, initial):
    return forms.FloatField(
        label=label,
        help_text=help_text,
        initial=initial,
        error_messages={
            "required": _("Enter a temperature in °C."),
            "invalid": _("Enter a temperature in °C, e.g. 18."),
        },
        widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}),
    )


class IndexParamsForm(forms.Form):
    """The index parameters, validated against the core's rules. ``warnings`` holds notes
    that do not stop the run (an extra time scale already calculated, and so on)."""

    # The groups validated together as they change (htmx): each is re-rendered alone.
    UNITS = {
        "plot_title": ("plot_title",),
        "wsdi_days": ("wsdi_days",),
        "csdi_days": ("csdi_days",),
        "rx_days": ("rx_days",),
        "txtn_days": ("txtn_days",),
        "hdd_base": ("hdd_base",),
        "cdd_base": ("cdd_base",),
        "gdd_base": ("gdd_base",),
        "rnnmm": ("rnnmm",),
        "spei_months": ("spei_months",),
        "custom": ("custom_enabled", "custom_variable", "custom_operator", "custom_threshold"),
    }

    plot_title = forms.CharField(
        label=_("Plot title"),
        max_length=200,
        required=False,
        help_text=_("Leave empty to use the station name."),
    )
    wsdi_days = _days(
        _("Days for WSDId"),
        _("1 to 10. Default 1."),
        1,
        maximum=10,
        required_message=_("Enter the number of days for WSDId."),
    )
    csdi_days = _days(
        _("Days for CSDId"),
        _("1 to 10. Default 1."),
        1,
        maximum=10,
        required_message=_("Enter the number of days for CSDId."),
    )
    rx_days = _days(
        _("Days for Rxdday"),
        _("Default 3."),
        3,
        required_message=_("Enter the number of days for Rxdday."),
    )
    txtn_days = _days(
        _("Days for TXdTNd and TXbdTNbd"),
        _("Default 2."),
        2,
        required_message=_("Enter the number of days for TXdTNd and TXbdTNbd."),
    )
    hdd_base = _degrees(_("Base temperature for HDDheat"), _("Default 18 °C."), 18.0)
    cdd_base = _degrees(_("Base temperature for CDDcold"), _("Default 18 °C."), 18.0)
    gdd_base = _degrees(_("Base temperature for GDDgrow"), _("Default 10 °C."), 10.0)
    rnnmm = forms.FloatField(
        label=_("Precipitation amount for Rnnmm"),
        help_text=_("Default 30 mm."),
        initial=30.0,
        min_value=0,
        error_messages={
            "required": _("Enter an amount of precipitation in mm."),
            "invalid": _("Enter an amount of precipitation in mm, e.g. 30."),
            "min_value": _("Enter 0 mm or more."),
        },
        widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}),
    )
    spei_months = _days(
        _("Extra SPI and SPEI time scale"),
        _("Default 24."),
        24,
        required_message=_("Enter a number of months."),
    )
    spei_months.error_messages["invalid"] = _("Enter a whole number of months.")

    custom_enabled = forms.BooleanField(
        label=_("Calculate a custom threshold index"),
        required=False,
        initial=True,
        help_text=_("Default TN > 0, as in Climpact for R."),
    )
    custom_variable = forms.ChoiceField(
        label=_("Variable"), choices=CUSTOM_VARIABLES, initial="TN", required=False
    )
    custom_operator = forms.ChoiceField(
        label=_("Operator"), choices=CUSTOM_OPERATORS, initial=">", required=False
    )
    custom_threshold = forms.FloatField(
        label=_("Threshold"),
        initial=0.0,
        required=False,
        error_messages={"invalid": _("Enter the threshold as a number, e.g. 40.")},
        widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}),
    )

    plots = forms.BooleanField(
        label=_("Draw the plots"),
        help_text=_("Plots take about two thirds of the time."),
        required=False,
        initial=True,
    )
    zip = forms.BooleanField(
        label=_("Make a zip file of the results"),
        help_text=_("Every result file in one download."),
        required=False,
        initial=True,
    )
    report = forms.BooleanField(
        label=_("Write a PDF report"),
        help_text=_("One PDF to read, print or send."),
        required=False,
        initial=True,
    )
    # The index the user was looking at, so that they return to it after recalculating.
    index = forms.CharField(required=False, widget=forms.HiddenInput, max_length=100)

    def __init__(self, *args, station_title: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self.warnings: dict[str, list[str]] = {}
        self.fields["plot_title"].widget.attrs["placeholder"] = station_title
        # The custom index's fields are needed only when it is chosen (on by default).
        enabled = (
            bool(self.data.get("custom_enabled"))
            if self.is_bound
            else (self.initial.get("custom_enabled", True))
        )
        for name in ("custom_variable", "custom_operator", "custom_threshold"):
            self.fields[name].required = bool(enabled)

    def warn(self, unit: str, message: str) -> None:
        self.warnings.setdefault(unit, []).append(message)

    def unit_errors(self, unit: str) -> bool:
        return any(self[name].errors for name in self.UNITS[unit])

    def clean_plot_title(self):
        return " ".join(self.cleaned_data["plot_title"].split())

    def clean(self):
        data = super().clean()
        if data.get("custom_enabled"):
            if data.get("custom_threshold") is None and not self["custom_threshold"].errors:
                self.add_error("custom_threshold", _("Enter the threshold as a number."))
            if not data.get("custom_variable"):
                self.add_error("custom_variable", _("Choose a variable."))
            if not data.get("custom_operator"):
                self.add_error("custom_operator", _("Choose an operator."))
        if all(name in data and data[name] is not None for name in PARAM_FIELDS):
            self._check_with_core(data)
        self._warnings(data)
        return data

    def _check_with_core(self, data) -> None:
        """The core's own rules (R's ``validate_climdexInputParams``), so nothing the core
        would refuse reaches a job. The fields' own limits catch these first."""
        from climpact.batch import validate_params

        try:
            validate_params(self.index_params(data))
        except ValueError as exc:
            for line in str(exc).splitlines():
                field = next(
                    (f for prefix, f in _CORE_MESSAGE_FIELDS if line.startswith(prefix)), None
                )
                if field and not self[field].errors:
                    self.add_error(field, line)
                elif not field:
                    self.add_error(None, line)

    def _warnings(self, data) -> None:
        same = _("This is the same index as %(index)s, which is always calculated.")
        if data.get("wsdi_days") == 6:
            self.warn("wsdi_days", same % {"index": "WSDI"})
        if data.get("csdi_days") == 6:
            self.warn("csdi_days", same % {"index": "CSDI"})
        if data.get("rx_days") in (1, 5):
            self.warn("rx_days", same % {"index": f"Rx{data['rx_days']}day"})
        if data.get("rnnmm") in (10, 20):
            self.warn("rnnmm", same % {"index": f"R{int(data['rnnmm'])}mm"})
        if data.get("spei_months") in (3, 6, 12):
            self.warn(
                "spei_months",
                _(
                    "SPI and SPEI over %(n)s months are always calculated, so no extra "
                    "time scale is added."
                )
                % {"n": data["spei_months"]},
            )

    # ---- what the job is given -------------------------------------------------------

    def index_params(self, data=None):
        """The :class:`~climpact.config.IndexParams` of the cleaned data."""
        from climpact.config import CustomIndex, IndexParams

        data = self.cleaned_data if data is None else data
        custom = None
        if data.get("custom_enabled"):
            custom = CustomIndex(
                variable=data.get("custom_variable") or "TN",
                operator=data.get("custom_operator") or ">",
                threshold=float(data.get("custom_threshold") or 0.0),
            )
        return IndexParams(**{name: data[name] for name in PARAM_FIELDS}, custom=custom)

    def job_params(self) -> dict:
        """The ``params`` of the ``station`` runner (``jobs.runners.index_params``)."""
        data = self.cleaned_data
        params = {name: data[name] for name in PARAM_FIELDS}
        params["custom"] = (
            {
                "variable": data["custom_variable"],
                "operator": data["custom_operator"],
                "threshold": float(data["custom_threshold"]),
            }
            if data.get("custom_enabled")
            else None
        )
        return params


def initial_from_params(
    params: dict | None, plot_title: str = "", plots=True, zip=True, report=True
) -> dict:
    """Form values from a job's ``params`` (or a batch station's), defaults elsewhere."""
    params = dict(params or {})
    initial = {name: params[name] for name in PARAM_FIELDS if name in params}
    if "custom" in params:
        custom = params["custom"]
        initial["custom_enabled"] = custom is not None
        if custom:
            initial["custom_variable"] = custom.get("variable", "TN")
            initial["custom_operator"] = custom.get("operator", ">")
            initial["custom_threshold"] = custom.get("threshold", 0.0)
    initial["plot_title"] = plot_title
    initial["plots"] = plots
    initial["zip"] = zip
    initial["report"] = report
    return initial

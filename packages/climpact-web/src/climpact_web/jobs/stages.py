"""Readable names for the core's progress stages (:mod:`climpact.progress`)."""

from __future__ import annotations

from django.utils.translation import gettext as _

# Whole stage names, or the part before the first ":". A stage's own ids (the module, the
# index or file after the ":") mean nothing to a user and are not shown (#226): the
# progress reads "Calculating the indices · 7%".
_LABELS = {
    "read": lambda: _("Reading the data"),
    "write": lambda: _("Writing the results"),
    "zip": lambda: _("Making the zip file"),
    "qc": lambda: _("Checking the data quality"),
    "homogeneity": lambda: _("Checking homogeneity"),
    "indices": lambda: _("Calculating the indices"),
    "plots": lambda: _("Drawing the plots"),
    "report": lambda: _("Writing the PDF report"),
    "rechunk": lambda: _("Preparing the input files"),
    "thresholds": lambda: _("Calculating the thresholds"),
    "trends": lambda: _("Trends and the map"),
    "correlate": lambda: _("Calculating the correlations"),
    "failed": lambda: _("Failed"),
}


def stage_label(stage: str) -> str:
    """``"indices:climpact:spi"`` -> "Calculating the indices"; a batch's
    ``"<station>: <stage>"`` -> "<station>: <label>"; a stage it does not know is shown
    as it is."""
    if not stage:
        return ""
    station, sep, rest = stage.rpartition(": ")
    if sep:
        return f"{station}: {stage_label(rest)}"
    head = _LABELS.get(stage.split(":")[0])
    return stage if head is None else head()

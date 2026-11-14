"""Readable names for the core's progress stages (:mod:`climpact.progress`)."""

from __future__ import annotations

from django.utils.translation import gettext as _

# Whole stage names, or the part before the first ":".
_LABELS = {
    "read": lambda: _("Reading the data"),
    "write": lambda: _("Writing the results"),
    "zip": lambda: _("Making the zip file"),
    "qc": lambda: _("Checking the data quality"),
    "homogeneity": lambda: _("Checking homogeneity"),
    "indices": lambda: _("Calculating indices"),
    "plots": lambda: _("Drawing plots"),
    "rechunk": lambda: _("Preparing the input files"),
    "thresholds": lambda: _("Calculating thresholds"),
    "correlate": lambda: _("Calculating correlations"),
    "failed": lambda: _("Failed"),
}


def stage_label(stage: str) -> str:
    """``"indices:climpact:spi"`` -> "Calculating indices (spi)"; a batch's
    ``"<station>: <stage>"`` -> "<station>: <label>"."""
    if not stage:
        return ""
    station, sep, rest = stage.rpartition(": ")
    if sep:
        return f"{station}: {stage_label(rest)}"
    parts = stage.split(":")
    head = _LABELS.get(parts[0])
    if head is None:
        return stage
    detail = parts[-1] if len(parts) > 1 and parts[-1] not in ("climpact",) else ""
    if parts[0] in ("qc", "homogeneity"):
        detail = ""  # the module name means nothing to a user
    if parts[0] == "write" and len(parts) > 1:
        detail = parts[1]
    return f"{head()} ({detail})" if detail else head()

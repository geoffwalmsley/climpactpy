"""Python port of Climpact: indices of daily climate extremes."""

__version__ = "0.1.0rc1"

# Register the climdex missing-data method with xclim.
from climpact import missing as _missing  # noqa: E402, F401

import numpy as np
import pandas as pd
import pytest
import xarray as xr
import xclim

import climpact  # noqa: F401  (registers the "climdex" missing method)
from climpact.missing import climdex_missing, valid_mask


def series(year=2001, missing_dates=()):
    time = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    values = np.full(time.size, -5.0)
    da = xr.DataArray(
        values,
        dims="time",
        coords={"time": time},
        attrs={"units": "degC", "standard_name": "air_temperature"},
    )
    for d in missing_dates:
        da.loc[d] = np.nan
    return da


def month_flags(da):
    return climdex_missing(da.notnull(), "MS").values.tolist()


def test_month_missing_only_above_three_days():
    three = series(missing_dates=["2001-01-01", "2001-01-02", "2001-01-03"])
    four = series(missing_dates=["2001-01-01", "2001-01-02", "2001-01-03", "2001-01-04"])
    assert month_flags(three)[0] is False
    assert month_flags(four)[0] is True


def test_year_missing_above_fifteen_days_even_if_every_month_valid():
    # 3 missing days in each of 6 months = 18 missing days, no month over the limit
    days = [f"2001-{m:02d}-{d:02d}" for m in range(1, 7) for d in (1, 2, 3)]
    da = series(missing_dates=days)
    assert not any(month_flags(da))
    assert bool(climdex_missing(da.notnull(), "YS").item()) is True


def test_year_missing_if_any_month_missing():
    da = series(missing_dates=[f"2001-07-{d:02d}" for d in range(1, 5)])  # 4 days
    assert bool(climdex_missing(da.notnull(), "YS").item()) is True


def test_year_valid_with_fifteen_scattered_missing_days():
    days = [f"2001-{m:02d}-01" for m in range(1, 13)] + ["2001-01-02", "2001-02-02", "2001-03-02"]
    da = series(missing_dates=days)
    assert bool(climdex_missing(da.notnull(), "YS").item()) is False


def test_valid_mask_combines_variables():
    a = series(missing_dates=[f"2001-01-{d:02d}" for d in range(1, 5)])
    b = series(missing_dates=[f"2001-02-{d:02d}" for d in range(1, 5)])
    mask = valid_mask(a, b, freq="MS").values.tolist()
    assert mask[:3] == [False, False, True]


def test_rejects_other_frequencies():
    with pytest.raises(ValueError, match="monthly or annual"):
        climdex_missing(series().notnull(), "QS-DEC")


@pytest.mark.parametrize("freq", ["MS", "YS"])
def test_xclim_indicator_uses_climdex_rules(freq):
    da = series(missing_dates=[f"2001-03-{d:02d}" for d in range(1, 5)])
    with xclim.set_options(check_missing="climdex"):
        out = xclim.atmos.frost_days(tasmin=da, freq=freq)
    fd = out["frost_days"] if isinstance(out, xr.Dataset) else out
    expected = climdex_missing(da.notnull(), freq)
    assert (fd.isnull().values == expected.values).all()

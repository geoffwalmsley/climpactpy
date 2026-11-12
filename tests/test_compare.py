import numpy as np
import pandas as pd

from climpact.compare import Tier, compare_tables


def table(values, dates=None):
    data = {"time": [1936.0, 1937.0, 1938.0], "val": values}
    if dates is not None:
        data["ymd"] = pd.Series(dates, dtype=object)
    return pd.DataFrame(data)


def test_identical_tables_match_in_every_tier():
    t = table([1.0, np.nan, 3.0], ["1936-01-01", None, "1938-01-01"])
    for tier in Tier:
        assert compare_tables(t, t.copy(), tier).ok


def test_exact_tier_rejects_any_difference():
    result = compare_tables(table([1.0, 2.0, 3.0]), table([1.0, 2.0, 3.0 + 1e-12]), Tier.EXACT)
    assert not result.ok
    assert "1/3 values differ" in result.summary()


def test_close_tier_uses_relative_tolerance():
    expected = table([1000.0, 2.0, 3.0])
    assert compare_tables(expected, table([1000.0005, 2.0, 3.0]), Tier.CLOSE).ok
    assert not compare_tables(expected, table([1000.01, 2.0, 3.0]), Tier.CLOSE).ok


def test_fitted_tier_allows_up_to_one_percent_outside_tolerance():
    n = 200
    expected = pd.DataFrame({"spi": np.linspace(-2, 2, n)})
    actual = expected.copy()
    actual.loc[0, "spi"] += 0.5  # 1 of 200 off: 99.5% within tolerance
    assert compare_tables(expected, actual, Tier.FITTED).ok
    actual.loc[1:3, "spi"] += 0.5  # 4 of 200 off: 98% within tolerance
    assert not compare_tables(expected, actual, Tier.FITTED).ok


def test_missing_value_pattern_must_match_in_every_tier():
    for tier in Tier:
        result = compare_tables(table([1.0, 2.0, 3.0]), table([1.0, np.nan, 3.0]), tier)
        assert not result.ok
        assert "1 missing-value mismatches" in result.summary()


def test_dates_are_compared_exactly():
    expected = table([1.0, 2.0, 3.0], ["1936-01-01", "1937-01-01", None])
    actual = table([1.0, 2.0, 3.0], ["1936-01-01", "1937-01-02", None])
    assert not compare_tables(expected, actual, Tier.CLOSE).ok


def test_column_tier_override():
    expected = pd.DataFrame({"n": [1.0, 2.0], "anomaly": [0.5, -0.5]})
    actual = pd.DataFrame({"n": [1.0, 2.0], "anomaly": [0.5 + 1e-12, -0.5]})
    assert not compare_tables(expected, actual, Tier.EXACT).ok
    assert compare_tables(expected, actual, Tier.EXACT, {"anomaly": Tier.CLOSE}).ok


def test_column_and_row_mismatches_are_reported():
    expected = table([1.0, 2.0, 3.0])
    assert (
        "columns differ"
        in compare_tables(expected, expected.rename(columns={"val": "x"}), Tier.EXACT).summary()
    )
    assert "row count differs" in compare_tables(expected, expected.iloc[:2], Tier.EXACT).summary()

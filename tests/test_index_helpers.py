import numpy as np

from climpact.config import CustomIndex
from climpact.products.indices import running_sum_centred, series_lengths_at_ends
from climpact.products.tables import format_number, standardise


def test_series_lengths_at_ends():
    flags = np.array([True, True, True, False, True, False, True, True, True, True, False])
    assert series_lengths_at_ends(flags).tolist() == [0, 0, 3, 0, 1, 0, 0, 0, 0, 4, 0]


def test_running_sum_is_centred_and_zero_padded():
    pr = np.array([1.0, 2.0, np.nan, 4.0, 5.0, 6.0])
    # 3-day centred windows; missing day counts as 0; ends padded with 0
    expected = np.array([0.0, 3.0, 6.0, 9.0, 15.0, 0.0]) / 3
    assert np.allclose(running_sum_centred(pr, 3), expected)


def test_standardise_uses_sample_sd_and_handles_constants():
    out = standardise(np.array([1.0, 2.0, 3.0, np.nan]))
    assert np.allclose(out[:3], [-1.0, 0.0, 1.0])
    assert np.isnan(out[3])
    assert np.isnan(standardise(np.array([0.0, 0.0, 0.0]))).all()
    assert np.isnan(standardise(np.array([5.0]))).all()


def test_parameter_names_match_r():
    assert format_number(30.0) == "30"
    assert format_number(12.5) == "12.5"
    assert CustomIndex("TN", ">", 0).name == "TNgt0"
    assert CustomIndex("TX", "<=", -2.5).name == "TXle-2.5"

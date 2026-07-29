import numpy as np
import pandas as pd

from app.indicators import technical as ti


def test_sma_matches_manual_mean():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    result = ti.sma(s, window=3)
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == 2.0
    assert result.iloc[4] == 4.0


def test_ema_converges_toward_constant_series():
    s = pd.Series([10.0] * 30)
    result = ti.ema(s, window=10)
    assert abs(result.iloc[-1] - 10.0) < 1e-6


def test_rsi_is_bounded_and_high_in_pure_uptrend():
    s = pd.Series(np.linspace(100, 200, 60))
    result = ti.rsi(s, window=14)
    valid = result.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()
    assert valid.iloc[-1] > 90


def test_rsi_is_low_in_pure_downtrend():
    s = pd.Series(np.linspace(200, 100, 60))
    result = ti.rsi(s, window=14)
    assert result.dropna().iloc[-1] < 10


def test_macd_histogram_equals_line_minus_signal():
    s = pd.Series(np.linspace(100, 150, 80)) + np.sin(np.linspace(0, 10, 80))
    macd_line, signal_line, hist = ti.macd(s)
    diff = (macd_line - signal_line - hist).dropna()
    assert (diff.abs() < 1e-9).all()


def test_bollinger_bands_ordering():
    s = pd.Series(np.linspace(100, 150, 80)) + np.sin(np.linspace(0, 10, 80))
    upper, middle, lower = ti.bollinger_bands(s, window=20, num_std=2)
    valid = pd.DataFrame({"upper": upper, "middle": middle, "lower": lower}).dropna()
    assert (valid["upper"] >= valid["middle"]).all()
    assert (valid["middle"] >= valid["lower"]).all()


def test_atr_nonnegative():
    df = pd.DataFrame(
        {
            "High": [10, 11, 12, 11, 13],
            "Low": [9, 9.5, 10.5, 9.5, 11],
            "Close": [9.5, 10.5, 11.5, 10, 12],
        }
    )
    result = ti.atr(df, window=3)
    assert (result.dropna() >= 0).all()

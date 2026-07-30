"""Technical indicators used by the strategies and the recommendation engine.

All functions take/return pandas Series (or a tuple of Series) aligned to the
input index, so they can be assigned straight back onto a price DataFrame.
"""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()

    rs = avg_gain / avg_loss
    result = 100 - (100 / (1 + rs))
    result = result.where(avg_loss != 0, 100)  # no losses in the window -> RSI 100
    result = result.where((avg_gain != 0) | (avg_loss != 0), 50)  # no movement -> RSI 50
    return result


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(
    series: pd.Series, window: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = sma(series, window)
    std = series.rolling(window=window, min_periods=window).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()


def adx(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average Directional Index: trend *strength*, not direction — high
    values (roughly >25-40) mean a strong trend, low values (roughly <15-20)
    mean a range-bound/choppy market. Needs about 2×window bars to stabilize
    (NaN before that), the same warm-up shape as the other Wilder-smoothed
    indicators here."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_high, prev_low, prev_close = high.shift(1), low.shift(1), close.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    smoothed_tr = tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    smoothed_plus_dm = plus_dm.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    smoothed_minus_dm = minus_dm.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()

    plus_di = 100 * smoothed_plus_dm / smoothed_tr
    minus_di = 100 * smoothed_minus_dm / smoothed_tr
    di_sum = plus_di + minus_di
    dx = (100 * (plus_di - minus_di).abs() / di_sum).where(di_sum != 0, 0.0)
    return dx.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()

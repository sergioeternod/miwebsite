from __future__ import annotations

import pandas as pd

from app.indicators.technical import macd, sma
from app.strategies.base import Strategy


class TrendConfirmationStrategy(Strategy):
    """Trend-filtered momentum: only goes long while MACD is bullish AND
    price is above a long-term SMA (the trend filter); mirrors that for
    shorts. This is a "confirmation" style strategy — it trades less often
    than a raw MACD crossover, aiming to skip momentum signals that fight
    the prevailing trend and so raise the average profit per trade at the
    cost of fewer trades.

    Exit is a plain opposite-momentum flip (no trend filter), acting as the
    risk control: once momentum turns against the position, get out
    regardless of what the long-term trend is doing.
    """

    def __init__(
        self,
        trend_window: int = 100,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        allow_short: bool = True,
    ):
        super().__init__(allow_short=allow_short)
        self.trend_window = trend_window
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.name = f"trend_confirmation_{trend_window}_{fast}_{slow}_{signal}"

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["sma_trend"] = sma(df["Close"], self.trend_window)
        macd_line, signal_line, histogram = macd(df["Close"], self.fast, self.slow, self.signal)
        df["macd_line"] = macd_line
        df["macd_signal"] = signal_line
        df["macd_hist"] = histogram
        return df

    def generate_signals(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        # Level conditions (not one-off crossing events): the state machine in
        # stateful_positions only acts on them while flat, so this naturally
        # enters on the first bar both line up — including right as the SMA
        # trend filter finishes its own warm-up — instead of requiring MACD to
        # cross at that exact same bar.
        bullish_momentum = df["macd_line"] > df["macd_signal"]
        bearish_momentum = df["macd_line"] < df["macd_signal"]
        uptrend = df["Close"] > df["sma_trend"]
        downtrend = df["Close"] < df["sma_trend"]

        return {
            "long_entry": bullish_momentum & uptrend,
            "long_exit": bearish_momentum,
            "short_entry": bearish_momentum & downtrend,
            "short_exit": bullish_momentum,
        }

    def explain(self, df: pd.DataFrame) -> dict:
        last = df.iloc[-1]
        trend = None
        if pd.notna(last["sma_trend"]):
            trend = "alcista" if last["Close"] > last["sma_trend"] else "bajista"
        return {
            "sma_trend": round(float(last["sma_trend"]), 4) if pd.notna(last["sma_trend"]) else None,
            "trend": trend,
            "macd_line": round(float(last["macd_line"]), 4) if pd.notna(last["macd_line"]) else None,
            "macd_signal": round(float(last["macd_signal"]), 4) if pd.notna(last["macd_signal"]) else None,
        }

from __future__ import annotations

import pandas as pd

from app.indicators.technical import rsi
from app.strategies.base import Strategy


class RsiMeanReversionStrategy(Strategy):
    """Mean reversion: long a confirmed bounce off oversold, short a confirmed
    turn down from overbought (if allow_short)."""

    def __init__(
        self, window: int = 14, oversold: float = 30, overbought: float = 70, allow_short: bool = True
    ):
        super().__init__(allow_short=allow_short)
        if oversold >= overbought:
            raise ValueError("oversold debe ser menor que overbought")
        self.window = window
        self.oversold = oversold
        self.overbought = overbought
        self.name = f"rsi_reversion_{window}_{int(oversold)}_{int(overbought)}"

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = rsi(df["Close"], self.window)
        return df

    def generate_signals(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        rsi_series = df["rsi"]
        prev = rsi_series.shift(1)
        # Bottom confirmed: RSI bounces back up through the oversold line.
        bottom_reversal = (rsi_series >= self.oversold) & (prev < self.oversold)
        # Top confirmed: RSI turns back down through the overbought line.
        top_reversal = (rsi_series < self.overbought) & (prev >= self.overbought)
        return {
            "long_entry": bottom_reversal,
            "long_exit": top_reversal,
            "short_entry": top_reversal,
            "short_exit": bottom_reversal,
        }

    def explain(self, df: pd.DataFrame) -> dict:
        last = df.iloc[-1]
        return {
            "rsi": round(float(last["rsi"]), 2) if pd.notna(last["rsi"]) else None,
            "oversold": self.oversold,
            "overbought": self.overbought,
        }

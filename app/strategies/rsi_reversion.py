from __future__ import annotations

import pandas as pd

from app.indicators.technical import rsi
from app.strategies.base import Strategy, stateful_positions


class RsiMeanReversionStrategy(Strategy):
    """Mean reversion: buy a confirmed bounce off oversold, sell a confirmed
    turn down from overbought."""

    def __init__(self, window: int = 14, oversold: float = 30, overbought: float = 70):
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

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        rsi_series = df["rsi"]
        prev = rsi_series.shift(1)
        entry = (rsi_series >= self.oversold) & (prev < self.oversold)
        exit_ = (rsi_series >= self.overbought) & (prev < self.overbought)
        return stateful_positions(entry, exit_)

    def explain(self, df: pd.DataFrame) -> dict:
        last = df.iloc[-1]
        return {
            "rsi": round(float(last["rsi"]), 2) if pd.notna(last["rsi"]) else None,
            "oversold": self.oversold,
            "overbought": self.overbought,
        }

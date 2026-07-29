from __future__ import annotations

import pandas as pd

from app.indicators.technical import bollinger_bands
from app.strategies.base import Strategy, _crosses_above, _crosses_below, stateful_positions


class BollingerBreakoutStrategy(Strategy):
    """Momentum breakout: go long when price breaks above the upper band,
    exit when it falls back below the middle band (the moving average)."""

    def __init__(self, window: int = 20, num_std: float = 2.0):
        self.window = window
        self.num_std = num_std
        self.name = f"bollinger_breakout_{window}_{num_std}"

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        upper, middle, lower = bollinger_bands(df["Close"], self.window, self.num_std)
        df["bb_upper"] = upper
        df["bb_middle"] = middle
        df["bb_lower"] = lower
        return df

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        entry = _crosses_above(df["Close"], df["bb_upper"])
        exit_ = _crosses_below(df["Close"], df["bb_middle"])
        return stateful_positions(entry, exit_)

    def explain(self, df: pd.DataFrame) -> dict:
        last = df.iloc[-1]
        return {
            "close": round(float(last["Close"]), 4),
            "bb_upper": round(float(last["bb_upper"]), 4) if pd.notna(last["bb_upper"]) else None,
            "bb_middle": round(float(last["bb_middle"]), 4) if pd.notna(last["bb_middle"]) else None,
            "bb_lower": round(float(last["bb_lower"]), 4) if pd.notna(last["bb_lower"]) else None,
        }

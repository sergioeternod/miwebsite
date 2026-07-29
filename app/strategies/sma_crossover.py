from __future__ import annotations

import pandas as pd

from app.indicators.technical import sma
from app.strategies.base import Strategy, _crosses_above, _crosses_below


class SmaCrossoverStrategy(Strategy):
    """Trend-following: long when the fast SMA crosses above the slow SMA,
    short when it crosses below (if allow_short)."""

    def __init__(self, fast: int = 20, slow: int = 50, allow_short: bool = True):
        super().__init__(allow_short=allow_short)
        if fast >= slow:
            raise ValueError("fast debe ser menor que slow")
        self.fast = fast
        self.slow = slow
        self.name = f"sma_crossover_{fast}_{slow}"

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["sma_fast"] = sma(df["Close"], self.fast)
        df["sma_slow"] = sma(df["Close"], self.slow)
        return df

    def generate_signals(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        crosses_up = _crosses_above(df["sma_fast"], df["sma_slow"])
        crosses_down = _crosses_below(df["sma_fast"], df["sma_slow"])
        return {
            "long_entry": crosses_up,
            "long_exit": crosses_down,
            "short_entry": crosses_down,
            "short_exit": crosses_up,
        }

    def explain(self, df: pd.DataFrame) -> dict:
        last = df.iloc[-1]
        return {
            "sma_fast": round(float(last["sma_fast"]), 4) if pd.notna(last["sma_fast"]) else None,
            "sma_slow": round(float(last["sma_slow"]), 4) if pd.notna(last["sma_slow"]) else None,
        }

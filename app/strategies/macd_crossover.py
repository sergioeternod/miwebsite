from __future__ import annotations

import pandas as pd

from app.indicators.technical import macd
from app.strategies.base import Strategy, _crosses_above, _crosses_below, stateful_positions


class MacdCrossoverStrategy(Strategy):
    """Trend-following: go long when the MACD line crosses above its signal line."""

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.name = f"macd_crossover_{fast}_{slow}_{signal}"

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        macd_line, signal_line, histogram = macd(df["Close"], self.fast, self.slow, self.signal)
        df["macd_line"] = macd_line
        df["macd_signal"] = signal_line
        df["macd_hist"] = histogram
        return df

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        entry = _crosses_above(df["macd_line"], df["macd_signal"])
        exit_ = _crosses_below(df["macd_line"], df["macd_signal"])
        return stateful_positions(entry, exit_)

    def explain(self, df: pd.DataFrame) -> dict:
        last = df.iloc[-1]
        return {
            "macd_line": round(float(last["macd_line"]), 4) if pd.notna(last["macd_line"]) else None,
            "macd_signal": round(float(last["macd_signal"]), 4) if pd.notna(last["macd_signal"]) else None,
            "macd_hist": round(float(last["macd_hist"]), 4) if pd.notna(last["macd_hist"]) else None,
        }

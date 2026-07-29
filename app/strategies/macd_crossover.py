from __future__ import annotations

import pandas as pd

from app.indicators.technical import macd
from app.strategies.base import Strategy, _crosses_above, _crosses_below


class MacdCrossoverStrategy(Strategy):
    """Trend-following: long when the MACD line crosses above its signal line,
    short when it crosses below (if allow_short)."""

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9, allow_short: bool = True):
        super().__init__(allow_short=allow_short)
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

    def generate_signals(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        crosses_up = _crosses_above(df["macd_line"], df["macd_signal"])
        crosses_down = _crosses_below(df["macd_line"], df["macd_signal"])
        return {
            "long_entry": crosses_up,
            "long_exit": crosses_down,
            "short_entry": crosses_down,
            "short_exit": crosses_up,
        }

    def explain(self, df: pd.DataFrame) -> dict:
        last = df.iloc[-1]
        return {
            "macd_line": round(float(last["macd_line"]), 4) if pd.notna(last["macd_line"]) else None,
            "macd_signal": round(float(last["macd_signal"]), 4) if pd.notna(last["macd_signal"]) else None,
            "macd_hist": round(float(last["macd_hist"]), 4) if pd.notna(last["macd_hist"]) else None,
        }
